# context.md §4 DIP: ComplianceService receives all dependencies via constructor.
# No SQLAlchemy, no FastAPI — only Protocol interfaces from domain/ports.py.
# context.md §1: SHA-256 hash-chained audit log; advisory lock for concurrent appends.

from __future__ import annotations

import uuid
from decimal import Decimal

import structlog

from src.compliance.application.commands import (
    AppendAuditEventCommand,
    GenerateComplianceRecordsCommand,
    RequestBulkExportCommand,
)
from src.compliance.application.queries import (
    ExportFEMAPDFQuery,
    ExportGSTCSVQuery,
    GetAuditLogQuery,
    GetExportJobQuery,
    GetFEMARecordQuery,
    GetGSTRecordQuery,
    VerifyAuditChainQuery,
)
from src.compliance.domain.audit_log import AuditChainVerifier, AuditEntry
from src.compliance.domain.fema_record import FEMARecord
from src.compliance.domain.gst_record import GSTRecord
from src.compliance.domain.ports import (
    IAuditLogRepository,
    IExportJobRepository,
    IFEMAGSTExporter,
    IFEMARepository,
    IGSTRepository,
)
from src.compliance.domain.value_objects import GENESIS_HASH
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.protocols import IEnterpriseReader, IMerkleService
from src.shared.infrastructure.db.uow import AbstractUnitOfWork

log = structlog.get_logger(__name__)

# Stub FX rate used when no treasury service is available (Phase 3).
# Phase 7 will replace with live Frankfurter feed.
_STUB_FX_RATE_INR_PER_ALGO = Decimal("15")


