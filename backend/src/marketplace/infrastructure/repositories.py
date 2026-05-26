# context.md §3: Infrastructure repositories — concrete implementations of domain ports.

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.marketplace.domain.capability_profile import CapabilityProfile
from src.marketplace.domain.match import Match
from src.marketplace.domain.rfq import RFQ
from src.marketplace.domain.value_objects import (
    BudgetRange,
    HSNCode,
    MatchStatus,
    RFQStatus,
    SimilarityScore,
)
from src.marketplace.infrastructure.models import (
    CapabilityProfileModel,
    MatchModel,
    RFQModel,
)
from src.identity.infrastructure.models import EnterpriseModel


# ── Domain ↔ ORM Mapping Helpers ─────────────────────────────────────────────


def _rfq_model_to_domain(m: RFQModel) -> RFQ:
    hsn = None
    if m.hsn_code:
        try:
            hsn = HSNCode(value=m.hsn_code)
        except Exception:
            hsn = None

    budget = None
    if m.budget_min is not None and m.budget_max is not None:
        try:
            budget = BudgetRange(
                min_value=Decimal(str(m.budget_min)),
                max_value=Decimal(str(m.budget_max)),
            )
        except Exception:
            budget = None

    rfq = RFQ(
        id=m.id,
        buyer_enterprise_id=m.enterprise_id,
        raw_document=m.raw_text,
        parsed_fields=m.parsed_fields,
        hsn_code=hsn,
        budget_range=budget,
        status=RFQStatus(m.status),
        confirmed_match_id=m.confirmed_match_id,
        geography_pref=m.geography or "IN",
        created_at=m.created_at,
    )
    rfq.all_products = getattr(m, "all_products", None)
    return rfq


def _match_model_to_domain(m: MatchModel) -> Match:
    return Match(
        id=m.id,
        rfq_id=m.rfq_id,
        seller_enterprise_id=m.seller_enterprise_id,
        similarity_score=SimilarityScore(value=float(m.score)),
        rank=m.rank,
        created_at=m.created_at,
    )


