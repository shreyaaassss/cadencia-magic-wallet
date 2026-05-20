"""Add opponent_beliefs JSONB column to negotiation_sessions.

BUG-12 FIX: Persists Bayesian opponent beliefs so they survive pod restarts.
Previously beliefs were stored in NeutralEngine._belief_cache (in-memory dict),
which was lost on any process restart, scale event, or crash. A 10-round session
that restarted would classify the opponent from the uniform prior again.

The column is JSONB nullable to be backward-compatible with existing rows.

Revision ID: 016
Revises: 015
Create Date: 2026-05-20
"""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "negotiation_sessions",
        sa.Column("opponent_beliefs", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("negotiation_sessions", "opponent_beliefs")
