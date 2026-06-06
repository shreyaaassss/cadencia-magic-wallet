"""Add approved_vendor_lists table

Revision ID: 034
Revises: 033
Create Date: 2026-06-06

Buyer-managed approved vendor lists for preferred seller management.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "034"
down_revision: Union[str, None] = "033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "approved_vendor_lists",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("buyer_enterprise_id", UUID(as_uuid=True), sa.ForeignKey("enterprises.id"), nullable=False),
        sa.Column("seller_enterprise_id", UUID(as_uuid=True), sa.ForeignKey("enterprises.id"), nullable=False),
        sa.Column("status", sa.Text(), server_default="ACTIVE", nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("buyer_enterprise_id", "seller_enterprise_id", name="uq_approved_vendor"),
    )

    op.execute("""
        ALTER TABLE approved_vendor_lists ADD CONSTRAINT ck_vendor_status
        CHECK (status IN ('ACTIVE','SUSPENDED','REMOVED'))
    """)

    op.create_index("ix_avl_buyer_status", "approved_vendor_lists", ["buyer_enterprise_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_avl_buyer_status", table_name="approved_vendor_lists")
    op.drop_table("approved_vendor_lists")
