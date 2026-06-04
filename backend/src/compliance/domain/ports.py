# context.md §3 — Hexagonal Architecture: Protocol interfaces ONLY here.
# No concrete classes. No algosdk, sqlalchemy, fastapi imports.
# Repositories and exporters live ONLY in infrastructure/.

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol, runtime_checkable

from src.compliance.domain.audit_log import AuditEntry
from src.compliance.domain.fema_record import FEMARecord
from src.compliance.domain.gst_record import GSTRecord

# ── Repository Ports ──────────────────────────────────────────────────────────


@runtime_checkable
class IAuditLogRepository(Protocol):
    """
    Append-only audit log repository.

    Advisory lock for concurrent appends is enforced by the infrastructure
    implementation (PostgreSQL pg_advisory_xact_lock per escrow_id).
    """

    async def append(self, entry: AuditEntry) -> None:
        """Persist a new audit entry. Must hold advisory lock before calling."""
        ...

    async def get_latest(self, escrow_id: uuid.UUID) -> AuditEntry | None:
        """Return the entry with the highest sequence_no for this escrow."""
        ...

    async def list_entries(
        self,
        escrow_id: uuid.UUID,
        after_created_at: datetime | None,
        limit: int,
    ) -> list[AuditEntry]:
        """
        Cursor-based paginated fetch.

        Returns up to `limit` entries with created_at > after_created_at,
        ordered by (sequence_no ASC). Pass None for after_created_at to
        fetch from the beginning.
        """
        ...

    async def list_all_entries(self, escrow_id: uuid.UUID) -> list[AuditEntry]:
        """Load ALL entries for hash chain verification. Use with care on large chains."""
        ...

    async def acquire_advisory_lock(self, escrow_id: uuid.UUID) -> None:
        """
        Acquire PostgreSQL transaction-scoped advisory lock for escrow_id.

        MUST be called inside an open transaction. Lock is released on commit/rollback.
        Prevents concurrent audit appends for the same escrow.
        """
        ...


@runtime_checkable
class IFEMARepository(Protocol):
    async def save(self, record: FEMARecord) -> None: ...
    async def get_by_escrow(self, escrow_id: uuid.UUID) -> FEMARecord | None: ...


@runtime_checkable
class IGSTRepository(Protocol):
    async def save(self, record: GSTRecord) -> None: ...
    async def get_by_escrow(self, escrow_id: uuid.UUID) -> GSTRecord | None: ...


# ── Export Job Port ───────────────────────────────────────────────────────────


@runtime_checkable
class IExportJobRepository(Protocol):
    """Tracks async bulk ZIP export jobs. Status stored in DB; payload in Redis."""

    async def create_job(self, job_id: uuid.UUID, escrow_ids: list[uuid.UUID]) -> None: ...
    async def update_status(
        self,
        job_id: uuid.UUID,
        status: str,
        redis_key: str | None,
        error: str | None,
    ) -> None: ...
    async def get_job(self, job_id: uuid.UUID) -> dict | None: ...


# ── Exporter Port ─────────────────────────────────────────────────────────────


@runtime_checkable
class IFEMAGSTExporter(Protocol):
    """Generates PDF (FEMA) and CSV (GST) export bytes. Never writes to disk."""

    def export_fema_pdf(self, record: FEMARecord) -> bytes: ...
    def export_gst_csv(self, records: list[GSTRecord]) -> bytes: ...
    def build_zip(
        self, fema_records: list[FEMARecord], gst_records: list[GSTRecord]
    ) -> bytes: ...
