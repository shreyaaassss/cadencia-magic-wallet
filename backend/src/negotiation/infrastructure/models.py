"""
SQLAlchemy ORM models for the negotiation bounded context.

Tables: negotiation_sessions, offers, agent_profiles, industry_playbooks
context.md §11 — Database Schema.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]

from src.shared.infrastructure.db.base import Base


class NegotiationSessionModel(Base):
    """
    Negotiation session aggregate (negotiation bounded context).

    status: ACTIVE | AGREED | FAILED | EXPIRED | HUMAN_REVIEW
    context.md §9.3 — Negotiation Session State Machine.
    """

    __tablename__ = "negotiation_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE','AGREED','FAILED','EXPIRED','HUMAN_REVIEW',"
            "'INIT','SELLER_ANCHOR','BUYER_RESPONSE',"
            "'BUYER_ANCHOR','SELLER_RESPONSE','ROUND_LOOP',"
            "'WALK_AWAY','STALLED','TIMEOUT','POLICY_BREACH')",
            name="ck_negotiation_sessions_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    rfq_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    match_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    buyer_enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("enterprises.id"),
        nullable=False,
    )
    seller_enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("enterprises.id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="ACTIVE"
    )
    current_round: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    stall_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="10"
    )
    convergence_threshold_pct: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="2.0"
    )
    agreed_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    agreed_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    agreed_terms_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    schema_failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    stall_counter: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    # BUG-12 FIX: Persist Bayesian opponent beliefs so pod restarts don't lose
    # accumulated classification state. Nullable for backward compatibility.
    opponent_beliefs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    conversation_transcript: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    offers: Mapped[list[OfferModel]] = relationship("OfferModel", back_populates="session")


_sessions_rfq_idx = Index("ix_negotiation_sessions_rfq_id", NegotiationSessionModel.rfq_id)
_sessions_status_idx = Index(
    "ix_negotiation_sessions_status", NegotiationSessionModel.status
)
_sessions_buyer_idx = Index(
    "ix_negotiation_sessions_buyer_enterprise_id",
    NegotiationSessionModel.buyer_enterprise_id,
)


class OfferModel(Base):
    """
    Offer entity (negotiation bounded context).

    proposer_role: BUYER | SELLER | HUMAN
    Soft-delete: archived_at (context.md §11 — 3-year retention).
    """

    __tablename__ = "offers"
    __table_args__ = (
        CheckConstraint(
            "proposer_role IN ('BUYER','SELLER','HUMAN')",
            name="ck_offers_proposer_role",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("negotiation_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    proposer_role: Mapped[str] = mapped_column(String(10), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_human_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    raw_llm_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    archived_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    session: Mapped[NegotiationSessionModel] = relationship(
        "NegotiationSessionModel", back_populates="offers"
    )


_offers_session_round_idx = Index(
    "ix_offers_session_id_round_number", OfferModel.session_id, OfferModel.round_number
)


class AgentProfileModel(Base):
    """
    Agent profile for LLM negotiation personalisation (negotiation bounded context).

    strategy_weights: JSONB {aggression, patience, risk_tolerance, ...}
    automation_level: FULLY_AUTONOMOUS | SUPERVISED | MANUAL
    context.md §2 — Agent Personalization Engine (Layer 2).
    """

    __tablename__ = "agent_profiles"
    __table_args__ = (
        UniqueConstraint("enterprise_id", name="uq_agent_profiles_enterprise_id"),
        CheckConstraint(
            "automation_level IN ('FULLY_AUTONOMOUS','SUPERVISED','MANUAL')",
            name="ck_agent_profiles_automation_level",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("enterprises.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    automation_level: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="SUPERVISED"
    )
    risk_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    strategy_weights: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    budget_ceiling: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_rounds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="10")
    # Historical embedding for context injection
    history_embedding: Mapped[list | None] = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class IndustryPlaybookModel(Base):
    """
    Industry playbook injected into LLM agent context (negotiation bounded context).

    Provides sector-specific negotiation strategies and norms.
    """

    __tablename__ = "industry_playbooks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    hsn_prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    industry_name: Mapped[str] = mapped_column(String(100), nullable=False)
    playbook_text: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_hints: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


_playbooks_hsn_idx = Index("ix_industry_playbooks_hsn_prefix", IndustryPlaybookModel.hsn_prefix)


class OpponentProfileModel(Base):
    """
    Persistent Bayesian opponent belief profiles.

    observer_id: The agent observing (buyer or seller enterprise).
    target_id:   The agent being observed.
    flexibility: Last computed flexibility score.
    belief:      JSONB {cooperative, strategic, stubborn, bluffing} posteriors.

    PRIMARY KEY: (observer_id, target_id) — one profile per pair.
    """

    __tablename__ = "opponent_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    observer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    flexibility: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0.5"
    )
    belief: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    rounds_observed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


_opponent_profiles_pair_idx = Index(
    "ix_opponent_profiles_observer_target",
    OpponentProfileModel.observer_id,
    OpponentProfileModel.target_id,
    unique=True,
)
_opponent_profiles_target_idx = Index(
    "ix_opponent_profiles_target_id",
    OpponentProfileModel.target_id,
)


class AgentMemoryModel(Base):
    """
    pgvector-backed agent memory for RAG retrieval.

    Stores chunked + embedded enterprise documents (contracts, past RFQs,
    terms sheets) for retrieval-augmented agent intelligence.

    tenant_id: Enterprise UUID — tenant isolation.
    role:      buyer | seller — scoped retrieval.
    content:   512-token text chunk.
    embedding: 1536-dim float vector (Gemini text-embedding-004).
    metadata:  JSONB {source: s3_key, chunk_index, original_filename}.

    Index: HNSW on embedding for <50ms Top-5 cosine similarity queries.
    """

    __tablename__ = "agent_memory"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="buyer"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(1536), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


_agent_memory_tenant_idx = Index(
    "ix_agent_memory_tenant_id", AgentMemoryModel.tenant_id
)
_agent_memory_role_idx = Index(
    "ix_agent_memory_tenant_role",
    AgentMemoryModel.tenant_id,
    AgentMemoryModel.role,
)
