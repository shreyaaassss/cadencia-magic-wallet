"""Add wallet_ledger table and users.onboarding_checklist column

Revision ID: 027
Revises: 026
Create Date: 2026-06-06

wallet_ledger provides event-sourced tracking of all ALGO movements
(escrow fund/release/refund, x402 payments, onramp deposits) so
historical balance can be reconstructed without blockchain queries.

users.onboarding_checklist tracks first-time user guidance progress.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "027"
down_revision: Union[str, None] = "026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wallet_ledger",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("enterprise_id", UUID(as_uuid=True), sa.ForeignKey("enterprises.id"), nullable=False),
        sa.Column("algorand_address", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("amount_microalgo", sa.BigInteger(), nullable=False),
        sa.Column("tx_id", sa.Text(), nullable=True),
        sa.Column("reference_id", UUID(as_uuid=True), nullable=True),
        sa.Column("reference_type", sa.Text(), nullable=True),
        sa.Column("balance_before_microalgo", sa.BigInteger(), nullable=True),
        sa.Column("balance_after_microalgo", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.execute("""
        ALTER TABLE wallet_ledger ADD CONSTRAINT ck_wallet_ledger_event_type
        CHECK (event_type IN (
            'ESCROW_FUNDED','ESCROW_RELEASED','ESCROW_REFUNDED',
            'X402_PAYMENT','ONRAMP_DEPOSIT','WALLET_LINKED','WALLET_UNLINKED'
        ))
    """)

    op.execute("""
        ALTER TABLE wallet_ledger ADD CONSTRAINT ck_wallet_ledger_direction
        CHECK (direction IN ('DEBIT','CREDIT'))
    """)

    op.create_index("ix_wallet_ledger_enterprise_created", "wallet_ledger", ["enterprise_id", sa.text("created_at DESC")])
    op.create_index("ix_wallet_ledger_address_created", "wallet_ledger", ["algorand_address", sa.text("created_at DESC")])

    # Onboarding checklist on users table
    op.add_column(
        "users",
        sa.Column("onboarding_checklist", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "onboarding_checklist")
    op.drop_index("ix_wallet_ledger_address_created", table_name="wallet_ledger")
    op.drop_index("ix_wallet_ledger_enterprise_created", table_name="wallet_ledger")
    op.drop_table("wallet_ledger")
