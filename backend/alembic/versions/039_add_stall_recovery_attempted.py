"""Add stall_recovery_attempted column to negotiation_sessions

Revision ID: 039
Revises: 038
Create Date: 2026-06-06

CRITICAL FIX: stall_recovery_attempted was only stored in memory,
resetting to False on every session reload from DB. This caused
infinite stall recovery loops where the engine never terminated.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "039"
down_revision: Union[str, None] = "038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "negotiation_sessions",
        sa.Column("stall_recovery_attempted", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("negotiation_sessions", "stall_recovery_attempted")
