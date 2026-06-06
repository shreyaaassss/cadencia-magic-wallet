"""Add sla_events table for tracking lifecycle timelines

Revision ID: 036
Revises: 035
Create Date: 2026-06-06

Tracks key lifecycle events (RFQ submitted, first match, session created,
deal agreed, escrow funded, delivery confirmed) for SLA reporting.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "036"
down_revision: Union[str, None] = "035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sla_events",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_name", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("metadata", JSONB(), nullable=True),
    )

    op.execute("""
        ALTER TABLE sla_events ADD CONSTRAINT ck_sla_entity_type
        CHECK (entity_type IN ('RFQ','SESSION','ESCROW'))
    """)

    op.create_index("ix_sla_events_entity", "sla_events", ["entity_type", "entity_id"])
    op.create_index("ix_sla_events_name", "sla_events", ["entity_type", "event_name", sa.text("occurred_at")])


def downgrade() -> None:
    op.drop_index("ix_sla_events_name", table_name="sla_events")
    op.drop_index("ix_sla_events_entity", table_name="sla_events")
    op.drop_table("sla_events")
