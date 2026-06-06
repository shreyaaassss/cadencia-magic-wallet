# context.md §3: Infrastructure repositories — concrete implementations of domain ports.

from __future__ import annotations

import uuid
from datetime import datetime
from datetime import timedelta as _timedelta
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.negotiation.domain.agent_profile import AgentProfile
from src.negotiation.domain.negotiation_insight import NegotiationInsight
from src.negotiation.domain.negotiation_record import (
    NegotiationOutcome,
    NegotiationRecord,
    RecordType,
)
from src.negotiation.domain.offer import Offer, ProposerRole
from src.negotiation.domain.opponent_model import OpponentBelief
from src.negotiation.domain.playbook import IndustryPlaybook
from src.negotiation.domain.session import NegotiationSession, SessionStatus
from src.negotiation.domain.value_objects import (
    AutomationLevel,
    Confidence,
    OfferValue,
    RiskProfile,
    RoundNumber,
    StrategyWeights,
)
from src.negotiation.infrastructure.models import (
    AgentMemoryModel,
    AgentProfileModel,
    IndustryPlaybookModel,
    NegotiationInsightModel,
    NegotiationRecordModel,
    NegotiationSessionModel,
    OfferModel,
    OpponentProfileModel,
)

# ── Domain ↔ ORM Mapping Helpers ─────────────────────────────────────────────

# DB uses FULLY_AUTONOMOUS; domain uses FULL. Bi-directional mapping.
_AUTOMATION_TO_DB = {"FULL": "FULLY_AUTONOMOUS", "SUPERVISED": "SUPERVISED", "MANUAL": "MANUAL"}
_AUTOMATION_FROM_DB = {"FULLY_AUTONOMOUS": "FULL", "SUPERVISED": "SUPERVISED", "MANUAL": "MANUAL"}


def _offer_model_to_domain(m: OfferModel) -> Offer:
    return Offer(
        id=m.id,
        session_id=m.session_id,
        round_number=RoundNumber(value=m.round_number),
        proposer_role=ProposerRole(m.proposer_role),
        price=OfferValue(amount=Decimal(str(m.price)), currency="INR"),
        terms=m.raw_llm_output or {},
        confidence=Confidence(value=m.confidence) if m.confidence is not None else None,
        agent_reasoning=m.reasoning,
        is_human_override=m.is_human_override,
        created_at=m.created_at,
    )


def _session_model_to_domain(m: NegotiationSessionModel) -> NegotiationSession:
    offers = sorted(
        [_offer_model_to_domain(o) for o in (m.offers or [])],
        key=lambda o: o.round_number.value,
    )
    agreed_price = None
    if m.agreed_price is not None:
        agreed_price = OfferValue(amount=Decimal(str(m.agreed_price)), currency="INR")

    # Map status — handle both DANP and legacy statuses
    try:
        status = SessionStatus(m.status)
    except ValueError:
        status = SessionStatus.ACTIVE  # Fallback for unknown statuses

    return NegotiationSession(
        id=m.id,
        rfq_id=m.rfq_id,
        match_id=m.match_id,
        buyer_enterprise_id=m.buyer_enterprise_id,
        seller_enterprise_id=m.seller_enterprise_id,
        status=status,
        agreed_price=agreed_price,
        agreed_terms=m.agreed_terms_json,
        round_count=RoundNumber(value=m.current_round),
        offers=offers,
        created_at=m.created_at,
        completed_at=m.completed_at,
        expires_at=getattr(m, "expires_at", None) or (m.created_at + _timedelta(hours=24)),
        schema_failure_count=getattr(m, "schema_failure_count", 0) or 0,
        stall_counter=getattr(m, "stall_counter", 0) or 0,
        # BUG-12 FIX: restore persisted Bayesian beliefs
        opponent_beliefs=getattr(m, "opponent_beliefs", None),
        conversation_transcript=getattr(m, "conversation_transcript", None),
        deal_quality_score=getattr(m, "deal_quality_score", None),
        product_context=getattr(m, "product_context", None),
    )


