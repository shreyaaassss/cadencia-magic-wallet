# SQL-based matching using commodity overlap, geography, and order value ranges.
# Implements IMatchmakingEngine as a keyword-based fallback when pgvector is unavailable.

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.identity.infrastructure.models import EnterpriseModel
from src.marketplace.infrastructure.models import CapabilityProfileModel
from src.shared.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from src.marketplace.domain.rfq import RFQ

log = get_logger(__name__)

# Weights for scoring
COMMODITY_WEIGHT = 0.5
GEOGRAPHY_WEIGHT = 0.3
VALUE_WEIGHT = 0.2

# ── Related-term graph ───────────────────────────────────────────────────────
# Maps a search term to related commodity keywords with a relevance factor.
# An exact keyword hit gets 1.0; a related-term hit gets the factor below.
_RELATED_TERMS: dict[str, dict[str, float]] = {
    "metal": {"steel": 0.6, "iron": 0.6, "aluminium": 0.5, "aluminum": 0.5, "copper": 0.5, "zinc": 0.4, "tin": 0.4},
    "steel": {"metal": 0.5, "iron": 0.5, "hr coil": 0.9, "cr coil": 0.9, "tmt": 0.8, "rebar": 0.8, "galvanized": 0.7, "stainless": 0.7},
    "iron": {"metal": 0.5, "steel": 0.6, "pig iron": 0.9, "sponge iron": 0.9, "iron ore": 0.9},
    "aluminium": {"aluminum": 1.0, "metal": 0.5, "aluminium ingot": 0.9, "aluminium sheet": 0.9},
    "aluminum": {"aluminium": 1.0, "metal": 0.5},
    "copper": {"metal": 0.5, "copper cathode": 0.9, "copper wire": 0.9, "copper rod": 0.9},
    "plastic": {"polymer": 0.8, "polyethylene": 0.7, "polypropylene": 0.7, "pvc": 0.7, "hdpe": 0.7},
    "polymer": {"plastic": 0.8, "polyethylene": 0.7, "polypropylene": 0.7},
    "textile": {"fabric": 0.9, "yarn": 0.8, "cotton": 0.6, "polyester": 0.6},
    "fabric": {"textile": 0.9, "yarn": 0.7, "cotton": 0.6},
    "oil": {"crude oil": 0.9, "palm oil": 0.8, "edible oil": 0.8, "sunflower oil": 0.8},
    "chemical": {"chemicals": 1.0, "caustic soda": 0.7, "soda ash": 0.7},
    "chemicals": {"chemical": 1.0, "caustic soda": 0.7, "soda ash": 0.7},
}


