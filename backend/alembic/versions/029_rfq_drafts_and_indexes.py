"""Add rfqs.is_draft column and missing performance indexes

Revision ID: 029
Revises: 028
Create Date: 2026-06-06

is_draft enables RFQ draft saving (buyers can save and resume later).
Missing indexes on negotiation_sessions.status and escrow_contracts.status
were identified in the scalability audit (§11.7).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "029"
down_revision: Union[str, None] = "028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rfqs",
        sa.Column("is_draft", sa.Boolean(), server_default="false", nullable=False),
    )

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_negotiation_sessions_status_v2
        ON negotiation_sessions(status)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_escrow_contracts_status
        ON escrow_contracts(status)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_escrow_contracts_status")
    op.execute("DROP INDEX IF EXISTS ix_negotiation_sessions_status_v2")
    op.drop_column("rfqs", "is_draft")