def _profile_model_to_domain(m: AgentProfileModel) -> AgentProfile:
    sw_data = m.strategy_weights or {}
    rp_data = m.risk_profile or {}
    return AgentProfile(
        id=m.id,
        enterprise_id=m.enterprise_id,
        strategy_weights=StrategyWeights(
            concession_rate=sw_data.get("concession_rate", 0.05),
            acceptance_threshold=sw_data.get("acceptance_threshold", 0.02),
            avg_deviation=sw_data.get("avg_deviation", 0.0),
            avg_rounds=sw_data.get("avg_rounds", 5.0),
            win_rate=sw_data.get("win_rate", 0.5),
            stall_threshold=sw_data.get("stall_threshold", 10),
        ),
        risk_profile=RiskProfile(
            budget_ceiling=Decimal(str(rp_data.get("budget_ceiling", 1000000))),
            margin_floor=Decimal(str(rp_data.get("margin_floor", 10))),
            liquidity_buffer=Decimal(str(rp_data.get("liquidity_buffer", 50000))),
            risk_appetite=rp_data.get("risk_appetite", "MEDIUM"),
        ),
        automation_level=AutomationLevel(value=_AUTOMATION_FROM_DB.get(m.automation_level, m.automation_level)),
        version=1,
        history_embedding=m.history_embedding,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def _playbook_model_to_domain(m: IndustryPlaybookModel) -> IndustryPlaybook:
    return IndustryPlaybook(
        id=m.id,
        vertical=m.industry_name,
        playbook_config=m.strategy_hints or {},
        created_at=m.created_at,
    )


# ── Repositories ──────────────────────────────────────────────────────────────


class PostgresSessionRepository:
    """Implements ISessionRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def get_db_session(self) -> AsyncSession:
        """
        BUG-07 FIX: Expose the underlying AsyncSession via a public method.
        External callers (service layer, router) should use this instead of
        directly accessing `_session` to avoid DIP violation and fragile coupling.
        """
        return self._session


    async def save(self, session: NegotiationSession) -> None:
        model = NegotiationSessionModel(
            id=session.id,
            rfq_id=session.rfq_id,
            match_id=session.match_id,
            buyer_enterprise_id=session.buyer_enterprise_id,
            seller_enterprise_id=session.seller_enterprise_id,
            status=session.status.value,
            current_round=session.round_count.value,
            agreed_price=float(session.agreed_price.amount) if session.agreed_price else None,
            agreed_terms_json=session.agreed_terms,
            completed_at=session.completed_at,
            schema_failure_count=session.schema_failure_count,
            stall_counter=session.stall_counter,
            opponent_beliefs=session.opponent_beliefs,  # BUG-12 FIX
            conversation_transcript=getattr(session, "conversation_transcript", None),
            deal_quality_score=getattr(session, "deal_quality_score", None),
            product_context=getattr(session, "product_context", None),
        )
        self._session.add(model)
        await self._session.flush()

    async def get_by_id(self, session_id: uuid.UUID) -> NegotiationSession | None:
        stmt = (
            select(NegotiationSessionModel)
            .options(selectinload(NegotiationSessionModel.offers))
            .where(NegotiationSessionModel.id == session_id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _session_model_to_domain(model) if model else None

    async def get_by_match_id(self, match_id: uuid.UUID) -> NegotiationSession | None:
        stmt = (
            select(NegotiationSessionModel)
            .options(selectinload(NegotiationSessionModel.offers))
            .where(NegotiationSessionModel.match_id == match_id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _session_model_to_domain(model) if model else None

    async def update(self, session: NegotiationSession) -> None:
        stmt = (
            update(NegotiationSessionModel)
            .where(NegotiationSessionModel.id == session.id)
            .values(
                status=session.status.value,
                current_round=session.round_count.value,
                agreed_price=float(session.agreed_price.amount) if session.agreed_price else None,
                agreed_terms_json=session.agreed_terms,
                completed_at=session.completed_at,
                schema_failure_count=session.schema_failure_count,
                stall_counter=session.stall_counter,
                opponent_beliefs=session.opponent_beliefs,  # BUG-12 FIX
                conversation_transcript=getattr(session, "conversation_transcript", None),
                deal_quality_score=getattr(session, "deal_quality_score", None),
                product_context=getattr(session, "product_context", None),
            )
        )
        await self._session.execute(stmt)

    async def list_by_enterprise(
        self,
        enterprise_id: uuid.UUID | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[NegotiationSession]:
        """List sessions where enterprise is buyer or seller, optionally filtered by status."""
        from sqlalchemy import or_

        stmt = (
            select(NegotiationSessionModel)
            .options(selectinload(NegotiationSessionModel.offers))
        )
        if enterprise_id:
            stmt = stmt.where(
                or_(
                    NegotiationSessionModel.buyer_enterprise_id == enterprise_id,
                    NegotiationSessionModel.seller_enterprise_id == enterprise_id,
                )
            )
        if status:
            stmt = stmt.where(NegotiationSessionModel.status == status)
        stmt = stmt.order_by(NegotiationSessionModel.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return [_session_model_to_domain(m) for m in result.scalars().all()]

    async def list_active(self, limit: int, offset: int) -> list[NegotiationSession]:
        stmt = (
            select(NegotiationSessionModel)
            .options(selectinload(NegotiationSessionModel.offers))
            .where(NegotiationSessionModel.status.in_([
                "ACTIVE", "INIT",
                "SELLER_ANCHOR", "BUYER_RESPONSE",
                "BUYER_ANCHOR", "SELLER_RESPONSE",
                "ROUND_LOOP",
            ]))
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return [_session_model_to_domain(m) for m in result.scalars().all()]

    async def list_expired_candidates(self, cutoff: datetime) -> list[NegotiationSession]:
        stmt = (
            select(NegotiationSessionModel)
            .where(
                NegotiationSessionModel.status.in_([
                    "ACTIVE", "HUMAN_REVIEW", "INIT",
                    "SELLER_ANCHOR", "BUYER_RESPONSE",
                    "BUYER_ANCHOR", "SELLER_RESPONSE",
                    "ROUND_LOOP",
                ]),
                NegotiationSessionModel.created_at < cutoff,
            )
            .limit(100)
        )
        result = await self._session.execute(stmt)
        return [_session_model_to_domain(m) for m in result.scalars().all()]


class PostgresOfferRepository:
    """Implements IOfferRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, offer: Offer) -> None:
        model = OfferModel(
            id=offer.id,
            session_id=offer.session_id,
            round_number=offer.round_number.value,
            proposer_role=offer.proposer_role.value,
            price=float(offer.price.amount),
            confidence=offer.confidence.value if offer.confidence else None,
            reasoning=offer.agent_reasoning,
            is_human_override=offer.is_human_override,
            raw_llm_output=offer.terms,
        )
        self._session.add(model)
        await self._session.flush()

    async def list_by_session(self, session_id: uuid.UUID) -> list[Offer]:
        stmt = (
            select(OfferModel)
            .where(OfferModel.session_id == session_id)
            .order_by(OfferModel.round_number)
        )
        result = await self._session.execute(stmt)
        return [_offer_model_to_domain(m) for m in result.scalars().all()]

    async def get_by_id(self, offer_id: uuid.UUID) -> Offer | None:
        stmt = select(OfferModel).where(OfferModel.id == offer_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _offer_model_to_domain(model) if model else None


class PostgresAgentProfileRepository:
    """Implements IAgentProfileRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_enterprise(self, enterprise_id: uuid.UUID) -> AgentProfile | None:
        stmt = select(AgentProfileModel).where(
            AgentProfileModel.enterprise_id == enterprise_id
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _profile_model_to_domain(model) if model else None

    async def save(self, profile: AgentProfile) -> None:
        model = AgentProfileModel(
            id=profile.id,
            enterprise_id=profile.enterprise_id,
            automation_level=_AUTOMATION_TO_DB.get(profile.automation_level.value, profile.automation_level.value),
            risk_profile={
                "budget_ceiling": float(profile.risk_profile.budget_ceiling),
                "margin_floor": float(profile.risk_profile.margin_floor),
                "liquidity_buffer": float(profile.risk_profile.liquidity_buffer),
                "risk_appetite": profile.risk_profile.risk_appetite,
            },
            strategy_weights={
                "concession_rate": profile.strategy_weights.concession_rate,
                "acceptance_threshold": profile.strategy_weights.acceptance_threshold,
                "avg_deviation": profile.strategy_weights.avg_deviation,
                "avg_rounds": profile.strategy_weights.avg_rounds,
                "win_rate": profile.strategy_weights.win_rate,
                "stall_threshold": profile.strategy_weights.stall_threshold,
            },
        )
        self._session.add(model)
        await self._session.flush()

    async def update(self, profile: AgentProfile) -> None:
        stmt = (
            update(AgentProfileModel)
            .where(AgentProfileModel.id == profile.id)
            .values(
                automation_level=_AUTOMATION_TO_DB.get(profile.automation_level.value, profile.automation_level.value),
                risk_profile={
                    "budget_ceiling": float(profile.risk_profile.budget_ceiling),
                    "margin_floor": float(profile.risk_profile.margin_floor),
                    "liquidity_buffer": float(profile.risk_profile.liquidity_buffer),
                    "risk_appetite": profile.risk_profile.risk_appetite,
                },
                strategy_weights={
                    "concession_rate": profile.strategy_weights.concession_rate,
                    "acceptance_threshold": profile.strategy_weights.acceptance_threshold,
                    "avg_deviation": profile.strategy_weights.avg_deviation,
                    "avg_rounds": profile.strategy_weights.avg_rounds,
                    "win_rate": profile.strategy_weights.win_rate,
                    "stall_threshold": profile.strategy_weights.stall_threshold,
                },
            )
        )
        await self._session.execute(stmt)


class PostgresPlaybookRepository:
    """Implements IPlaybookRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_vertical(self, vertical: str) -> IndustryPlaybook | None:
        stmt = (
            select(IndustryPlaybookModel)
            .where(
                IndustryPlaybookModel.industry_name == vertical,
                IndustryPlaybookModel.is_active == True,  # noqa: E712
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _playbook_model_to_domain(model) if model else None

    async def list_all(self) -> list[IndustryPlaybook]:
        stmt = select(IndustryPlaybookModel).where(
            IndustryPlaybookModel.is_active == True  # noqa: E712
        )
        result = await self._session.execute(stmt)
        return [_playbook_model_to_domain(m) for m in result.scalars().all()]


class PostgresOpponentProfileRepository:
    """Implements IOpponentProfileRepository — persistent Bayesian beliefs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_belief(
        self, observer_id: uuid.UUID, target_id: uuid.UUID
    ) -> OpponentBelief | None:
        stmt = select(OpponentProfileModel).where(
            OpponentProfileModel.observer_id == observer_id,
            OpponentProfileModel.target_id == target_id,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model and model.belief:
            return OpponentBelief.from_dict(model.belief)
        return None

    async def save_belief(
        self,
        observer_id: uuid.UUID,
        target_id: uuid.UUID,
        belief: OpponentBelief,
        flexibility: float,
    ) -> None:
        model = OpponentProfileModel(
            observer_id=observer_id,
            target_id=target_id,
            flexibility=flexibility,
            belief=belief.to_dict(),
            rounds_observed=0,
        )
        self._session.add(model)
        await self._session.flush()

    async def update_belief(
        self,
        observer_id: uuid.UUID,
        target_id: uuid.UUID,
        belief: OpponentBelief,
        flexibility: float,
    ) -> None:
        stmt = (
            update(OpponentProfileModel)
            .where(
                OpponentProfileModel.observer_id == observer_id,
                OpponentProfileModel.target_id == target_id,
            )
            .values(
                flexibility=flexibility,
                belief=belief.to_dict(),
            )
        )
        await self._session.execute(stmt)


class PostgresAgentMemoryRepository:
    """Implements IAgentMemoryRepository — pgvector RAG storage."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def store(
        self,
        tenant_id: uuid.UUID,
        role: str,
        content: str,
        embedding: list[float],
        metadata: dict,
    ) -> uuid.UUID:
        """Store a chunked + embedded document fragment."""
        model = AgentMemoryModel(
            tenant_id=tenant_id,
            role=role,
            content=content,
            embedding=embedding,
            metadata_json=metadata,
        )
        self._session.add(model)
        await self._session.flush()
        return model.id

    async def retrieve_similar(
        self,
        tenant_id: uuid.UUID,
        query_embedding: list[float],
        limit: int = 5,
        role: str | None = None,
    ) -> list[dict]:
        """
        Retrieve Top-N similar chunks via cosine similarity.

        Uses pgvector <=> operator for HNSW-accelerated search.
        When role is provided, filters to only return memories stored
        under that role (buyer/seller) — prevents cross-perspective leaks.
        Returns list of {id, content, metadata, similarity}.
        """
        from sqlalchemy import text

        if role:
            stmt = text(
                "SELECT id, content, metadata, "
                "1 - (embedding <=> :query_embedding) AS similarity "
                "FROM agent_memory "
                "WHERE tenant_id = :tenant_id AND role = :role "
                "ORDER BY embedding <=> :query_embedding "
                "LIMIT :limit"
            )
            params = {
                "tenant_id": str(tenant_id),
                "query_embedding": str(query_embedding),
                "role": role,
                "limit": limit,
            }
        else:
            stmt = text(
                "SELECT id, content, metadata, "
                "1 - (embedding <=> :query_embedding) AS similarity "
                "FROM agent_memory "
                "WHERE tenant_id = :tenant_id "
                "ORDER BY embedding <=> :query_embedding "
                "LIMIT :limit"
            )
            params = {
                "tenant_id": str(tenant_id),
                "query_embedding": str(query_embedding),
                "limit": limit,
            }
        result = await self._session.execute(stmt, params)
        rows = result.fetchall()
        return [
            {
                "id": str(row[0]),
                "content": row[1],
                "metadata": row[2] or {},
                "similarity": float(row[3]) if row[3] else 0.0,
            }
            for row in rows
        ]

    async def delete_by_tenant(self, tenant_id: uuid.UUID) -> int:
        """Delete all memory for a tenant (re-ingestion)."""
        from sqlalchemy import delete

        stmt = delete(AgentMemoryModel).where(
            AgentMemoryModel.tenant_id == tenant_id
        )
        result = await self._session.execute(stmt)
        return result.rowcount  # type: ignore[return-value]

    async def count_by_tenant(self, tenant_id: uuid.UUID) -> int:
        """Count memory chunks for a tenant."""
        from sqlalchemy import func as sa_func

        stmt = select(sa_func.count()).where(
            AgentMemoryModel.tenant_id == tenant_id
        )
        result = await self._session.execute(stmt)
        return result.scalar() or 0


# ── Phase 6: Negotiation Memory Repositories ─────────────────────────────────


def _record_model_to_domain(m: NegotiationRecordModel) -> NegotiationRecord:
    return NegotiationRecord(
        id=m.id,
        enterprise_id=m.enterprise_id,
        record_type=RecordType(m.record_type),
        source_session_id=m.source_session_id,
        counterparty_enterprise_id=m.counterparty_enterprise_id,
        enterprise_role=m.enterprise_role,
        product_name=m.product_name,
        product_category=m.product_category,
        hsn_code=m.hsn_code,
        industry_vertical=m.industry_vertical,
        quantity=Decimal(str(m.quantity)) if m.quantity is not None else None,
        quantity_unit=m.quantity_unit,
        outcome=NegotiationOutcome(m.outcome),
        agreed_price_inr=Decimal(str(m.agreed_price_inr)) if m.agreed_price_inr is not None else None,
        initial_ask_price_inr=Decimal(str(m.initial_ask_price_inr)) if m.initial_ask_price_inr is not None else None,
        initial_bid_price_inr=Decimal(str(m.initial_bid_price_inr)) if m.initial_bid_price_inr is not None else None,
        final_discount_pct=Decimal(str(m.final_discount_pct)) if m.final_discount_pct is not None else None,
        total_rounds=m.total_rounds,
        duration_hours=Decimal(str(m.duration_hours)) if m.duration_hours is not None else None,
        buyer_avg_concession_pct=Decimal(str(m.buyer_avg_concession_pct)) if m.buyer_avg_concession_pct is not None else None,
        seller_avg_concession_pct=Decimal(str(m.seller_avg_concession_pct)) if m.seller_avg_concession_pct is not None else None,
        buyer_style=m.buyer_style,
        seller_style=m.seller_style,
        deal_quality_score=Decimal(str(m.deal_quality_score)) if m.deal_quality_score is not None else None,
        agreed_terms=m.agreed_terms,
        payment_terms=m.payment_terms,
        delivery_window_days=m.delivery_window_days,
        offer_sequence=m.offer_sequence,
        conversation_summary=m.conversation_summary,
        raw_source_text=m.raw_source_text,
        schema_version=m.schema_version,
        confidence_score=Decimal(str(m.confidence_score)) if m.confidence_score is not None else None,
        source_filename=m.source_filename,
        normalized_at=m.normalized_at,
        retention_expires_at=m.retention_expires_at,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def _insight_model_to_domain(m: NegotiationInsightModel) -> NegotiationInsight:
    return NegotiationInsight(
        id=m.id,
        enterprise_id=m.enterprise_id,
        role=m.role,
        total_negotiations=m.total_negotiations,
        success_rate=Decimal(str(m.success_rate)),
        avg_rounds_to_close=Decimal(str(m.avg_rounds_to_close)),
        avg_discount_achieved_pct=Decimal(str(m.avg_discount_achieved_pct)),
        avg_deal_quality=Decimal(str(m.avg_deal_quality)),
        dominant_style=m.dominant_style or "collaborative",
        style_distribution=m.style_distribution or {},
        top_products=m.top_products or [],
        top_verticals=m.top_verticals or [],
        counterparty_stats=m.counterparty_stats or [],
        seasonal_patterns=m.seasonal_patterns,
        strategy_recommendations=m.strategy_recommendations or [],
        last_computed_at=m.last_computed_at,
        schema_version=m.schema_version,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


class PostgresNegotiationRecordRepository:
    """Implements INegotiationRecordRepository — pgvector-backed canonical record storage."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, record: NegotiationRecord) -> None:
        model = NegotiationRecordModel(
            id=record.id,
            enterprise_id=record.enterprise_id,
            record_type=record.record_type.value,
            source_session_id=record.source_session_id,
            counterparty_enterprise_id=record.counterparty_enterprise_id,
            enterprise_role=record.enterprise_role,
            product_name=record.product_name,
            product_category=record.product_category,
            hsn_code=record.hsn_code,
            industry_vertical=record.industry_vertical,
            quantity=float(record.quantity) if record.quantity is not None else None,
            quantity_unit=record.quantity_unit,
            outcome=record.outcome.value,
            agreed_price_inr=float(record.agreed_price_inr) if record.agreed_price_inr is not None else None,
            initial_ask_price_inr=float(record.initial_ask_price_inr) if record.initial_ask_price_inr is not None else None,
            initial_bid_price_inr=float(record.initial_bid_price_inr) if record.initial_bid_price_inr is not None else None,
            final_discount_pct=float(record.final_discount_pct) if record.final_discount_pct is not None else None,
            total_rounds=record.total_rounds,
            duration_hours=float(record.duration_hours) if record.duration_hours is not None else None,
            buyer_avg_concession_pct=float(record.buyer_avg_concession_pct) if record.buyer_avg_concession_pct is not None else None,
            seller_avg_concession_pct=float(record.seller_avg_concession_pct) if record.seller_avg_concession_pct is not None else None,
            buyer_style=record.buyer_style,
            seller_style=record.seller_style,
            deal_quality_score=float(record.deal_quality_score) if record.deal_quality_score is not None else None,
            agreed_terms=record.agreed_terms,
            payment_terms=record.payment_terms,
            delivery_window_days=record.delivery_window_days,
            offer_sequence=record.offer_sequence,
            conversation_summary=record.conversation_summary,
            raw_source_text=record.raw_source_text,
            schema_version=record.schema_version,
            confidence_score=float(record.confidence_score) if record.confidence_score is not None else None,
            source_filename=record.source_filename,
            normalized_at=record.normalized_at,
            retention_expires_at=record.retention_expires_at,
            embedding=record.embedding,
        )
        self._session.add(model)
        await self._session.flush()

    async def get_by_id(self, record_id: uuid.UUID) -> NegotiationRecord | None:
        stmt = select(NegotiationRecordModel).where(NegotiationRecordModel.id == record_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _record_model_to_domain(model) if model else None

    async def get_by_session_id(self, session_id: uuid.UUID) -> NegotiationRecord | None:
        stmt = select(NegotiationRecordModel).where(
            NegotiationRecordModel.source_session_id == session_id
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _record_model_to_domain(model) if model else None

    async def list_by_enterprise(
        self,
        enterprise_id: uuid.UUID,
        filters: dict,
        limit: int,
        offset: int,
    ) -> list[NegotiationRecord]:
        stmt = select(NegotiationRecordModel).where(
            NegotiationRecordModel.enterprise_id == enterprise_id
        )
        if filters.get("outcome"):
            stmt = stmt.where(NegotiationRecordModel.outcome == filters["outcome"])
        if filters.get("record_type"):
            stmt = stmt.where(NegotiationRecordModel.record_type == filters["record_type"])
        if filters.get("product_category"):
            stmt = stmt.where(
                NegotiationRecordModel.product_category == filters["product_category"]
            )
        stmt = stmt.order_by(NegotiationRecordModel.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return [_record_model_to_domain(m) for m in result.scalars().all()]

    async def search_similar(
        self,
        enterprise_id: uuid.UUID,
        query_embedding: list[float],
        limit: int = 5,
    ) -> list[NegotiationRecord]:
        """Semantic search via pgvector cosine similarity — tenant-scoped."""
        from sqlalchemy import text

        stmt = text(
            "SELECT id FROM negotiation_records "
            "WHERE enterprise_id = :enterprise_id "
            "AND embedding IS NOT NULL "
            "ORDER BY embedding <=> :query_embedding "
            "LIMIT :limit"
        )
        result = await self._session.execute(
            stmt,
            {
                "enterprise_id": str(enterprise_id),
                "query_embedding": str(query_embedding),
                "limit": limit,
            },
        )
        ids = [row[0] for row in result.fetchall()]
        if not ids:
            return []
        records_stmt = select(NegotiationRecordModel).where(
            NegotiationRecordModel.id.in_(ids)
        )
        records_result = await self._session.execute(records_stmt)
        return [_record_model_to_domain(m) for m in records_result.scalars().all()]


class PostgresNegotiationInsightRepository:
    """Implements INegotiationInsightRepository — one row per enterprise, upsert semantics."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_enterprise(self, enterprise_id: uuid.UUID) -> NegotiationInsight | None:
        stmt = select(NegotiationInsightModel).where(
            NegotiationInsightModel.enterprise_id == enterprise_id
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _insight_model_to_domain(model) if model else None

    async def save(self, insight: NegotiationInsight) -> None:
        model = NegotiationInsightModel(
            id=insight.id,
            enterprise_id=insight.enterprise_id,
            role=insight.role,
            total_negotiations=insight.total_negotiations,
            success_rate=float(insight.success_rate),
            avg_rounds_to_close=float(insight.avg_rounds_to_close),
            avg_discount_achieved_pct=float(insight.avg_discount_achieved_pct),
            avg_deal_quality=float(insight.avg_deal_quality),
            dominant_style=insight.dominant_style,
            style_distribution=insight.style_distribution,
            top_products=insight.top_products,
            top_verticals=insight.top_verticals,
            counterparty_stats=insight.counterparty_stats,
            seasonal_patterns=insight.seasonal_patterns,
            strategy_recommendations=insight.strategy_recommendations,
            last_computed_at=insight.last_computed_at,
            schema_version=insight.schema_version,
        )
        self._session.add(model)
        await self._session.flush()

    async def upsert(self, insight: NegotiationInsight) -> None:
        """Insert or update — one row per enterprise."""
        existing_stmt = select(NegotiationInsightModel).where(
            NegotiationInsightModel.enterprise_id == insight.enterprise_id
        )
        result = await self._session.execute(existing_stmt)
        existing = result.scalar_one_or_none()

        if existing:
            stmt = (
                update(NegotiationInsightModel)
                .where(NegotiationInsightModel.enterprise_id == insight.enterprise_id)
                .values(
                    role=insight.role,
                    total_negotiations=insight.total_negotiations,
                    success_rate=float(insight.success_rate),
                    avg_rounds_to_close=float(insight.avg_rounds_to_close),
                    avg_discount_achieved_pct=float(insight.avg_discount_achieved_pct),
                    avg_deal_quality=float(insight.avg_deal_quality),
                    dominant_style=insight.dominant_style,
                    style_distribution=insight.style_distribution,
                    top_products=insight.top_products,
                    top_verticals=insight.top_verticals,
                    counterparty_stats=insight.counterparty_stats,
                    seasonal_patterns=insight.seasonal_patterns,
                    strategy_recommendations=insight.strategy_recommendations,
                    last_computed_at=insight.last_computed_at,
                    schema_version=insight.schema_version,
                )
            )
            await self._session.execute(stmt)
        else:
            await self.save(insight)
