"""Add SELLER_ANCHOR and BUYER_RESPONSE to negotiation session status constraint.

FSM flipped: seller now anchors first (catalog price), buyer responds.
Legacy BUYER_ANCHOR / SELLER_RESPONSE values retained for in-flight sessions.

Revision ID: 015
Revises: 014
Create Date: 2026-05-19
"""

from typing import Union

from alembic import op

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the old CHECK constraint and recreate with the two new status values.
    # PostgreSQL requires DROP + ADD; the constraint name must match exactly.
    op.execute(
        "ALTER TABLE negotiation_sessions "
        "DROP CONSTRAINT IF EXISTS ck_negotiation_sessions_status"
    )
    op.execute(
        "ALTER TABLE negotiation_sessions ADD CONSTRAINT ck_negotiation_sessions_status "
        "CHECK (status IN ("
        "'ACTIVE','AGREED','FAILED','EXPIRED','HUMAN_REVIEW',"
        "'INIT','SELLER_ANCHOR','BUYER_RESPONSE',"
        "'BUYER_ANCHOR','SELLER_RESPONSE','ROUND_LOOP',"
        "'WALK_AWAY','STALLED','TIMEOUT','POLICY_BREACH'"
        "))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE negotiation_sessions "
        "DROP CONSTRAINT IF EXISTS ck_negotiation_sessions_status"
    )
    op.execute(
        "ALTER TABLE negotiation_sessions ADD CONSTRAINT ck_negotiation_sessions_status "
        "CHECK (status IN ("
        "'ACTIVE','AGREED','FAILED','EXPIRED','HUMAN_REVIEW',"
        "'INIT','BUYER_ANCHOR','SELLER_RESPONSE','ROUND_LOOP',"
        "'WALK_AWAY','STALLED','TIMEOUT','POLICY_BREACH'"
        "))"
    )