class KeywordMatchmaker:
    """SQL-based matching using commodity overlap, geography, and order value ranges."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_matches(
        self,
        rfq: "RFQ",
        rfq_embedding: list[float],
        top_n: int = 10,
    ) -> list[tuple[uuid.UUID, float]]:
        """Find seller matches using keyword-based scoring against CapabilityProfiles."""
        parsed = rfq.parsed_fields or {}
        rfq_product = (parsed.get("product") or "").lower()
        rfq_geography = (parsed.get("geography") or "").lower()
        rfq_budget_min = parsed.get("budget_min")
        rfq_budget_max = parsed.get("budget_max")

        if not rfq_product:
            log.info("keyword_match_skipped_no_product", rfq_id=str(rfq.id))
            return []

        # Query capability profiles joined with enterprises to filter by trade role
        stmt = select(
            CapabilityProfileModel.enterprise_id,
            CapabilityProfileModel.commodities,
            CapabilityProfileModel.geographies_served,
            CapabilityProfileModel.min_order_value,
            CapabilityProfileModel.max_order_value,
        ).join(
            EnterpriseModel,
            EnterpriseModel.id == CapabilityProfileModel.enterprise_id,
        ).where(
            and_(
                CapabilityProfileModel.enterprise_id != rfq.buyer_enterprise_id,
                or_(
                    EnterpriseModel.trade_role == "SELLER",
                    EnterpriseModel.trade_role == "BOTH",
                ),
            )
        )

        result = await self._session.execute(stmt)
        rows = result.all()

        scored: list[tuple[uuid.UUID, float]] = []

        for row in rows:
            # 1. Commodity relevance (weight: 0.5) — granular, not binary
            commodities = row.commodities or []
            commodity_lower = [c.lower() for c in commodities]
            commodity_text = " ".join(commodity_lower)
            product_words = [w for w in rfq_product.split() if len(w) > 2]

            commodity_score = self._score_commodity(
                rfq_product, product_words, commodity_lower, commodity_text,
            )

            # 2. Geography match (weight: 0.3) — granular
            geographies = row.geographies_served or []
            geo_lower = [g.lower() for g in geographies]
            geo_score = 0.0
            if rfq_geography and geo_lower:
                for g in geo_lower:
                    if rfq_geography == g:
                        geo_score = 1.0  # exact
                        break
                    if rfq_geography in g or g in rfq_geography:
                        geo_score = max(geo_score, 0.5)  # partial

            # 3. Order value range overlap (weight: 0.2) — granular
            value_score = 0.0
            if rfq_budget_min is not None or rfq_budget_max is not None:
                ent_min = float(row.min_order_value) if row.min_order_value else 0
                ent_max = float(row.max_order_value) if row.max_order_value else float("inf")
                b_min = float(rfq_budget_min) if rfq_budget_min else 0
                b_max = float(rfq_budget_max) if rfq_budget_max else float("inf")

                # Check overlap
                if b_min <= ent_max and b_max >= ent_min:
                    # Compute how well the budget fits within the seller's range
                    overlap_low = max(b_min, ent_min)
                    overlap_high = min(b_max, ent_max)
                    if overlap_high > overlap_low:
                        buyer_range = max(b_max - b_min, 1)
                        value_score = min(1.0, (overlap_high - overlap_low) / buyer_range)
                    else:
                        value_score = 0.5  # edges overlap

            # Composite
            score = (
                COMMODITY_WEIGHT * commodity_score
                + GEOGRAPHY_WEIGHT * geo_score
                + VALUE_WEIGHT * value_score
            )

            # Hard filter: require meaningful commodity relevance.
            # A seller with zero commodity match is irrelevant regardless
            # of geography or value overlap.
            if commodity_score <= 0:
                continue

            # Minimum composite threshold — skip noise matches
            if score < 0.15:
                continue

            scored.append((row.enterprise_id, round(min(score, 1.0), 3)))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)

        matches = scored[:top_n]

        log.info(
            "keyword_match_complete",
            rfq_id=str(rfq.id),
            match_count=len(matches),
            top_score=matches[0][1] if matches else 0.0,
        )

        return matches

    @staticmethod
    def _score_commodity(
        rfq_product: str,
        product_words: list[str],
        seller_commodities: list[str],
        seller_text: str,
    ) -> float:
        """
        Score commodity relevance on a 0.0-1.0 scale.

        Hierarchy:
          1.0  — exact match (rfq product IS a seller commodity)
          0.8  — rfq product substring of a seller commodity
          0.6  — related-term match (e.g. 'metal' → 'steel')
          0.3  — partial word overlap
          0.0  — no match
        """
        # Exact match: rfq product string is one of the seller's commodities
        if rfq_product in seller_commodities:
            return 1.0

        # Substring: rfq product appears inside a commodity or vice versa
        for sc in seller_commodities:
            if rfq_product in sc or sc in rfq_product:
                return 0.8

        # Related-term: check if any rfq word has a related-term mapping to seller commodities
        best_related = 0.0
        for word in product_words:
            related = _RELATED_TERMS.get(word, {})
            for sc in seller_commodities:
                # Check if seller commodity (or any word in it) is a related term
                if sc in related:
                    best_related = max(best_related, related[sc])
                for sc_word in sc.split():
                    if sc_word in related:
                        best_related = max(best_related, related[sc_word] * 0.9)

        if best_related > 0:
            return min(best_related, 0.7)  # cap related-term score at 0.7

        # Partial word overlap: any product word appears in seller commodity text
        overlap_count = sum(1 for w in product_words if w in seller_text)
        if overlap_count > 0:
            return min(0.3 + 0.1 * overlap_count, 0.5)

        return 0.0

