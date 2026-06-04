# context.md §3: FastAPI/Pydantic imports ONLY in api/ layer.
# Pydantic v2 DTOs — completely separate from domain entities.

from __future__ import annotations

import base64
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_serializer

from src.compliance.domain.audit_log import AuditEntry
from src.compliance.domain.fema_record import FEMARecord
from src.compliance.domain.gst_record import GSTRecord

# ── Audit Log Schemas ─────────────────────────────────────────────────────────


class AuditEntryResponse(BaseModel):
    entry_id: uuid.UUID
    escrow_id: uuid.UUID
    sequence_no: int
    event_type: str
    payload_json: str
    prev_hash: str
    entry_hash: str
    created_at: datetime

    @classmethod
    def from_domain(cls, entry: AuditEntry) -> "AuditEntryResponse":
        return cls(
            entry_id=entry.id,
            escrow_id=entry.escrow_id,
            sequence_no=entry.sequence_no.value,
            event_type=entry.event_type,
            payload_json=entry.payload_json,
            prev_hash=entry.prev_hash.value,
            entry_hash=entry.entry_hash.value,
            created_at=entry.created_at,
        )


class AuditLogPageResponse(BaseModel):
    entries: list[AuditEntryResponse]
    next_cursor: str | None  # base64-encoded ISO datetime; None on last page


class AuditChainVerifyResponse(BaseModel):
    valid: bool
    entry_count: int
    first_invalid_sequence_no: int | None


# ── FEMA Schemas ──────────────────────────────────────────────────────────────


class FEMARecordResponse(BaseModel):
    record_id: uuid.UUID
    escrow_id: uuid.UUID
    form_type: Literal["15CA", "15CB"]
    purpose_code: str
    buyer_pan: str
    seller_pan: str
    amount_inr: Decimal
    amount_algo: Decimal
    fx_rate_inr_per_algo: Decimal
    merkle_root: str
    generated_at: datetime

    @field_serializer('amount_inr', 'amount_algo', 'fx_rate_inr_per_algo')
    def serialize_decimal(self, value: Decimal) -> float:
        return float(value)

    @classmethod
    def from_domain(cls, record: FEMARecord) -> "FEMARecordResponse":
        return cls(
            record_id=record.id,
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
        )


# ── GST Schemas ───────────────────────────────────────────────────────────────


class GSTRecordResponse(BaseModel):
    record_id: uuid.UUID
    escrow_id: uuid.UUID
    hsn_code: str
    buyer_gstin: str
    seller_gstin: str
    tax_type: Literal["IGST", "CGST_SGST"]
    taxable_amount: Decimal
    igst_amount: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    total_tax: Decimal
    generated_at: datetime

    @field_serializer('taxable_amount', 'igst_amount', 'cgst_amount', 'sgst_amount', 'total_tax')
    def serialize_decimal(self, value: Decimal) -> float:
        return float(value)

    @classmethod
    def from_domain(cls, record: GSTRecord) -> "GSTRecordResponse":
        return cls(
            record_id=record.id,
            escrow_id=record.escrow_id,
            hsn_code=record.hsn_code.value,
            buyer_gstin=record.buyer_gstin.value,
            seller_gstin=record.seller_gstin.value,
            tax_type=record.tax_type,
            taxable_amount=record.taxable_amount.value,
            igst_amount=record.igst_amount.value,
            cgst_amount=record.cgst_amount.value,
            sgst_amount=record.sgst_amount.value,
            total_tax=record.total_tax,
            generated_at=record.generated_at,
        )


# ── Export Job Schemas ────────────────────────────────────────────────────────


class BulkExportRequest(BaseModel):
    escrow_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


class ExportJobResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    redis_key: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


# ── Cursor Helpers ────────────────────────────────────────────────────────────


def encode_cursor(dt: datetime) -> str:
    """Encode a datetime as a base64 cursor string."""
    return base64.urlsafe_b64encode(dt.isoformat().encode()).decode()


def decode_cursor(cursor: str) -> datetime:
    """Decode a base64 cursor string back to datetime."""
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    return datetime.fromisoformat(raw)
