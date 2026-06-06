"""Add escrow_milestones table and escrow_contracts columns for partial fulfillment

Revision ID: 035
Revises: 034
Create Date: 2026-06-06

Milestone-based partial release enables sellers to receive payment for
partial deliveries. Each escrow can have multiple milestones, each with
its own release transaction.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "035"
down_revision: Union[str, None] = "034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "escrow_milestones",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("escrow_id", UUID(as_uuid=True), sa.ForeignKey("escrow_contracts.id"), nullable=False),
        sa.Column("milestone_index", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("amount_microalgo", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("release_tx_id", sa.Text(), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("escrow_id", "milestone_index", name="uq_escrow_milestone"),
    )

    op.execute("""
        ALTER TABLE escrow_milestones ADD CONSTRAINT ck_milestone_status
        CHECK (status IN ('PENDING','RELEASED','CANCELLED'))
    """)

    # Additional columns on escrow_contracts for milestone tracking
    op.add_column("escrow_contracts", sa.Column("total_milestones", sa.Integer(), server_default="1", nullable=False))
    op.add_column("escrow_contracts", sa.Column("released_amount_microalgo", sa.BigInteger(), server_default="0", nullable=False))
    op.add_column("escrow_contracts", sa.Column("dispatch_deadline", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("escrow_contracts", "dispatch_deadline")
    op.drop_column("escrow_contracts", "released_amount_microalgo")
    op.drop_column("escrow_contracts", "total_milestones")
    op.drop_table("escrow_milestones")
