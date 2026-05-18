"""Add x402_payments table for Algorand payment tracking.

New table:
  - x402_payments: records every confirmed Algorand payment made via the x402
    HTTP payment protocol for gated marketplace endpoints.

Revision ID: 014
Revises: ea191f1c2d52
Create Date: 2026-05-18
"""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "014"
down_revision: Union[str, None] = "ea191f1c2d52"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "x402_payments",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("buyer_address", sa.Text(), nullable=False),
        sa.Column("tx_id", sa.Text(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("resource_url", sa.Text(), nullable=False),
        sa.Column("nonce", sa.Text(), nullable=False),
        sa.Column("confirmed_round", sa.BigInteger(), nullable=True),
        sa.Column(
            "paid_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint("tx_id", name="uq_x402_payments_tx_id"),
        sa.UniqueConstraint("nonce", name="uq_x402_payments_nonce"),
    )

    op.create_index(
        "ix_x402_payments_buyer_address",
        "x402_payments",
        ["buyer_address"],
    )
    op.create_index(
        "ix_x402_payments_nonce",
        "x402_payments",
        ["nonce"],
    )


def downgrade() -> None:
    op.drop_index("ix_x402_payments_nonce", table_name="x402_payments")
    op.drop_index("ix_x402_payments_buyer_address", table_name="x402_payments")
    op.drop_table("x402_payments")
