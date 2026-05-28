"""
Canonical Negotiation Record — standardized schema for all negotiation memory.

Covers three record types:
  PLATFORM_SESSION   — completed negotiation sessions from this platform
  AGENT_CONVERSATION — LLM prompt/response pairs captured from NeutralEngine
  HISTORICAL_IMPORT  — pre-migration records extracted from uploaded documents

context.md §3: domain layer — zero framework imports. Pure Python only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from src.shared.domain.base_entity import BaseEntity


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# ── Enums ─────────────────────────────────────────────────────────────────────


class RecordType(str, Enum):
    PLATFORM_SESSION = "PLATFORM_SESSION"
    AGENT_CONVERSATION = "AGENT_CONVERSATION"
    HISTORICAL_IMPORT = "HISTORICAL_IMPORT"


class NegotiationOutcome(str, Enum):
    AGREED = "AGREED"
    REJECTED = "REJECTED"
    STALLED = "STALLED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


# Mapping from session status values → NegotiationOutcome
SESSION_STATUS_TO_OUTCOME: dict[str, NegotiationOutcome] = {
    "AGREED": NegotiationOutcome.AGREED,
    "WALK_AWAY": NegotiationOutcome.REJECTED,
    "FAILED": NegotiationOutcome.REJECTED,
    "STALLED": NegotiationOutcome.STALLED,
    "HUMAN_REVIEW": NegotiationOutcome.STALLED,
    "TIMEOUT": NegotiationOutcome.EXPIRED,
    "EXPIRED": NegotiationOutcome.EXPIRED,
    "POLICY_BREACH": NegotiationOutcome.REJECTED,
}


# ── Domain Entity ─────────────────────────────────────────────────────────────


@dataclass
class NegotiationRecord(BaseEntity):
    """
    Canonical schema for all negotiation memory — platform, agent, and historical.

    Single table with `record_type` discriminator enables uniform RAG queries
    ("find similar negotiations regardless of source") while allowing
    source-specific filtering.

    Retention policy (enforced by normalization service):
      AGREED + HISTORICAL_IMPORT → retention_expires_at = NULL (never auto-expires)
      REJECTED / STALLED / EXPIRED platform records → NOW() + 3 years
    """

    # ── Identity ──
    enterprise_id: uuid.UUID = field(default_factory=uuid.uuid4)
    record_type: RecordType = RecordType.PLATFORM_SESSION
    source_session_id: uuid.UUID | None = None

    # ── Counterparty ──
    counterparty_enterprise_id: uuid.UUID | None = None
    enterprise_role: str = "buyer"  # "buyer" | "seller"

    # ── Product Context ──
    product_name: str | None = None
    product_category: str | None = None
    hsn_code: str | None = None
    industry_vertical: str | None = None
    quantity: Decimal | None = None
    quantity_unit: str | None = None

    # ── Outcome ──
    outcome: NegotiationOutcome = NegotiationOutcome.UNKNOWN
    agreed_price_inr: Decimal | None = None
    initial_ask_price_inr: Decimal | None = None
    initial_bid_price_inr: Decimal | None = None
    final_discount_pct: Decimal | None = None

    # ── Behavioral Metrics ──
    total_rounds: int | None = None
    duration_hours: Decimal | None = None
    buyer_avg_concession_pct: Decimal | None = None
    seller_avg_concession_pct: Decimal | None = None
    buyer_style: str | None = None   # collaborative | assertive | analytical | competitive
    seller_style: str | None = None
    deal_quality_score: Decimal | None = None  # 0.0–1.0 (buyer's ZOPA position)

    # ── Terms ──
    agreed_terms: dict | None = None
    payment_terms: str | None = None
    delivery_window_days: int | None = None

    # ── Raw Data ──
    offer_sequence: list[dict] | None = None   # [{round, role, price, reasoning, confidence}]
    conversation_summary: str | None = None    # LLM-generated summary for RAG
    raw_source_text: str | None = None         # Original document text (historical only)

    # ── Metadata ──
    schema_version: int = 1
    confidence_score: Decimal | None = None    # Extraction completeness (0–1)
    source_filename: str | None = None         # Original filename (historical imports)
    normalized_at: datetime | None = None
    retention_expires_at: datetime | None = None  # NULL = never expires

    # ── Embedding ──
    embedding: list[float] | None = None       # 1536-dim for pgvector search
