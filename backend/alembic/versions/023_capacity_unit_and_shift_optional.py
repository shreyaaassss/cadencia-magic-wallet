"""Add capacity_unit to seller_capacity_profiles, make shift_pattern nullable

Revision ID: 023
Revises: 022
Create Date: 2026-06-06

Parameterizes capacity so non-steel sellers (electronics, services) can
express capacity in UNITS/month, PIECES/month, etc. instead of MT.
shift_pattern becomes nullable for trading offices and service providers
who have no manufacturing shifts.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "seller_capacity_profiles",
        sa.Column("capacity_unit", sa.String(20), server_default="MT", nullable=False),
    )
    # Make shift_pattern nullable (trading offices don't have shifts)
    op.alter_column(
        "seller_capacity_profiles",
        "shift_pattern",
        existing_type=sa.String(30),
        nullable=True,
    )
    # Drop the old CHECK constraint that required shift_pattern values
    op.execute("""
        ALTER TABLE seller_capacity_profiles
        DROP CONSTRAINT IF EXISTS ck_shift_pattern
    """)
    # Re-add as a softer constraint: NULL is now allowed
    op.execute("""
        ALTER TABLE seller_capacity_profiles
        ADD CONSTRAINT ck_shift_pattern
        CHECK (shift_pattern IS NULL OR shift_pattern IN (
            'SINGLE_SHIFT','DOUBLE_SHIFT','TRIPLE_SHIFT','CONTINUOUS'
        ))
    """)
    # Backfill existing rows: all existing sellers used MT
    op.execute("""
        UPDATE seller_capacity_profiles
        SET capacity_unit = 'MT'
        WHERE capacity_unit IS NULL OR capacity_unit = ''
    """)


def downgrade() -> None:
    op.drop_column("seller_capacity_profiles", "capacity_unit")
    op.alter_column(
        "seller_capacity_profiles",
        "shift_pattern",
        existing_type=sa.String(30),
        nullable=False,
    )
