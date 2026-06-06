"""Add catalogue versioning columns and change_log table

Revision ID: 024
Revises: 023
Create Date: 2026-06-06

Adds version tracking to catalogue_items and a change audit trail so
sellers have price history and can roll back accidental changes.
Also adds catalogue_items.status for the DRAFT→ACTIVE lifecycle.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "024"
down_revision: Union[str, None] = "023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Catalogue versioning columns
    op.add_column(
        "catalogue_items",
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "catalogue_items",
        sa.Column(
            "status",
            sa.String(20),
            server_default="ACTIVE",
            nullable=False,
        ),
    )
    op.add_column(
        "catalogue_items",
        sa.Column("previous_version_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "catalogue_items",
        sa.Column("price_updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Change log table
    op.create_table(
        "catalogue_change_log",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("catalogue_item_id", UUID(as_uuid=True), sa.ForeignKey("catalogue_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_name", sa.String(50), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("changed_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_catalogue_change_log_item_id", "catalogue_change_log", ["catalogue_item_id"])


def downgrade() -> None:
    op.drop_index("ix_catalogue_change_log_item_id", table_name="catalogue_change_log")
    op.drop_table("catalogue_change_log")
    op.drop_column("catalogue_items", "price_updated_at")
    op.drop_column("catalogue_items", "previous_version_id")
    op.drop_column("catalogue_items", "status")
    op.drop_column("catalogue_items", "version")
