"""Housekeeping indexes for new tables

Revision ID: 038
Revises: 037
Create Date: 2026-06-06

Performance indexes for tables created in migrations 027-037.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "038"
down_revision: Union[str, None] = "037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_wallet_ledger_tx_id ON wallet_ledger(tx_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_decision_audit_session ON agent_decision_audit(session_id, round_number)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_procurement_documents_po_number ON procurement_documents(po_number)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_order_splits_parent ON order_splits(parent_rfq_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_escrow_milestones_escrow ON escrow_milestones(escrow_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_escrow_milestones_escrow")
    op.execute("DROP INDEX IF EXISTS ix_order_splits_parent")
    op.execute("DROP INDEX IF EXISTS ix_procurement_documents_po_number")
    op.execute("DROP INDEX IF EXISTS ix_agent_decision_audit_session")
    op.execute("DROP INDEX IF EXISTS ix_wallet_ledger_tx_id")
