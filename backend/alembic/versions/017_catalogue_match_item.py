"""Catalogue product selection fixes: matched_catalogue_item_id + free-form product_category.

Fix 1: Add matched_catalogue_item_id to matches table.
    Records which specific catalogue item was used during matchmaking so the
    negotiation engine can look up the right product instead of always defaulting
    to the cheapest item in the seller's catalogue.

Fix 3: Drop steel-specific product_category CHECK constraint from catalogue_items.
    The previous constraint only allowed steel product codes
    (HR_COIL, CR_COIL, TMT_BAR, ..., CUSTOM). All non-steel industries were
    forced to use 'CUSTOM', making the category field meaningless for filtering.
    product_category is now a free-form VARCHAR(100) — any label is valid.

Revision ID: 017
Revises: 016
Create Date: 2026-05-20
"""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fix 1: Add matched_catalogue_item_id FK column to matches
    op.add_column(
        "matches",
        sa.Column(
            "matched_catalogue_item_id",
            UUID(as_uuid=True),
            sa.ForeignKey("catalogue_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_matches_matched_catalogue_item_id",
        "matches",
        ["matched_catalogue_item_id"],
    )

    # Fix 3: Drop the steel-specific product_category CHECK constraint
    # The column itself remains — only the restrictive enum is removed.
    op.drop_constraint(
        "ck_catalogue_product_category",
        "catalogue_items",
        type_="check",
    )


def downgrade() -> None:
    # Re-add steel enum constraint (rows with non-steel values will fail — data migration needed)
    op.create_check_constraint(
        "ck_catalogue_product_category",
        "catalogue_items",
        "product_category IN ('HR_COIL','CR_COIL','TMT_BAR','WIRE_ROD','BILLET',"
        "'SLAB','PLATE','PIPE','SHEET','ANGLE','CHANNEL','BEAM','CUSTOM')",
    )

    # Remove matched_catalogue_item_id index + column
    op.drop_index("ix_matches_matched_catalogue_item_id", table_name="matches")
    op.drop_column("matches", "matched_catalogue_item_id")
