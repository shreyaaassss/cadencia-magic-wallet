"""Add commercial negotiation fields to catalogue_items

Revision ID: ea191f1c2d53
Revises: ea191f1c2d52
Create Date: 2026-06-05

Adds per-item commercial constraints so the negotiation engine can use
item-level floor prices, discount limits, and payment terms instead of
falling back to uniform AgentProfile defaults.

New columns:
  - floor_price_inr: seller's minimum acceptable price per unit
  - max_discount_pct: maximum negotiable discount (default 10%)
  - negotiation_enabled: toggle AI negotiation per item (default true)
  - approval_threshold_inr: orders above this need human approval
  - validity_end_date: price expiry date
  - payment_terms: per-item payment term preferences (JSONB)
  - region_restrictions: geo-fenced availability rules (JSONB)
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "catalogue_items",
        sa.Column("floor_price_inr", sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        "catalogue_items",
        sa.Column(
            "max_discount_pct",
            sa.Numeric(5, 2),
            server_default="10.0",
            nullable=True,
        ),
    )
    op.add_column(
        "catalogue_items",
        sa.Column(
            "negotiation_enabled",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
    )
    op.add_column(
        "catalogue_items",
        sa.Column("approval_threshold_inr", sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        "catalogue_items",
        sa.Column("validity_end_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "catalogue_items",
        sa.Column(
            "payment_terms",
            JSONB(),
            server_default="[]",
            nullable=True,
        ),
    )
    op.add_column(
        "catalogue_items",
        sa.Column(
            "region_restrictions",
            JSONB(),
            server_default="[]",
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("catalogue_items", "region_restrictions")
    op.drop_column("catalogue_items", "payment_terms")
    op.drop_column("catalogue_items", "validity_end_date")
    op.drop_column("catalogue_items", "approval_threshold_inr")
    op.drop_column("catalogue_items", "negotiation_enabled")
    op.drop_column("catalogue_items", "max_discount_pct")
    op.drop_column("catalogue_items", "floor_price_inr")
