# context.md §3: Infrastructure repositories — concrete implementations of domain ports.

from __future__ import annotations

import uuid
from datetime import datetime, timedelta as _timedelta
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.negotiation.domain.agent_profile import AgentProfile
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
    ) -> list[dict]:
        """
        Retrieve Top-N similar chunks via cosine similarity.

        Uses pgvector <=> operator for HNSW-accelerated search.
        Returns list of {id, content, metadata, similarity}.
        """
        from sqlalchemy import text

        stmt = text(
            "SELECT id, content, metadata, "
            "1 - (embedding <=> :query_embedding) AS similarity "
            "FROM agent_memory "
            "WHERE tenant_id = :tenant_id "
            "ORDER BY embedding <=> :query_embedding "
            "LIMIT :limit"
        )
        result = await self._session.execute(
            stmt,
            {
                "tenant_id": str(tenant_id),
                "query_embedding": str(query_embedding),
                "limit": limit,
            },
        )
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
