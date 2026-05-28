"""
InsightEngine — computes NegotiationInsight aggregates from NegotiationRecords.

Triggered:
  - After each session completion (via Phase 6 event handler)
  - On historical document ingestion
  - On-demand via POST /v1/negotiation-insights/{enterprise_id}/recompute

context.md §3: application layer — orchestration only.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal

import structlog

from src.negotiation.domain.negotiation_insight import NegotiationInsight
from src.negotiation.domain.negotiation_record import NegotiationOutcome, NegotiationRecord

log = structlog.get_logger(__name__)


class InsightEngine:
    """Computes NegotiationInsight aggregates from all NegotiationRecords for an enterprise."""

    def __init__(
        self,
        record_repo,  # INegotiationRecordRepository
        insight_repo,  # INegotiationInsightRepository
    ) -> None:
        self._record_repo = record_repo
        self._insight_repo = insight_repo

    async def compute_enterprise_insights(
        self, enterprise_id: uuid.UUID
    ) -> NegotiationInsight:
        """
        Aggregate all NegotiationRecords for an enterprise into a NegotiationInsight.
        Upserts into negotiation_insights table.
        """
        # Fetch all records (no limit — aggregate pass)
        records = await self._record_repo.list_by_enterprise(
            enterprise_id=enterprise_id,
            filters={},
            limit=10000,
            offset=0,
        )

        insight = _compute_from_records(enterprise_id, records)

        await self._insight_repo.upsert(insight)

        log.info(
            "insights_computed",
            enterprise_id=str(enterprise_id),
            total_records=len(records),
            success_rate=str(insight.success_rate),
        )
        return insight


# ── Aggregate Computation ─────────────────────────────────────────────────────


def _compute_from_records(
    enterprise_id: uuid.UUID,
    records: list[NegotiationRecord],
) -> NegotiationInsight:
    """Pure function: compute NegotiationInsight from a list of records."""

    if not records:
        return NegotiationInsight(
            enterprise_id=enterprise_id,
            last_computed_at=datetime.now(tz=timezone.utc),
        )

    total = len(records)
    agreed = [r for r in records if r.outcome == NegotiationOutcome.AGREED]
    success_rate = Decimal(str(round(len(agreed) / total, 4)))

    # ── Average rounds ──
    rounds_values = [r.total_rounds for r in records if r.total_rounds is not None]
    avg_rounds = (
        Decimal(str(round(sum(rounds_values) / len(rounds_values), 2)))
        if rounds_values
        else Decimal("0")
    )

    # ── Average discount (from agreed records) ──
    discount_values = [
        float(r.final_discount_pct)
        for r in agreed
        if r.final_discount_pct is not None
    ]
    avg_discount = (
        Decimal(str(round(sum(discount_values) / len(discount_values), 4)))
        if discount_values
        else Decimal("0")
    )

    # ── Average deal quality ──
    quality_values = [
        float(r.deal_quality_score)
        for r in agreed
        if r.deal_quality_score is not None
    ]
    avg_quality = (
        Decimal(str(round(sum(quality_values) / len(quality_values), 4)))
        if quality_values
        else Decimal("0")
    )

    # ── Style distribution ──
    # Combine buyer_style and seller_style based on enterprise_role
    style_counts: Counter = Counter()
    for r in records:
        style = r.buyer_style if r.enterprise_role == "buyer" else r.seller_style
        if style:
            style_counts[style] += 1
    total_styled = sum(style_counts.values()) or 1
    style_distribution = {s: round(c / total_styled, 3) for s, c in style_counts.items()}
    dominant_style = style_counts.most_common(1)[0][0] if style_counts else "collaborative"

    # ── Top products ──
    product_groups: dict = defaultdict(list)
    for r in records:
        if r.product_name:
            product_groups[r.product_name].append(r)

    top_products = []
    for product, prod_records in sorted(
        product_groups.items(), key=lambda x: len(x[1]), reverse=True
    )[:10]:
        prod_agreed = [r for r in prod_records if r.outcome == NegotiationOutcome.AGREED]
        prices = [float(r.agreed_price_inr) for r in prod_agreed if r.agreed_price_inr]
        discounts = [float(r.final_discount_pct) for r in prod_agreed if r.final_discount_pct]
        top_products.append(
            {
                "product_name": product,
                "count": len(prod_records),
                "avg_price_inr": round(sum(prices) / len(prices), 2) if prices else None,
                "avg_discount_pct": round(sum(discounts) / len(discounts), 2) if discounts else None,
                "success_rate": round(len(prod_agreed) / len(prod_records), 3),
            }
        )

    # ── Top verticals ──
    vertical_groups: dict = defaultdict(list)
    for r in records:
        if r.industry_vertical:
            vertical_groups[r.industry_vertical].append(r)

    top_verticals = []
    for vertical, vert_records in sorted(
        vertical_groups.items(), key=lambda x: len(x[1]), reverse=True
    )[:5]:
        vert_agreed = [r for r in vert_records if r.outcome == NegotiationOutcome.AGREED]
        top_verticals.append(
            {
                "vertical": vertical,
                "count": len(vert_records),
                "success_rate": round(len(vert_agreed) / len(vert_records), 3),
            }
        )

    # ── Counterparty stats ──
    counterparty_groups: dict = defaultdict(list)
    for r in records:
        if r.counterparty_enterprise_id:
            counterparty_groups[str(r.counterparty_enterprise_id)].append(r)

    counterparty_stats = []
    for cp_id, cp_records in sorted(
        counterparty_groups.items(), key=lambda x: len(x[1]), reverse=True
    )[:20]:
        cp_agreed = [r for r in cp_records if r.outcome == NegotiationOutcome.AGREED]
        cp_prices = [float(r.agreed_price_inr) for r in cp_agreed if r.agreed_price_inr]
        relationship_score = round(len(cp_agreed) / len(cp_records), 3)
        counterparty_stats.append(
            {
                "enterprise_id": cp_id,
                "deals": len(cp_records),
                "successful_deals": len(cp_agreed),
                "avg_price_inr": round(sum(cp_prices) / len(cp_prices), 2) if cp_prices else None,
                "relationship_score": relationship_score,
                "success_rate": relationship_score,
            }
        )

    # ── Role determination ──
    roles = [r.enterprise_role for r in records]
    buyer_count = roles.count("buyer")
    seller_count = roles.count("seller")
    if buyer_count > 0 and seller_count > 0:
        role = "both"
    elif seller_count > buyer_count:
        role = "seller"
    else:
        role = "buyer"

    return NegotiationInsight(
        enterprise_id=enterprise_id,
        role=role,
        total_negotiations=total,
        success_rate=success_rate,
        avg_rounds_to_close=avg_rounds,
        avg_discount_achieved_pct=avg_discount,
        avg_deal_quality=avg_quality,
        dominant_style=dominant_style,
        style_distribution=style_distribution,
        top_products=top_products,
        top_verticals=top_verticals,
        counterparty_stats=counterparty_stats,
        strategy_recommendations=[],  # LLM-generated recommendations — future enhancement
        last_computed_at=datetime.now(tz=timezone.utc),
    )
