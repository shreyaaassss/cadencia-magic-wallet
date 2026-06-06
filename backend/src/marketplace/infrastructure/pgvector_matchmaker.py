# context.md §3.1: pgvector cosine similarity using ivfflat index.
# Enhanced with hard filters (delivery, capacity, MOQ) and composite scoring.

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.marketplace.infrastructure.delivery_feasibility import DeliveryFeasibilityService
from src.marketplace.infrastructure.models import (
    AddressModel,
    CapabilityProfileModel,
    CatalogueItemModel,
    SellerCapacityProfileModel,
)
from src.shared.infrastructure.logging import get_logger
from src.shared.infrastructure.metrics import VECTOR_SEARCH_DURATION

if TYPE_CHECKING:
    from src.marketplace.domain.rfq import RFQ

log = get_logger(__name__)

# Default composite scoring weights (used when no industry-specific weights available)
_DEFAULT_WEIGHTS = {
    "semantic": 0.25,
    "delivery": 0.20,
    "capacity": 0.15,
    "price": 0.15,
    "proximity": 0.10,
    "payment": 0.10,
    "certification": 0.05,
}

# Module-level alias for backward compatibility
_WEIGHTS = _DEFAULT_WEIGHTS


async def _load_industry_weights(session: object, industry_vertical: str | None) -> dict:
    """Load per-industry matching weights from industry_taxonomies table.

    Falls back to _DEFAULT_WEIGHTS if no industry-specific weights found.
    """
    if not industry_vertical:
        return _DEFAULT_WEIGHTS
    try:
        from sqlalchemy import select as _sa_select

        from src.marketplace.infrastructure.models import IndustryTaxonomyModel
        result = await session.execute(
            _sa_select(IndustryTaxonomyModel.matching_weights).where(
                IndustryTaxonomyModel.display_name.ilike(f"%{industry_vertical}%")
            )
        )
        row = result.scalar_one_or_none()
        if row and isinstance(row, dict):
            return row
    except Exception:
        pass
    return _DEFAULT_WEIGHTS


