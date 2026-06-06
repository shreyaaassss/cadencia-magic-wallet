"""Add embedding lifecycle tracking to capability_profiles

Revision ID: ea191f1c2d54
Revises: ea191f1c2d53
Create Date: 2026-06-05

Tracks the state of seller embedding computation so the system can:
  - Show "profile updating" status in the UI
  - Retry failed embeddings
  - Batch-recompute old-version embeddings after composition changes

New columns:
  - embedding_status: ACTIVE | COMPUTING | FAILED | OUTDATED
  - embedding_version: incremented on composition changes
  - last_embedded_at: timestamp of last successful embedding
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "capability_profiles",
        sa.Column(
            "embedding_status",
            sa.String(20),
            server_default="OUTDATED",
            nullable=False,
        ),
    )
    op.add_column(
        "capability_profiles",
        sa.Column(
            "embedding_version",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "capability_profiles",
        sa.Column("last_embedded_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("capability_profiles", "last_embedded_at")
    op.drop_column("capability_profiles", "embedding_version")
    op.drop_column("capability_profiles", "embedding_status")
