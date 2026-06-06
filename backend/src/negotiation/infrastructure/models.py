"""
SQLAlchemy ORM models for the negotiation bounded context.

Tables: negotiation_sessions, offers, agent_profiles, industry_playbooks
context.md §11 — Database Schema.
"""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
            "'WALK_AWAY','STALLED','TIMEOUT','POLICY_BREACH','CLOSED_BY_BUYER')",
            name="ck_negotiation_sessions_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    rfq_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rfqs.id", ondelete="SET NULL"), nullable=False
    )
    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("matches.id", ondelete="SET NULL"), nullable=False
    )
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
    deal_quality_score: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    product_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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
    # Phase 6: distinguish document chunks from negotiation record chunks
    record_type: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="DOCUMENT"
    )
    # Phase 6: link chunks back to their canonical NegotiationRecord
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
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


# ── Phase 6: Negotiation Memory Schema ───────────────────────────────────────


class NegotiationRecordModel(Base):
    """
    Canonical storage for all negotiation data regardless of source.

    record_type distinguishes PLATFORM_SESSION | AGENT_CONVERSATION | HISTORICAL_IMPORT.
    embedding enables semantic search via pgvector HNSW.
    All queries must include enterprise_id for tenant isolation.
    """

    __tablename__ = "negotiation_records"
    __table_args__ = (
        CheckConstraint(
            "record_type IN ('PLATFORM_SESSION','AGENT_CONVERSATION','HISTORICAL_IMPORT')",
            name="ck_negotiation_records_record_type",
        ),
        CheckConstraint(
            "outcome IN ('AGREED','REJECTED','STALLED','EXPIRED','UNKNOWN')",
            name="ck_negotiation_records_outcome",
        ),
        CheckConstraint(
            "enterprise_role IN ('buyer','seller')",
            name="ck_negotiation_records_enterprise_role",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    record_type: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="PLATFORM_SESSION"
    )
    source_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("negotiation_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    counterparty_enterprise_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    enterprise_role: Mapped[str] = mapped_column(String(10), nullable=False)

    # Product context
    product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hsn_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    industry_vertical: Mapped[str | None] = mapped_column(String(100), nullable=True)
    quantity: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    quantity_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Outcome
    outcome: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="UNKNOWN"
    )
    agreed_price_inr: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    initial_ask_price_inr: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    initial_bid_price_inr: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    final_discount_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)

    # Behavioral metrics
    total_rounds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_hours: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    buyer_avg_concession_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    seller_avg_concession_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    buyer_style: Mapped[str | None] = mapped_column(String(30), nullable=True)
    seller_style: Mapped[str | None] = mapped_column(String(30), nullable=True)
    deal_quality_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)

    # Terms
    agreed_terms: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(String(200), nullable=True)
    delivery_window_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Raw data
    offer_sequence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    conversation_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_source_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Metadata
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    confidence_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    source_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    normalized_at: Mapped[str | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retention_expires_at: Mapped[str | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Embedding
    embedding = mapped_column(Vector(1536), nullable=True)

    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


_nr_enterprise_idx = Index(
    "ix_negotiation_records_enterprise_id", NegotiationRecordModel.enterprise_id
)
_nr_enterprise_role_idx = Index(
    "ix_negotiation_records_enterprise_role",
    NegotiationRecordModel.enterprise_id,
    NegotiationRecordModel.enterprise_role,
)
_nr_enterprise_outcome_idx = Index(
    "ix_negotiation_records_enterprise_outcome",
    NegotiationRecordModel.enterprise_id,
    NegotiationRecordModel.outcome,
)
_nr_product_idx = Index(
    "ix_negotiation_records_product",
    NegotiationRecordModel.enterprise_id,
    NegotiationRecordModel.product_category,
    NegotiationRecordModel.hsn_code,
)
_nr_session_idx = Index(
    "ix_negotiation_records_session",
    NegotiationRecordModel.source_session_id,
)


class NegotiationInsightModel(Base):
    """
    Per-enterprise aggregate intelligence computed from NegotiationRecords.

    One row per enterprise — upserted after each session completion.
    """

    __tablename__ = "negotiation_insights"
    __table_args__ = (
        UniqueConstraint("enterprise_id", name="uq_negotiation_insights_enterprise_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False, unique=True
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False, server_default="both")
    total_negotiations: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    success_rate: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, server_default="0"
    )
    avg_rounds_to_close: Mapped[float] = mapped_column(
        Numeric(6, 2), nullable=False, server_default="0"
    )
    avg_discount_achieved_pct: Mapped[float] = mapped_column(
        Numeric(8, 4), nullable=False, server_default="0"
    )
    avg_deal_quality: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, server_default="0"
    )
    dominant_style: Mapped[str | None] = mapped_column(String(30), nullable=True)
    style_distribution: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    top_products: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    top_verticals: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    counterparty_stats: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    seasonal_patterns: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    strategy_recommendations: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_computed_at: Mapped[str | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class NegotiationConfigModel(Base):
    """DB-backed negotiation configuration (migration 030)."""

    __tablename__ = "negotiation_config"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    config_name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    max_rounds: Mapped[int] = mapped_column(Integer, server_default="20", nullable=False)
    stall_rounds: Mapped[int] = mapped_column(Integer, server_default="3", nullable=False)
    convergence_tolerance: Mapped[float] = mapped_column(
        Numeric(5, 4), server_default="0.02", nullable=False
    )
    session_ttl_hours: Mapped[int] = mapped_column(Integer, server_default="24", nullable=False)
    hardball_flexibility_threshold: Mapped[float | None] = mapped_column(
        Numeric(4, 3), server_default="0.15", nullable=True
    )
    walkaway_pct_below_floor: Mapped[float | None] = mapped_column(
        Numeric(4, 3), server_default="0.10", nullable=True
    )
    concessive_step_pct: Mapped[float | None] = mapped_column(
        Numeric(4, 3), server_default="0.035", nullable=True
    )
    conservative_step_pct: Mapped[float | None] = mapped_column(
        Numeric(4, 3), server_default="0.015", nullable=True
    )
    opponent_modifiers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    urgency_max_rounds: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    applies_to_industries: Mapped[list | None] = mapped_column(
        ARRAY(String), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentDecisionAuditModel(Base):
    """Per-turn tamper-evident agent decision log (migration 031)."""

    __tablename__ = "agent_decision_audit"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("negotiation_sessions.id"), nullable=False
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_selected: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning_chain: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    opponent_classification: Mapped[str | None] = mapped_column(Text, nullable=True)
    flexibility_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    prev_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
