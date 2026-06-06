"""Add order_splits table and GDPR soft-delete columns on enterprises

Revision ID: 037
Revises: 036
Create Date: 2026-06-06

order_splits enables splitting a single RFQ across multiple sellers.
GDPR columns enable enterprise data deletion workflow.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "037"
down_revision: Union[str, None] = "036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "order_splits",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("parent_rfq_id", UUID(as_uuid=True), sa.ForeignKey("rfqs.id"), nullable=False),
        sa.Column("child_rfq_id", UUID(as_uuid=True), sa.ForeignKey("rfqs.id"), nullable=True),
        sa.Column("seller_enterprise_id", UUID(as_uuid=True), sa.ForeignKey("enterprises.id"), nullable=False),
        sa.Column("allocated_quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("allocated_amount_inr", sa.Numeric(18, 2), nullable=True),
        sa.Column("status", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.execute("""
        ALTER TABLE order_splits ADD CONSTRAINT ck_order_split_status
        CHECK (status IN ('PENDING','ACTIVE','COMPLETED','CANCELLED'))
    """)

    # GDPR soft-delete columns
    op.add_column("enterprises", sa.Column("gdpr_deletion_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("enterprises", sa.Column("gdpr_deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("enterprises", sa.Column("is_anonymized", sa.Boolean(), server_default="false", nullable=False))


def downgrade() -> None:
    op.drop_column("enterprises", "is_anonymized")
    op.drop_column("enterprises", "gdpr_deleted_at")
    op.drop_column("enterprises", "gdpr_deletion_requested_at")
    op.drop_table("order_splits")