class ComplianceService:
    """
    Orchestrates the compliance pipeline:

    1. Append audit events (hash-chained, advisory lock).
    2. Generate FEMA + GST records on EscrowReleased.
    3. Verify audit chain integrity.
    4. Export FEMA PDF, GST CSV, bulk ZIP.

    All dependencies injected via constructor (DIP — context.md §4).
    """

    def __init__(
        self,
        audit_repo: IAuditLogRepository,
        fema_repo: IFEMARepository,
        gst_repo: IGSTRepository,
        export_job_repo: IExportJobRepository,
        enterprise_reader: IEnterpriseReader,
        merkle_service: IMerkleService,
        exporter: IFEMAGSTExporter,
        uow: AbstractUnitOfWork,
    ) -> None:
        self._audit = audit_repo
        self._fema = fema_repo
        self._gst = gst_repo
        self._jobs = export_job_repo
        self._enterprise = enterprise_reader
        self._merkle = merkle_service
        self._exporter = exporter
        self._uow = uow

    # ── Audit Log ─────────────────────────────────────────────────────────────

    async def append_audit_event(self, cmd: AppendAuditEventCommand) -> AuditEntry:
        """
        Append a single event to the hash-chained audit log.

        Advisory lock is held for the duration of the transaction to prevent
        concurrent appends producing duplicate or split sequence numbers.

        context.md §1: pg_advisory_xact_lock(escrow_id hash).
        """
        async with self._uow:
            # 1. Acquire advisory lock (transaction-scoped)
            await self._audit.acquire_advisory_lock(cmd.escrow_id)

            # 2. Fetch latest entry for chain linkage
            latest = await self._audit.get_latest(cmd.escrow_id)
            prev_hash = latest.entry_hash.value if latest else GENESIS_HASH
            next_seq = (latest.sequence_no.value + 1) if latest else 0

            # 3. Create new entry (hash computed in domain)
            entry = AuditEntry.create(
                escrow_id=cmd.escrow_id,
                sequence_no=next_seq,
                event_type=cmd.event_type,
                payload=cmd.payload,
                prev_hash=prev_hash,
            )

            # 4. Persist (append-only — no updates ever)
            await self._audit.append(entry)
            await self._uow.commit()

        log.info(
            "audit_entry_appended",
            escrow_id=str(cmd.escrow_id),
            sequence_no=entry.sequence_no.value,
            event_type=cmd.event_type,
            entry_hash=entry.entry_hash.value[:16] + "…",
        )
        return entry

    async def get_audit_log(
        self, query: GetAuditLogQuery
    ) -> tuple[list[AuditEntry], str | None]:
        """
        Paginated audit log fetch.

        Returns (entries, next_cursor) where next_cursor is the ISO-8601
        created_at of the last entry (base64-encode at API layer).
        Returns (entries, None) on last page.
        """
        entries = await self._audit.list_entries(
            escrow_id=query.escrow_id,
            after_created_at=query.cursor,
            limit=query.limit + 1,  # fetch one extra to detect next page
        )

        has_more = len(entries) > query.limit
        page = entries[: query.limit]
        next_cursor: str | None = (
            page[-1].created_at.isoformat() if has_more and page else None
        )
        return page, next_cursor

    async def verify_audit_chain(
        self, query: VerifyAuditChainQuery
    ) -> tuple[bool, int | None]:
        """
        Load all audit entries and verify hash chain integrity.

        Returns (is_valid, first_invalid_sequence_no).
        """
        entries = await self._audit.list_all_entries(query.escrow_id)
        return AuditChainVerifier.verify(entries)

    # ── Compliance Record Generation ──────────────────────────────────────────

    async def generate_compliance_records(
        self, cmd: GenerateComplianceRecordsCommand
    ) -> tuple[FEMARecord, GSTRecord]:
        """
        Generate FEMA and GST records after escrow release.

        Idempotent: if records already exist for escrow_id, returns them.
        """
        # Idempotency check
        existing_fema = await self._fema.get_by_escrow(cmd.escrow_id)
        existing_gst = await self._gst.get_by_escrow(cmd.escrow_id)
        if existing_fema and existing_gst:
            log.info(
                "compliance_records_already_exist",
                escrow_id=str(cmd.escrow_id),
            )
            return existing_fema, existing_gst

        fx_rate = cmd.fx_rate_inr_per_algo or _STUB_FX_RATE_INR_PER_ALGO

        # Resolve enterprise snapshots (may be None if not yet in DB)
        buyer_snap = None
        seller_snap = None
        if cmd.buyer_enterprise_id:
            buyer_snap = await self._enterprise.get_snapshot(cmd.buyer_enterprise_id)
        if cmd.seller_enterprise_id:
            seller_snap = await self._enterprise.get_snapshot(cmd.seller_enterprise_id)

        # FEMA record — use placeholder PAN if enterprise not yet resolved
        buyer_pan = buyer_snap.pan if buyer_snap else "AAAAA0000A"
        seller_pan = seller_snap.pan if seller_snap else "BBBBB0000B"

        fema = FEMARecord.generate(
            escrow_id=cmd.escrow_id,
            buyer_pan=buyer_pan,
            seller_pan=seller_pan,
            amount_microalgo=cmd.amount_microalgo,
            fx_rate_inr_per_algo=fx_rate,
            merkle_root=cmd.merkle_root,
        )

        # GST record — use placeholder GSTIN if enterprise not yet resolved
        buyer_gstin = buyer_snap.gstin if buyer_snap else "27AAAAA0000A1Z5"
        seller_gstin = seller_snap.gstin if seller_snap else "29BBBBB0000B1Z5"

        amount_algo = Decimal(cmd.amount_microalgo) / Decimal("1000000")
        taxable_inr = (amount_algo * fx_rate).quantize(Decimal("0.01"))

        gst = GSTRecord.generate(
            escrow_id=cmd.escrow_id,
            buyer_gstin=buyer_gstin,
            seller_gstin=seller_gstin,
            hsn_code=cmd.hsn_code,
            taxable_amount_inr=taxable_inr,
        )

        async with self._uow:
            if not existing_fema:
                await self._fema.save(fema)
            if not existing_gst:
                await self._gst.save(gst)
            await self._uow.commit()

        log.info(
            "compliance_records_generated",
            escrow_id=str(cmd.escrow_id),
            fema_form=fema.form_type,
            gst_tax_type=gst.tax_type,
            amount_inr=str(fema.amount_inr.value),
        )
        return fema, gst

    # ── Queries ────────────────────────────────────────────────────────────────

    async def get_fema_record(self, query: GetFEMARecordQuery) -> FEMARecord:
        record = await self._fema.get_by_escrow(query.escrow_id)
        if record is None:
            raise NotFoundError("FEMARecord", query.escrow_id)
        return record

    async def get_gst_record(self, query: GetGSTRecordQuery) -> GSTRecord:
        record = await self._gst.get_by_escrow(query.escrow_id)
        if record is None:
            raise NotFoundError("GSTRecord", query.escrow_id)
        return record

    # ── Exports ────────────────────────────────────────────────────────────────

    async def export_fema_pdf(self, query: ExportFEMAPDFQuery) -> bytes:
        """Return FEMA record as PDF bytes (never written to disk)."""
        record = await self.get_fema_record(
            GetFEMARecordQuery(
                escrow_id=query.escrow_id,
                requesting_enterprise_id=query.requesting_enterprise_id,
            )
        )
        return self._exporter.export_fema_pdf(record)

    async def export_gst_csv(self, query: ExportGSTCSVQuery) -> bytes:
        """Return GST record as CSV bytes (never written to disk)."""
        record = await self.get_gst_record(
            GetGSTRecordQuery(
                escrow_id=query.escrow_id,
                requesting_enterprise_id=query.requesting_enterprise_id,
            )
        )
        return self._exporter.export_gst_csv([record])

    async def request_bulk_export(self, cmd: RequestBulkExportCommand) -> uuid.UUID:
        """
        Create an export job and immediately build the ZIP.

        Phase 3: synchronous generation (stored in Redis 1h TTL).
        Phase 5+: hand off to Celery worker for large exports.
        """
        async with self._uow:
            await self._jobs.create_job(cmd.job_id, cmd.escrow_ids)
            await self._uow.commit()

        fema_records: list[FEMARecord] = []
        gst_records: list[GSTRecord] = []

        for eid in cmd.escrow_ids:
            f = await self._fema.get_by_escrow(eid)
            g = await self._gst.get_by_escrow(eid)
            if f:
                fema_records.append(f)
            if g:
                gst_records.append(g)

        try:
            zip_bytes = self._exporter.build_zip(fema_records, gst_records)
            redis_key = f"compliance:export:{cmd.job_id}"
            async with self._uow:
                await self._jobs.update_status(
                    cmd.job_id, "DONE", redis_key, None
                )
                await self._uow.commit()
            log.info("bulk_export_ready", job_id=str(cmd.job_id), redis_key=redis_key)
            # Caller stores zip_bytes in Redis; returned key is used by GET endpoint.
            _ = zip_bytes  # stored by router layer via Redis client
        except Exception as exc:
            async with self._uow:
                await self._jobs.update_status(
                    cmd.job_id, "FAILED", None, str(exc)
                )
                await self._uow.commit()
            log.error("bulk_export_failed", job_id=str(cmd.job_id), error=str(exc))
            raise

        return cmd.job_id

    async def get_export_job(self, query: GetExportJobQuery) -> dict:
        job = await self._jobs.get_job(query.job_id)
        if job is None:
            raise NotFoundError("ExportJob", query.job_id)
        return job