def _profile_model_to_domain(m: CapabilityProfileModel) -> CapabilityProfile:
    return CapabilityProfile(
        id=m.id,
        enterprise_id=m.enterprise_id,
        industry_vertical=m.industry_vertical,
        product_categories=m.commodities or [],
        geography_scope=m.geographies_served or [],
        trade_volume_min=Decimal(str(m.min_order_value)) if m.min_order_value else None,
        trade_volume_max=Decimal(str(m.max_order_value)) if m.max_order_value else None,
        embedding=m.embedding,
        profile_text=m.profile_text,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


# ── Repositories ──────────────────────────────────────────────────────────────


class PostgresRFQRepository:
    """Implements IRFQRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, rfq: RFQ) -> None:
        model = RFQModel(
            id=rfq.id,
            enterprise_id=rfq.buyer_enterprise_id,
            status=rfq.status.value,
            raw_text=rfq.raw_document,
            parsed_fields=rfq.parsed_fields,
            hsn_code=rfq.hsn_code.value if rfq.hsn_code else None,
            budget_min=float(rfq.budget_range.min_value) if rfq.budget_range else None,
            budget_max=float(rfq.budget_range.max_value) if rfq.budget_range else None,
            geography=rfq.geography_pref,
            confirmed_match_id=rfq.confirmed_match_id,
        )
        self._session.add(model)
        await self._session.flush()

    async def get_by_id(self, rfq_id: uuid.UUID) -> RFQ | None:
        stmt = select(RFQModel).where(RFQModel.id == rfq_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _rfq_model_to_domain(model) if model else None

    async def update(self, rfq: RFQ) -> None:
        values: dict = {
            "status": rfq.status.value,
            "parsed_fields": rfq.parsed_fields,
            "hsn_code": rfq.hsn_code.value if rfq.hsn_code else None,
            "budget_min": float(rfq.budget_range.min_value) if rfq.budget_range else None,
            "budget_max": float(rfq.budget_range.max_value) if rfq.budget_range else None,
            "geography": rfq.geography_pref,
            "confirmed_match_id": rfq.confirmed_match_id,
        }
        # Persist embedding when available (critical for pgvector matching)
        if rfq.embedding is not None:
            values["embedding"] = rfq.embedding
        # Persist all_products for multi-product RFQs
        if getattr(rfq, "all_products", None) is not None:
            values["all_products"] = rfq.all_products
        stmt = (
            update(RFQModel)
            .where(RFQModel.id == rfq.id)
            .values(**values)
        )
        await self._session.execute(stmt)

    async def list_by_buyer(
        self,
        buyer_enterprise_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
        statuses: list[str] | None = None,
    ) -> list[RFQ]:
        stmt = (
            select(RFQModel)
            .where(RFQModel.enterprise_id == buyer_enterprise_id)
            .order_by(RFQModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if statuses:
            stmt = stmt.where(RFQModel.status.in_(statuses))
        result = await self._session.execute(stmt)
        return [_rfq_model_to_domain(m) for m in result.scalars().all()]

    async def list_expired_candidates(self, cutoff: datetime) -> list[RFQ]:
        stmt = (
            select(RFQModel)
            .where(
                RFQModel.status.in_(["DRAFT", "PARSED", "MATCHED"]),
                RFQModel.created_at < cutoff,
            )
            .limit(100)
        )
        result = await self._session.execute(stmt)
        return [_rfq_model_to_domain(m) for m in result.scalars().all()]


class PostgresMatchRepository:
    """Implements IMatchRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_bulk(self, matches: list[Match]) -> None:
        models = [
            MatchModel(
                id=m.id,
                rfq_id=m.rfq_id,
                seller_enterprise_id=m.seller_enterprise_id,
                score=float(m.similarity_score.value),
                rank=m.rank,
                matched_rfq_variant=getattr(m, "matched_rfq_variant", None),
            )
            for m in matches
        ]
        self._session.add_all(models)
        await self._session.flush()

    async def get_by_id(self, match_id: uuid.UUID) -> Match | None:
        stmt = select(MatchModel).where(MatchModel.id == match_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _match_model_to_domain(model) if model else None

    async def list_by_rfq(self, rfq_id: uuid.UUID) -> list[Match]:
        stmt = (
            select(MatchModel)
            .where(MatchModel.rfq_id == rfq_id)
            .order_by(MatchModel.rank)
        )
        result = await self._session.execute(stmt)
        return [_match_model_to_domain(m) for m in result.scalars().all()]

    async def list_by_seller(
        self,
        seller_enterprise_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Match]:
        """List matches where this enterprise is the seller."""
        stmt = (
            select(MatchModel)
            .where(MatchModel.seller_enterprise_id == seller_enterprise_id)
            .order_by(MatchModel.rank)
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return [_match_model_to_domain(m) for m in result.scalars().all()]

    async def update(self, match: Match) -> None:
        stmt = (
            update(MatchModel)
            .where(MatchModel.id == match.id)
            .values(
                rank=match.rank,
                score=float(match.similarity_score.value) if match.similarity_score else 0.0,
            )
        )
        await self._session.execute(stmt)

    async def get_match_by_seller(
        self,
        rfq_id: uuid.UUID,
        seller_enterprise_id: uuid.UUID,
    ) -> Match | None:
        """Find the match record for a specific seller + RFQ combination."""
        stmt = (
            select(MatchModel)
            .where(
                MatchModel.rfq_id == rfq_id,
                MatchModel.seller_enterprise_id == seller_enterprise_id,
            )
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _match_model_to_domain(model) if model else None

    async def get_matches_with_details(
        self, rfq_id: uuid.UUID
    ) -> list[dict]:
        """Fetch matches with enterprise name and capabilities via joins."""
        stmt = (
            select(
                MatchModel.seller_enterprise_id,
                MatchModel.score,
                MatchModel.rank,
                EnterpriseModel.name.label("enterprise_name"),
            )
            .join(
                EnterpriseModel,
                MatchModel.seller_enterprise_id == EnterpriseModel.id,
            )
            .where(MatchModel.rfq_id == rfq_id)
            .order_by(MatchModel.rank.asc())
        )
        result = await self._session.execute(stmt)
        rows = result.fetchall()

        # Fetch capabilities from CapabilityProfileModel if available
        seller_ids = [row.seller_enterprise_id for row in rows]
        cap_stmt = (
            select(
                CapabilityProfileModel.enterprise_id,
                CapabilityProfileModel.commodities,
            )
            .where(CapabilityProfileModel.enterprise_id.in_(seller_ids))
        )
        cap_result = await self._session.execute(cap_stmt)
        cap_map = {
            row.enterprise_id: row.commodities or []
            for row in cap_result.fetchall()
        }

        return [
            {
                "enterprise_id": str(row.seller_enterprise_id),
                "enterprise_name": row.enterprise_name or "",
                "score": round(float(row.score) * 100, 1)
                    if float(row.score) <= 1.0
                    else round(float(row.score), 1),
                "rank": row.rank,
                "capabilities": cap_map.get(row.seller_enterprise_id, []),
            }
            for row in rows
        ]


class PostgresCapabilityProfileRepository:
    """Implements ICapabilityProfileRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, profile: CapabilityProfile) -> None:
        model = CapabilityProfileModel(
            id=profile.id,
            enterprise_id=profile.enterprise_id,
            industry_vertical=profile.industry_vertical,
            commodities=profile.product_categories,
            geographies_served=profile.geography_scope,
            min_order_value=float(profile.trade_volume_min) if profile.trade_volume_min else None,
            max_order_value=float(profile.trade_volume_max) if profile.trade_volume_max else None,
            profile_text=profile.profile_text,
            embedding=profile.embedding,
        )
        self._session.add(model)
        await self._session.flush()

    async def get_by_enterprise(
        self, enterprise_id: uuid.UUID
    ) -> CapabilityProfile | None:
        stmt = select(CapabilityProfileModel).where(
            CapabilityProfileModel.enterprise_id == enterprise_id
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _profile_model_to_domain(model) if model else None

    async def update(self, profile: CapabilityProfile) -> None:
        stmt = (
            update(CapabilityProfileModel)
            .where(CapabilityProfileModel.id == profile.id)
            .values(
                industry_vertical=profile.industry_vertical,
                commodities=profile.product_categories,
                geographies_served=profile.geography_scope,
                min_order_value=float(profile.trade_volume_min) if profile.trade_volume_min else None,
                max_order_value=float(profile.trade_volume_max) if profile.trade_volume_max else None,
                profile_text=profile.profile_text,
                embedding=profile.embedding,
            )
        )
        await self._session.execute(stmt)

    async def list_without_embeddings(self, limit: int = 100) -> list[CapabilityProfile]:
        stmt = (
            select(CapabilityProfileModel)
            .where(CapabilityProfileModel.embedding.is_(None))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [_profile_model_to_domain(m) for m in result.scalars().all()]
