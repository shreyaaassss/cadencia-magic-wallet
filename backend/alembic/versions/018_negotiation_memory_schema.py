"""018 negotiation memory schema

Revision ID: 018
Revises: ea191f1c2d52
Create Date: 2026-05-28

Adds:
  - negotiation_records table (canonical schema for all negotiation memory)
  - negotiation_insights table (per-enterprise aggregate intelligence)
  - agent_memory: record_type VARCHAR(30) + source_record_id UUID columns

All changes are additive — zero breaking changes to existing data.
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Create negotiation_records ─────────────────────────────────────────────
    op.create_table(
        "negotiation_records",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("enterprise_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "record_type",
            sa.String(30),
            nullable=False,
            server_default="PLATFORM_SESSION",
        ),
        sa.Column("source_session_id", UUID(as_uuid=True), nullable=True),
        sa.Column("counterparty_enterprise_id", UUID(as_uuid=True), nullable=True),
        sa.Column("enterprise_role", sa.String(10), nullable=False),

        # Product context
        sa.Column("product_name", sa.String(255), nullable=True),
        sa.Column("product_category", sa.String(100), nullable=True),
        sa.Column("hsn_code", sa.String(8), nullable=True),
        sa.Column("industry_vertical", sa.String(100), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("quantity_unit", sa.String(20), nullable=True),

        # Outcome
        sa.Column("outcome", sa.String(20), nullable=False, server_default="UNKNOWN"),
        sa.Column("agreed_price_inr", sa.Numeric(18, 4), nullable=True),
        sa.Column("initial_ask_price_inr", sa.Numeric(18, 4), nullable=True),
        sa.Column("initial_bid_price_inr", sa.Numeric(18, 4), nullable=True),
        sa.Column("final_discount_pct", sa.Numeric(8, 4), nullable=True),

        # Behavioral metrics
        sa.Column("total_rounds", sa.Integer, nullable=True),
        sa.Column("duration_hours", sa.Numeric(10, 2), nullable=True),
        sa.Column("buyer_avg_concession_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("seller_avg_concession_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("buyer_style", sa.String(30), nullable=True),
        sa.Column("seller_style", sa.String(30), nullable=True),
        sa.Column("deal_quality_score", sa.Numeric(5, 4), nullable=True),

        # Terms
        sa.Column("agreed_terms", JSONB, nullable=True),
        sa.Column("payment_terms", sa.String(200), nullable=True),
        sa.Column("delivery_window_days", sa.Integer, nullable=True),

        # Raw data
        sa.Column("offer_sequence", JSONB, nullable=True),
        sa.Column("conversation_summary", sa.Text, nullable=True),
        sa.Column("raw_source_text", sa.Text, nullable=True),

        # Metadata
        sa.Column("schema_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("confidence_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("source_filename", sa.String(500), nullable=True),
        sa.Column("normalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),

        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),

        # Constraints
        sa.ForeignKeyConstraint(["enterprise_id"], ["enterprises.id"]),
        sa.ForeignKeyConstraint(
            ["source_session_id"],
            ["negotiation_sessions.id"],
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "record_type IN ('PLATFORM_SESSION','AGENT_CONVERSATION','HISTORICAL_IMPORT')",
            name="ck_negotiation_records_record_type",
        ),
        sa.CheckConstraint(
            "outcome IN ('AGREED','REJECTED','STALLED','EXPIRED','UNKNOWN')",
            name="ck_negotiation_records_outcome",
        ),
        sa.CheckConstraint(
            "enterprise_role IN ('buyer','seller')",
            name="ck_negotiation_records_enterprise_role",
        ),
    )

    # ── Add embedding column using raw SQL (pgvector type) ────────────────────
    op.execute("ALTER TABLE negotiation_records ADD COLUMN embedding vector(1536)")

    # ── Indexes on negotiation_records ────────────────────────────────────────
    op.create_index(
        "ix_negotiation_records_enterprise_id",
        "negotiation_records",
        ["enterprise_id"],
    )
    op.create_index(
        "ix_negotiation_records_enterprise_role",
        "negotiation_records",
        ["enterprise_id", "enterprise_role"],
    )
    op.create_index(
        "ix_negotiation_records_enterprise_outcome",
        "negotiation_records",
        ["enterprise_id", "outcome"],
    )
    op.create_index(
        "ix_negotiation_records_product",
        "negotiation_records",
        ["enterprise_id", "product_category", "hsn_code"],
    )
    op.create_index(
        "ix_negotiation_records_session",
        "negotiation_records",
        ["source_session_id"],
    )
    # Partial index for retention cleanup job
    op.execute(
        "CREATE INDEX ix_negotiation_records_retention ON negotiation_records "
        "(retention_expires_at) WHERE retention_expires_at IS NOT NULL"
    )
    # HNSW vector index (all similarity queries filter by enterprise_id at query time)
    op.execute(
        "CREATE INDEX ix_negotiation_records_embedding ON negotiation_records "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )

    # ── Create negotiation_insights ───────────────────────────────────────────
    op.create_table(
        "negotiation_insights",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("enterprise_id", UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("role", sa.String(10), nullable=False, server_default="both"),
        sa.Column("total_negotiations", sa.Integer, nullable=False, server_default="0"),
        sa.Column("success_rate", sa.Numeric(5, 4), nullable=False, server_default="0"),
        sa.Column(
            "avg_rounds_to_close", sa.Numeric(6, 2), nullable=False, server_default="0"
        ),
        sa.Column(
            "avg_discount_achieved_pct",
            sa.Numeric(8, 4),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "avg_deal_quality", sa.Numeric(5, 4), nullable=False, server_default="0"
        ),
        sa.Column("dominant_style", sa.String(30), nullable=True),
        sa.Column("style_distribution", JSONB, nullable=True),
        sa.Column("top_products", JSONB, nullable=True),
        sa.Column("top_verticals", JSONB, nullable=True),
        sa.Column("counterparty_stats", JSONB, nullable=True),
        sa.Column("seasonal_patterns", JSONB, nullable=True),
        sa.Column("strategy_recommendations", JSONB, nullable=True),
        sa.Column("last_computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("schema_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["enterprise_id"], ["enterprises.id"]),
        sa.UniqueConstraint("enterprise_id", name="uq_negotiation_insights_enterprise_id"),
    )

    # ── Alter agent_memory — add record_type + source_record_id ──────────────
    op.add_column(
        "agent_memory",
        sa.Column(
            "record_type",
            sa.String(30),
            nullable=False,
            server_default="DOCUMENT",
        ),
    )
    op.add_column(
        "agent_memory",
        sa.Column("source_record_id", UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    # Remove columns from agent_memory
    op.drop_column("agent_memory", "source_record_id")
    op.drop_column("agent_memory", "record_type")

    # Drop negotiation_insights
    op.drop_table("negotiation_insights")

    # Drop indexes on negotiation_records
    op.execute("DROP INDEX IF EXISTS ix_negotiation_records_embedding")
    op.execute("DROP INDEX IF EXISTS ix_negotiation_records_retention")
    op.drop_index("ix_negotiation_records_session", table_name="negotiation_records")
    op.drop_index("ix_negotiation_records_product", table_name="negotiation_records")
    op.drop_index(
        "ix_negotiation_records_enterprise_outcome", table_name="negotiation_records"
    )
    op.drop_index(
        "ix_negotiation_records_enterprise_role", table_name="negotiation_records"
    )
    op.drop_index(
        "ix_negotiation_records_enterprise_id", table_name="negotiation_records"
    )

    # Drop negotiation_records
    op.drop_table("negotiation_records")
