"""Add agent_decision_audit table and offers.agent_reasoning_chain

Revision ID: 031
Revises: 030
Create Date: 2026-06-06

Tamper-evident per-turn audit log for AI agent decisions.
Each row records the strategy selected, reasoning chain, opponent
classification, and a hash-chain for integrity verification.

offers.agent_reasoning_chain stores the structured JSON reasoning
(complementing the free-text agent_reasoning field).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "031"
down_revision: Union[str, None] = "030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_decision_audit",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("negotiation_sessions.id"), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("enterprise_id", UUID(as_uuid=True), sa.ForeignKey("enterprises.id"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("strategy_selected", sa.Text(), nullable=True),
        sa.Column("reasoning_chain", JSONB(), nullable=True),
        sa.Column("opponent_classification", sa.Text(), nullable=True),
        sa.Column("flexibility_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("prev_hash", sa.Text(), nullable=True),
        sa.Column("entry_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.execute("""
        ALTER TABLE agent_decision_audit ADD CONSTRAINT ck_agent_audit_role
        CHECK (role IN ('buyer','seller'))
    """)

    op.create_index("ix_agent_decision_audit_session_round", "agent_decision_audit", ["session_id", "round_number"])
    op.create_index("ix_agent_decision_audit_enterprise", "agent_decision_audit", ["enterprise_id", sa.text("created_at DESC")])

    # Structured reasoning chain on offers (complement to free-text agent_reasoning)
    op.add_column(
        "offers",
        sa.Column("agent_reasoning_chain", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("offers", "agent_reasoning_chain")
    op.drop_index("ix_agent_decision_audit_enterprise", table_name="agent_decision_audit")
    op.drop_index("ix_agent_decision_audit_session_round", table_name="agent_decision_audit")
    op.drop_table("agent_decision_audit")
