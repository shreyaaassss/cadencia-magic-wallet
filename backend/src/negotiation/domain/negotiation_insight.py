"""
NegotiationInsight — per-enterprise aggregate intelligence.

Computed from all NegotiationRecord entries for an enterprise.
Stored in negotiation_insights table; recomputed after each session completion
and on historical document ingestion.

context.md §3: domain layer — zero framework imports. Pure Python only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from src.shared.domain.base_entity import BaseEntity


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass
class NegotiationInsight(BaseEntity):
    """
    Per-enterprise aggregate intelligence computed from all NegotiationRecords.

    Injected into LLM system prompts by PersonalizationBuilder to give the
    agent awareness of its enterprise's negotiation history and patterns.
    """

    enterprise_id: uuid.UUID = field(default_factory=uuid.uuid4)
    role: str = "both"  # "buyer" | "seller" | "both"

    # ── Aggregate Stats ──
    total_negotiations: int = 0
    success_rate: Decimal = Decimal("0")         # fraction 0–1
    avg_rounds_to_close: Decimal = Decimal("0")
    avg_discount_achieved_pct: Decimal = Decimal("0")
    avg_deal_quality: Decimal = Decimal("0")

    # ── Style Profile ──
    dominant_style: str = "collaborative"
    style_distribution: dict = field(default_factory=dict)  # {style: fraction}

    # ── Product Intelligence ──
    top_products: list[dict] = field(default_factory=list)
    # [{product_name, count, avg_price_inr, avg_discount_pct}]

    top_verticals: list[dict] = field(default_factory=list)
    # [{vertical, count, success_rate}]

    # ── Counterparty Intelligence ──
    counterparty_stats: list[dict] = field(default_factory=list)
    # [{enterprise_id, deals, avg_price_inr, relationship_score, success_rate}]

    # ── Temporal Patterns ──
    seasonal_patterns: dict | None = None        # {Q1: {avg_discount, deal_count}, ...}
    time_of_day_preference: dict | None = None

    # ── Recommendations ──
    strategy_recommendations: list[str] = field(default_factory=list)

    last_computed_at: datetime = field(default_factory=_utcnow)
    schema_version: int = 1
