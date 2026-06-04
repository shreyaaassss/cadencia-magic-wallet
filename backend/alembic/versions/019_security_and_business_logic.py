"""019 security and business logic fixes

Revision ID: 019
Revises: 018
Create Date: 2026-06-04

Issues covered:
  #13 — Add CLOSED_BY_BUYER to negotiation session status
  #14 — Add PARSE_FAILED to RFQ status + parse_error column
  #25 — Add escrow approval_deadline column
  #26 — Add enterprises.algorand_wallet_changed_at column

All changes are additive — zero breaking changes to existing data.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Issue #13: Add CLOSED_BY_BUYER to session status CHECK ---
    # Use raw SQL because the actual constraint name in DB is
    # 'ck_negotiation_sessions_status' (not auto-prefixed).
    op.execute("ALTER TABLE negotiation_sessions DROP CONSTRAINT IF EXISTS ck_negotiation_sessions_status")
    op.execute(
        "ALTER TABLE negotiation_sessions ADD CONSTRAINT ck_negotiation_sessions_status "
        "CHECK (status IN ('ACTIVE','AGREED','FAILED','EXPIRED','HUMAN_REVIEW',"
        "'INIT','SELLER_ANCHOR','BUYER_RESPONSE',"
        "'BUYER_ANCHOR','SELLER_RESPONSE','ROUND_LOOP',"
        "'WALK_AWAY','STALLED','TIMEOUT','POLICY_BREACH','CLOSED_BY_BUYER'))"
    )

    # --- Issue #14: Add PARSE_FAILED + EXPIRED to RFQ status + parse_error column ---
    # DB has doubled prefix: 'ck_rfqs_ck_rfqs_status'
    op.execute("ALTER TABLE rfqs DROP CONSTRAINT IF EXISTS ck_rfqs_status")
    op.execute("ALTER TABLE rfqs DROP CONSTRAINT IF EXISTS ck_rfqs_ck_rfqs_status")
    op.execute(
        "ALTER TABLE rfqs ADD CONSTRAINT ck_rfqs_status "
        "CHECK (status IN ('DRAFT','PARSE_FAILED','PARSED','MATCHED',"
        "'NEGOTIATING','CONFIRMED','SETTLED','EXPIRED'))"
    )
    op.add_column("rfqs", sa.Column("parse_error", sa.Text(), nullable=True))

    # --- Issue #25: Escrow approval deadline ---
    op.add_column(
        "escrow_contracts",
        sa.Column("approval_deadline", sa.DateTime(timezone=True), nullable=True),
    )

    # --- Issue #26: Wallet change audit timestamp ---
    op.add_column(
        "enterprises",
        sa.Column(
            "algorand_wallet_changed_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    # Issue #26
    op.drop_column("enterprises", "algorand_wallet_changed_at")

    # Issue #25
    op.drop_column("escrow_contracts", "approval_deadline")

    # Issue #14
    op.drop_column("rfqs", "parse_error")
    op.execute("ALTER TABLE rfqs DROP CONSTRAINT IF EXISTS ck_rfqs_status")
    op.execute(
        "ALTER TABLE rfqs ADD CONSTRAINT ck_rfqs_status "
        "CHECK (status IN ('DRAFT','PARSED','MATCHED','NEGOTIATING','CONFIRMED','SETTLED'))"
    )

    # Issue #13
    op.execute("ALTER TABLE negotiation_sessions DROP CONSTRAINT IF EXISTS ck_negotiation_sessions_status")
    op.execute(
        "ALTER TABLE negotiation_sessions ADD CONSTRAINT ck_negotiation_sessions_status "
        "CHECK (status IN ('ACTIVE','AGREED','FAILED','EXPIRED','HUMAN_REVIEW',"
        "'INIT','SELLER_ANCHOR','BUYER_RESPONSE',"
        "'BUYER_ANCHOR','SELLER_RESPONSE','ROUND_LOOP',"
        "'WALK_AWAY','STALLED','TIMEOUT','POLICY_BREACH'))"
    )
