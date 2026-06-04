# context.md §3: Concrete repository implementations live ONLY in infrastructure/.
# context.md §5: async SQLAlchemy 2.0 with asyncpg.
# Advisory lock via pg_advisory_xact_lock prevents concurrent audit appends.

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.compliance.domain.audit_log import AuditEntry
from src.compliance.domain.fema_record import FEMARecord
from src.compliance.domain.gst_record import GSTRecord
from src.compliance.domain.value_objects import (
    GSTIN,
    HashValue,
    HSNCode,
    INRAmount,
    PANNumber,
    PurposeCode,
    SequenceNumber,
)
from src.compliance.infrastructure.models import (
    AuditEntryModel,
    ExportJobModel,
    FEMARecordModel,
    GSTRecordModel,
)

# ── AuditLogRepository ────────────────────────────────────────────────────────


class PostgresAuditLogRepository:
    """
    Append-only audit log repository backed by PostgreSQL.

    Advisory lock (pg_advisory_xact_lock) is used to prevent concurrent
    appends producing duplicate sequence numbers for the same escrow.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def acquire_advisory_lock(self, escrow_id: uuid.UUID) -> None:
        """
        Acquire a transaction-scoped PostgreSQL advisory lock keyed to escrow_id.

        The lock key is the first 8 bytes of the escrow UUID interpreted as
        a signed 64-bit integer (big-endian).
        """
        lock_key = int.from_bytes(escrow_id.bytes[:8], byteorder="big", signed=True)
        await self._session.execute(
            sa.text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key}
        )

    async def append(self, entry: AuditEntry) -> None:
        model = AuditEntryModel(
            id=entry.id,
            escrow_id=entry.escrow_id,
            sequence_no=entry.sequence_no.value,
            event_type=entry.event_type,
            payload_json=entry.payload_json,
            prev_hash=entry.prev_hash.value,
            entry_hash=entry.entry_hash.value,
            created_at=entry.created_at,
        )
        self._session.add(model)

    async def get_latest(self, escrow_id: uuid.UUID) -> AuditEntry | None:
        result = await self._session.execute(
            sa.select(AuditEntryModel)
            .where(AuditEntryModel.escrow_id == escrow_id)
            .order_by(AuditEntryModel.sequence_no.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return _model_to_audit_entry(row) if row else None

    async def list_entries(
        self,
        escrow_id: uuid.UUID,
        after_created_at: datetime | None,
        limit: int,
    ) -> list[AuditEntry]:
        q = (
            sa.select(AuditEntryModel)
            .where(AuditEntryModel.escrow_id == escrow_id)
            .order_by(AuditEntryModel.sequence_no.asc())
            .limit(limit)
        )
        if after_created_at is not None:
            q = q.where(AuditEntryModel.created_at > after_created_at)
        result = await self._session.execute(q)
        return [_model_to_audit_entry(r) for r in result.scalars().all()]

    async def list_all_entries(self, escrow_id: uuid.UUID) -> list[AuditEntry]:
        result = await self._session.execute(
            sa.select(AuditEntryModel)
            .where(AuditEntryModel.escrow_id == escrow_id)
            .order_by(AuditEntryModel.sequence_no.asc())
        )
        return [_model_to_audit_entry(r) for r in result.scalars().all()]


# ── FEMARepository ────────────────────────────────────────────────────────────


class PostgresFEMARepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, record: FEMARecord) -> None:
        model = FEMARecordModel(
            id=record.id,
            escrow_id=record.escrow_id,
            form_type=record.form_type,
            purpose_code=record.purpose_code.value,
            buyer_pan=record.buyer_pan.value,
            seller_pan=record.seller_pan.value,
            amount_inr=record.amount_inr.value,
            amount_algo=record.amount_algo,
            fx_rate_inr_per_algo=record.fx_rate_inr_per_algo,
            merkle_root=record.merkle_root,
            generated_at=record.generated_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        self._session.add(model)

    async def get_by_escrow(self, escrow_id: uuid.UUID) -> FEMARecord | None:
        result = await self._session.execute(
            sa.select(FEMARecordModel).where(FEMARecordModel.escrow_id == escrow_id)
        )
        row = result.scalar_one_or_none()
        return _model_to_fema_record(row) if row else None


# ── GSTRepository ─────────────────────────────────────────────────────────────


class PostgresGSTRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, record: GSTRecord) -> None:
        model = GSTRecordModel(
            id=record.id,
            escrow_id=record.escrow_id,
            hsn_code=record.hsn_code.value,
            buyer_gstin=record.buyer_gstin.value,
            seller_gstin=record.seller_gstin.value,
            tax_type=record.tax_type,
            taxable_amount=record.taxable_amount.value,
            igst_amount=record.igst_amount.value,
            cgst_amount=record.cgst_amount.value,
            sgst_amount=record.sgst_amount.value,
            generated_at=record.generated_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        self._session.add(model)

    async def get_by_escrow(self, escrow_id: uuid.UUID) -> GSTRecord | None:
        result = await self._session.execute(
            sa.select(GSTRecordModel).where(GSTRecordModel.escrow_id == escrow_id)
        )
        row = result.scalar_one_or_none()
        return _model_to_gst_record(row) if row else None


# ── ExportJobRepository ───────────────────────────────────────────────────────


class PostgresExportJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_job(self, job_id: uuid.UUID, escrow_ids: list[uuid.UUID]) -> None:
        model = ExportJobModel(
            id=job_id,
            escrow_ids={"ids": [str(e) for e in escrow_ids]},
            status="PENDING",
        )
        self._session.add(model)

    async def update_status(
        self,
        job_id: uuid.UUID,
        status: str,
        redis_key: str | None,
        error: str | None,
    ) -> None:
        from datetime import timezone
        now = datetime.now(tz=timezone.utc)
        await self._session.execute(
            sa.update(ExportJobModel)
            .where(ExportJobModel.id == job_id)
            .values(
                status=status,
                redis_key=redis_key,
                error_message=error,
                completed_at=now if status in ("DONE", "FAILED") else None,
            )
        )

    async def get_job(self, job_id: uuid.UUID) -> dict | None:
        result = await self._session.execute(
            sa.select(ExportJobModel).where(ExportJobModel.id == job_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return {
            "job_id": str(row.id),
            "status": row.status,
            "redis_key": row.redis_key,
            "error_message": row.error_message,
            "created_at": row.created_at,
            "completed_at": row.completed_at,
            "escrow_ids": row.escrow_ids.get("ids", []),
        }


# ── Model → Domain Mappers ────────────────────────────────────────────────────


def _model_to_audit_entry(m: AuditEntryModel) -> AuditEntry:
    return AuditEntry(
        id=m.id,
        created_at=m.created_at,
        updated_at=m.created_at,  # audit entries never updated
        escrow_id=m.escrow_id,
        sequence_no=SequenceNumber(value=m.sequence_no),
        event_type=m.event_type,
        payload_json=m.payload_json,
        prev_hash=HashValue(value=m.prev_hash),
        entry_hash=HashValue(value=m.entry_hash),
    )


def _model_to_fema_record(m: FEMARecordModel) -> FEMARecord:
    return FEMARecord(
        id=m.id,
        created_at=m.created_at,
        updated_at=m.updated_at,
        escrow_id=m.escrow_id,
        form_type=m.form_type,  # type: ignore[arg-type]
        purpose_code=PurposeCode(value=m.purpose_code),
        buyer_pan=PANNumber(value=m.buyer_pan),
        seller_pan=PANNumber(value=m.seller_pan),
        amount_inr=INRAmount(value=Decimal(str(m.amount_inr))),
        amount_algo=Decimal(str(m.amount_algo)),
        fx_rate_inr_per_algo=Decimal(str(m.fx_rate_inr_per_algo)),
        merkle_root=m.merkle_root,
        generated_at=m.generated_at,
    )


def _model_to_gst_record(m: GSTRecordModel) -> GSTRecord:
    return GSTRecord(
        id=m.id,
        created_at=m.created_at,
        updated_at=m.updated_at,
        escrow_id=m.escrow_id,
        hsn_code=HSNCode(value=m.hsn_code),
        buyer_gstin=GSTIN(value=m.buyer_gstin),
        seller_gstin=GSTIN(value=m.seller_gstin),
        tax_type=m.tax_type,  # type: ignore[arg-type]
        taxable_amount=INRAmount(value=Decimal(str(m.taxable_amount))),
        igst_amount=INRAmount(value=Decimal(str(m.igst_amount))),
        cgst_amount=INRAmount(value=Decimal(str(m.cgst_amount))),
        sgst_amount=INRAmount(value=Decimal(str(m.sgst_amount))),
        generated_at=m.generated_at,
    )