class PgvectorMatchmaker:
    """Cosine similarity search via pgvector ivfflat. Implements IMatchmakingEngine."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _select_best_catalogue_item(
        catalogue_items: list,
        rfq_product: str,
        rfq_hsn: str | None,
    ):
        """Pick catalogue row that best matches RFQ product name or HSN."""
        if not catalogue_items:
            return None
        rfq_product_lower = (rfq_product or "").lower().strip()
        hsn = (str(rfq_hsn).strip() if rfq_hsn else "") or ""
        if hsn:
            for item in catalogue_items:
                item_hsn = getattr(item, "hsn_code", None)
                if item_hsn and str(item_hsn).strip() == hsn:
                    return item
        if rfq_product_lower:
            for item in catalogue_items:
                name = (getattr(item, "product_name", None) or "").lower()
                if rfq_product_lower in name or name in rfq_product_lower:
                    return item
        return catalogue_items[0]

    async def find_matches(
        self,
        rfq: "RFQ",
        rfq_embedding: list[float],
        top_n: int = 10,
    ) -> list[tuple[uuid.UUID, float]]:
        # Set ivfflat probes for accuracy
        search_start = time.monotonic()
        await self._session.execute(text("SET ivfflat.probes = 50"))

        # Cosine similarity = 1 - cosine_distance
        # <=> operator is cosine distance in pgvector
        stmt = (
            select(
                CapabilityProfileModel.enterprise_id,
                (
                    1 - CapabilityProfileModel.embedding.cosine_distance(rfq_embedding)
                ).label("similarity"),
            )
            .where(CapabilityProfileModel.embedding.is_not(None))
            .where(CapabilityProfileModel.enterprise_id != rfq.buyer_enterprise_id)
            .order_by(
                CapabilityProfileModel.embedding.cosine_distance(rfq_embedding).asc()
            )
            .limit(top_n)
        )

        result = await self._session.execute(stmt)
        rows = result.all()

        # Prometheus: record vector search latency
        VECTOR_SEARCH_DURATION.observe(time.monotonic() - search_start)

        # Filter out very low similarity scores — these are noise matches
        # where the embeddings have near-zero relevance (e.g. textile vs metal).
        MIN_SEMANTIC_SCORE = 0.30
        matches = [
            (row.enterprise_id, max(0.0, min(1.0, float(row.similarity))))
            for row in rows
            if float(row.similarity) >= MIN_SEMANTIC_SCORE
        ]
        log.info(
            "pgvector_match_complete",
            rfq_id=str(rfq.id),
            match_count=len(matches),
            top_score=matches[0][1] if matches else 0.0,
        )
        return matches

    async def find_enhanced_matches(
        self,
        rfq: "RFQ",
        rfq_embedding: list[float],
        buyer_pincode: str | None = None,
        buyer_delivery_window: int | None = None,
        buyer_qty: float | None = None,
        buyer_budget_min: float | None = None,
        buyer_budget_max: float | None = None,
        buyer_payment_terms: list[str] | None = None,
        buyer_requires_tc: bool = False,
        product_category: str | None = None,
        top_n: int = 10,
    ) -> list[dict]:
        """
        Enhanced matching with hard filters and 7-factor composite scoring.

        Returns list of dicts with scoring breakdown per seller.
        """
        # Step 1: Get initial semantic matches (wider net)
        raw_matches = await self.find_matches(rfq, rfq_embedding, top_n=top_n * 3)
        if not raw_matches:
            return []

        feasibility_svc = DeliveryFeasibilityService()
        scored_matches = []

        # Pre-fetch commodity/industry data for hard filtering
        rfq_parsed = rfq.parsed_fields or {}
        rfq_product = (rfq_parsed.get("product") or rfq_parsed.get("product_name") or "").lower()
        rfq_product_words = [w for w in rfq_product.split() if len(w) > 2]

        # ── N+1 FIX: Batch-prefetch all seller data before the scoring loop ──
        # Instead of 6 individual queries per seller, fetch all data in 5 batch queries.
        seller_ids = [sid for sid, _ in raw_matches]

        _cap_result = await self._session.execute(
            select(CapabilityProfileModel).where(CapabilityProfileModel.enterprise_id.in_(seller_ids))
        )
        _prefetched_caps = {row.enterprise_id: row for row in _cap_result.scalars().all()}

        _addr_result = await self._session.execute(
            select(AddressModel).where(
                AddressModel.enterprise_id.in_(seller_ids),
                AddressModel.is_primary == True,  # noqa: E712
            )
        )
        _prefetched_addrs = {row.enterprise_id: row for row in _addr_result.scalars().all()}

        _scap_result = await self._session.execute(
            select(SellerCapacityProfileModel).where(SellerCapacityProfileModel.enterprise_id.in_(seller_ids))
        )
        _prefetched_scaps = {row.enterprise_id: row for row in _scap_result.scalars().all()}

        _cat_result = await self._session.execute(
            select(CatalogueItemModel).where(
                CatalogueItemModel.enterprise_id.in_(seller_ids),
                CatalogueItemModel.is_active == True,  # noqa: E712
            )
        )
        _all_cat_items = _cat_result.scalars().all()
        _prefetched_catalogues: dict = {}
        for _ci in _all_cat_items:
            _prefetched_catalogues.setdefault(_ci.enterprise_id, []).append(_ci)

        from src.identity.infrastructure.models import EnterpriseModel
        _ent_result = await self._session.execute(
            select(EnterpriseModel).where(EnterpriseModel.id.in_(seller_ids))
        )
        _prefetched_enterprises = {row.id: row for row in _ent_result.scalars().all()}

        for seller_id, semantic_score in raw_matches:
            # ── Industry/commodity relevance hard filter ─────────────
            # Reject sellers whose commodities have zero overlap with RFQ product.
            # (Uses batch-prefetched data instead of per-seller query)
            if rfq_product:
                seller_cap_profile = _prefetched_caps.get(seller_id)

                if seller_cap_profile:
                    seller_commodities = [c.lower() for c in (seller_cap_profile.commodities or [])]
                    seller_industry = (seller_cap_profile.industry_vertical or "").lower()
                    seller_text = " ".join(seller_commodities) + " " + seller_industry

                    # Check for ANY relevance between RFQ product and seller commodities/industry
                    has_relevance = False
                    # Exact or substring match
                    if rfq_product in seller_text or any(c in rfq_product for c in seller_commodities):
                        has_relevance = True
                    # Word-level overlap
                    if not has_relevance:
                        for word in rfq_product_words:
                            if word in seller_text:
                                has_relevance = True
                                break
                    # Related-term check (metal↔steel, textile↔fabric, etc.)
                    if not has_relevance:
                        from src.marketplace.infrastructure.keyword_matchmaker import _RELATED_TERMS
                        for word in rfq_product_words:
                            related = _RELATED_TERMS.get(word, {})
                            for sc in seller_commodities:
                                if sc in related or any(sw in related for sw in sc.split()):
                                    has_relevance = True
                                    break
                            if has_relevance:
                                break

                    if not has_relevance:
                        log.debug(
                            "pgvector_hard_filter_no_relevance",
                            seller_id=str(seller_id),
                            rfq_product=rfq_product,
                            seller_commodities=seller_commodities,
                        )
                        continue

            # Use batch-prefetched data (N+1 fix)
            seller_addr = _prefetched_addrs.get(seller_id)
            seller_cap = _prefetched_scaps.get(seller_id)

            # Filter catalogue items by category if specified
            all_seller_items = _prefetched_catalogues.get(seller_id, [])
            if product_category:
                catalogue_items = [
                    ci for ci in all_seller_items
                    if (ci.product_category or "").upper() == product_category.upper()
                ]
            else:
                catalogue_items = all_seller_items

            # ── Hard Filters ─────────────────────────────────────────────
            # Skip sellers without catalogue items for the requested product
            if product_category and not catalogue_items:
                continue

            rfq_hsn = rfq_parsed.get("hsn_code")
            best_item = self._select_best_catalogue_item(
                catalogue_items, rfq_product, rfq_hsn
            )
            lead_time = best_item.lead_time_days if best_item else 14

            # Delivery feasibility check
            delivery_score = 1.0
            estimated_days = None
            distance_km = None

            if buyer_pincode and seller_addr and seller_addr.pincode and buyer_delivery_window:
                feasibility = await feasibility_svc.check_feasibility(
                    seller_pincode=seller_addr.pincode,
                    buyer_pincode=buyer_pincode,
                    lead_time_days=lead_time,
                    delivery_window_days=buyer_delivery_window,
                    session=self._session,
                )
                if not feasibility.is_feasible:
                    continue  # Hard filter: skip infeasible sellers
                estimated_days = feasibility.total_days
                distance_km = feasibility.distance_km
                # Score: more buffer = higher score
                delivery_score = max(0.0, 1.0 - (feasibility.total_days / buyer_delivery_window))

                # Check delivery radius
                if seller_cap and seller_cap.max_delivery_radius_km:
                    if feasibility.distance_km > seller_cap.max_delivery_radius_km:
                        continue

            # Capacity check (MT/month sellers only — skip for piece/unit RFQs)
            capacity_score = 1.0
            item_unit = (getattr(best_item, "unit", None) or "MT").upper() if best_item else "MT"
            apply_mt_capacity = item_unit in ("MT", "TON", "TONNE", "METRIC TON")
            if (
                apply_mt_capacity
                and buyer_qty
                and seller_cap
                and seller_cap.available_capacity_mt
            ):
                available = float(seller_cap.available_capacity_mt)
                window = buyer_delivery_window or 30
                months = max(window / 30, 1)
                total_producible = available * months
                if buyer_qty > total_producible:
                    continue  # Hard filter: can't produce enough
                capacity_score = min(1.0, total_producible / buyer_qty)

            # MOQ check
            if buyer_qty and best_item:
                if buyer_qty < float(best_item.moq):
                    continue  # Hard filter: below MOQ
                if buyer_qty > float(best_item.max_order_qty):
                    continue  # Hard filter: above max

            # ── Soft Scoring ─────────────────────────────────────────────
            # Price competitiveness
            price_score = 0.5  # neutral default
            if buyer_budget_min and buyer_budget_max and best_item:
                budget_mid = (buyer_budget_min + buyer_budget_max) / 2
                seller_price = float(best_item.price_per_unit_inr)
                if budget_mid > 0:
                    price_score = max(0.0, 1.0 - abs(seller_price - budget_mid) / budget_mid)

            # Proximity
            proximity_score = 0.5
            if distance_km is not None:
                proximity_score = max(0.0, 1.0 - min(distance_km / 2500, 1.0))

            # Payment terms compatibility
            # Use batch-prefetched enterprise data (N+1 fix)
            seller_ent = _prefetched_enterprises.get(seller_id)

            payment_score = 0.5
            if buyer_payment_terms and seller_ent and seller_ent.payment_terms_accepted:
                overlap = set(buyer_payment_terms) & set(seller_ent.payment_terms_accepted)
                payment_score = len(overlap) / len(buyer_payment_terms) if buyer_payment_terms else 0.5

            # Certification match
            cert_score = 1.0
            if buyer_requires_tc:
                # Check test_certificate_available on enterprise
                cert_score = 0.5

            # Composite score
            composite = (
                _WEIGHTS["semantic"] * semantic_score
                + _WEIGHTS["delivery"] * delivery_score
                + _WEIGHTS["capacity"] * capacity_score
                + _WEIGHTS["price"] * price_score
                + _WEIGHTS["proximity"] * proximity_score
                + _WEIGHTS["payment"] * payment_score
                + _WEIGHTS["certification"] * cert_score
            )

            scored_matches.append({
                "enterprise_id": seller_id,
                "semantic_score": round(semantic_score, 4),
                "delivery_feasibility_score": round(delivery_score, 4),
                "capacity_score": round(capacity_score, 4),
                "price_score": round(price_score, 4),
                "proximity_score": round(proximity_score, 4),
                "composite_score": round(composite, 4),
                "estimated_delivery_days": estimated_days,
                "distance_km": distance_km,
                "score": round(composite * 100, 2),  # 0-100 scale for ranking
                # Fix 1: record which catalogue item drove the price/delivery scores
                "matched_catalogue_item_id": str(best_item.id) if best_item else None,
            })

        # Sort by composite score descending, take top_n
        scored_matches.sort(key=lambda m: m["composite_score"], reverse=True)
        for rank, m in enumerate(scored_matches[:top_n], 1):
            m["rank"] = rank

        log.info(
            "enhanced_match_complete",
            rfq_id=str(rfq.id),
            candidates=len(raw_matches),
            after_filters=len(scored_matches),
            returned=min(len(scored_matches), top_n),
        )
        return scored_matches[:top_n]


class StubMatchmakingEngine:
    """Keyword-based stub — delegates to KeywordMatchmaker instead of random UUIDs."""

    def __init__(self, session: AsyncSession | None = None) -> None:
        self._session = session

    async def find_matches(
        self,
        rfq: "RFQ",
        rfq_embedding: list[float],
        top_n: int = 10,
    ) -> list[tuple[uuid.UUID, float]]:
        if self._session is not None:
            from src.marketplace.infrastructure.keyword_matchmaker import KeywordMatchmaker
            km = KeywordMatchmaker(self._session)
            return await km.find_matches(rfq, rfq_embedding, top_n)

        # No DB session — cannot match sellers. Return empty list rather than
        # fabricating random UUIDs with misleading high scores.
        log.warning("stub_matchmaker_no_session", rfq_id=str(rfq.id))
        return []


def explain_match(match_data: dict) -> dict:
    """Generate human-readable explanation for why a seller was recommended.

    Takes the scored match data and produces an explanation string
    for each scoring factor.
    """
    explanations = []
    total = match_data.get("composite_score", 0)

    factors = {
        "semantic_score": ("Product Match", "How well the seller's products match your RFQ"),
        "delivery_feasibility_score": ("Delivery", "Estimated delivery feasibility based on distance and capacity"),
        "capacity_score": ("Capacity", "Seller's available production capacity for your order size"),
        "price_score": ("Price Fit", "How competitive the seller's pricing is vs. your budget"),
        "proximity_score": ("Proximity", "Geographic distance between seller and delivery location"),
        "payment_score": ("Payment Terms", "Overlap between your preferred payment terms and seller's accepted terms"),
        "certification_score": ("Certifications", "Quality certifications held by the seller"),
    }

    for key, (label, description) in factors.items():
        score = match_data.get(key, 0)
        if score > 0:
            # Score contribution as percentage of composite
            contribution = (score * _DEFAULT_WEIGHTS.get(key.replace("_score", ""), 0.1)) / total * 100 if total > 0 else 0
            strength = "Strong" if score > 0.7 else "Moderate" if score > 0.4 else "Weak"
            explanations.append({
                "factor": label,
                "score": round(score, 3),
                "strength": strength,
                "contribution_pct": round(contribution, 1),
                "description": description,
            })

    return {
        "composite_score": round(total, 3),
        "factors": sorted(explanations, key=lambda x: x["score"], reverse=True),
        "summary": (
            f"This seller scored {total:.1%} overall. "
            f"Strongest factor: {explanations[0]['factor'] if explanations else 'N/A'}."
        ),
    }
