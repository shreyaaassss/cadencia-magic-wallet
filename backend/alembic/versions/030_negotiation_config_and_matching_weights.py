"""Add negotiation_config table and industry matching_weights

Revision ID: 030
Revises: 029
Create Date: 2026-06-06

negotiation_config replaces 20+ hardcoded constants in strategy.py
with DB-backed, per-industry configurable parameters.

industry_taxonomies.matching_weights enables per-industry composite
scoring weights (e.g. capacity matters more for steel, certification
matters more for electronics).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "030"
down_revision: Union[str, None] = "029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "negotiation_config",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("config_name", sa.Text(), unique=True, nullable=False),
        sa.Column("max_rounds", sa.Integer(), server_default="20", nullable=False),
        sa.Column("stall_rounds", sa.Integer(), server_default="3", nullable=False),
        sa.Column("convergence_tolerance", sa.Numeric(5, 4), server_default="0.02", nullable=False),
        sa.Column("session_ttl_hours", sa.Integer(), server_default="24", nullable=False),
        sa.Column("hardball_flexibility_threshold", sa.Numeric(4, 3), server_default="0.15", nullable=True),
        sa.Column("walkaway_pct_below_floor", sa.Numeric(4, 3), server_default="0.10", nullable=True),
        sa.Column("concessive_step_pct", sa.Numeric(4, 3), server_default="0.035", nullable=True),
        sa.Column("conservative_step_pct", sa.Numeric(4, 3), server_default="0.015", nullable=True),
        sa.Column("opponent_modifiers", JSONB(), server_default='{"cooperative":0.85,"strategic":1.0,"stubborn":1.2,"bluffing":0.7}', nullable=True),
        sa.Column("urgency_max_rounds", JSONB(), server_default='{"CRITICAL":3,"HIGH":5,"MODERATE":8,"LOW":15}', nullable=True),
        sa.Column("applies_to_industries", sa.ARRAY(sa.Text()), server_default="{}", nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # Seed DEFAULT config with current hardcoded values
    op.execute("""
        INSERT INTO negotiation_config (config_name, max_rounds, stall_rounds, convergence_tolerance,
            session_ttl_hours, hardball_flexibility_threshold, walkaway_pct_below_floor,
            concessive_step_pct, conservative_step_pct)
        VALUES ('DEFAULT', 20, 3, 0.02, 24, 0.15, 0.10, 0.035, 0.015)
        ON CONFLICT (config_name) DO NOTHING
    """)

    # Add matching_weights to industry_taxonomies for per-industry scoring
    op.add_column(
        "industry_taxonomies",
        sa.Column(
            "matching_weights",
            JSONB(),
            server_default='{"semantic":0.25,"delivery":0.20,"capacity":0.15,"price":0.15,"proximity":0.10,"payment":0.10,"certification":0.05}',
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("industry_taxonomies", "matching_weights")
    op.drop_table("negotiation_config")
