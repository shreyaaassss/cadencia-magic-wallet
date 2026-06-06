"""Add full-text search index on catalogue_items

Revision ID: 026
Revises: 025
Create Date: 2026-06-06

GIN index on a tsvector column enables fast keyword search across
product_name, grade, specification_text, and product_category.
Buyers can now browse/search catalogues directly.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "026"
down_revision: Union[str, None] = "025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create a GIN index on a generated tsvector for full-text search
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_catalogue_items_fulltext
        ON catalogue_items
        USING GIN (
            to_tsvector('english',
                coalesce(product_name, '') || ' ' ||
                coalesce(grade, '') || ' ' ||
                coalesce(specification_text, '') || ' ' ||
                coalesce(product_category, '')
            )
        )
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_catalogue_items_fulltext")
