"""Add seller_ratings table for post-delivery feedback

Revision ID: 028
Revises: 027
Create Date: 2026-06-06

Buyers can rate sellers after escrow is RELEASED. One rating per escrow.
Ratings include overall 1-5 stars, delivery quality, communication quality,
and optional text feedback.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "028"
down_revision: Union[str, None] = "027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "seller_ratings",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("escrow_id", UUID(as_uuid=True), sa.ForeignKey("escrow_contracts.id"), nullable=False, unique=True),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("negotiation_sessions.id"), nullable=True),
        sa.Column("buyer_enterprise_id", UUID(as_uuid=True), sa.ForeignKey("enterprises.id"), nullable=False),
        sa.Column("seller_enterprise_id", UUID(as_uuid=True), sa.ForeignKey("enterprises.id"), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("feedback_text", sa.Text(), nullable=True),
        sa.Column("delivery_quality", sa.Integer(), nullable=True),
        sa.Column("communication_quality", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.execute("""
        ALTER TABLE seller_ratings ADD CONSTRAINT ck_seller_ratings_rating
        CHECK (rating BETWEEN 1 AND 5)
    """)

    op.execute("""
        ALTER TABLE seller_ratings ADD CONSTRAINT ck_seller_ratings_delivery
        CHECK (delivery_quality IS NULL OR delivery_quality BETWEEN 1 AND 5)
    """)

    op.execute("""
        ALTER TABLE seller_ratings ADD CONSTRAINT ck_seller_ratings_communication
        CHECK (communication_quality IS NULL OR communication_quality BETWEEN 1 AND 5)
    """)

    op.create_index("ix_seller_ratings_seller", "seller_ratings", ["seller_enterprise_id", sa.text("created_at DESC")])
    op.create_index("ix_seller_ratings_buyer", "seller_ratings", ["buyer_enterprise_id"])


def downgrade() -> None:
    op.drop_index("ix_seller_ratings_buyer", table_name="seller_ratings")
    op.drop_index("ix_seller_ratings_seller", table_name="seller_ratings")
    op.drop_table("seller_ratings")
