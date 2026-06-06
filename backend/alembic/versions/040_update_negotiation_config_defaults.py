"""Update negotiation_config DEFAULT row to match engine fixes

Revision ID: 040
Revises: 039
Create Date: 2026-06-07

Migration 030 seeded the DEFAULT config with max_rounds=20 and
convergence_tolerance=0.02. The engine fixes require 15 rounds and
3.5% tolerance. This updates the existing DB row so the config
service returns correct values.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "040"
down_revision: Union[str, None] = "039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE negotiation_config
        SET max_rounds = 15,
            convergence_tolerance = 0.035
        WHERE config_name = 'DEFAULT'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE negotiation_config
        SET max_rounds = 20,
            convergence_tolerance = 0.02
        WHERE config_name = 'DEFAULT'
    """)
