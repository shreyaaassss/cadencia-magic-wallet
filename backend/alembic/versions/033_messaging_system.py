"""Add conversation_threads and messages tables

Revision ID: 033
Revises: 032
Create Date: 2026-06-06

Buyer-seller messaging system scoped by deal (RFQ/session/escrow).
Post-match only — prevents cold spam. All messages auditable.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "033"
down_revision: Union[str, None] = "032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversation_threads",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("thread_type", sa.Text(), nullable=False),
        sa.Column("rfq_id", UUID(as_uuid=True), sa.ForeignKey("rfqs.id"), nullable=True),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("negotiation_sessions.id"), nullable=True),
        sa.Column("escrow_id", UUID(as_uuid=True), sa.ForeignKey("escrow_contracts.id"), nullable=True),
        sa.Column("buyer_enterprise_id", UUID(as_uuid=True), sa.ForeignKey("enterprises.id"), nullable=False),
        sa.Column("seller_enterprise_id", UUID(as_uuid=True), sa.ForeignKey("enterprises.id"), nullable=False),
        sa.Column("status", sa.Text(), server_default="OPEN", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.execute("""
        ALTER TABLE conversation_threads ADD CONSTRAINT ck_thread_type
        CHECK (thread_type IN ('RFQ_CLARIFICATION','NEGOTIATION_QUERY','DISPUTE','GENERAL'))
    """)

    op.execute("""
        ALTER TABLE conversation_threads ADD CONSTRAINT ck_thread_status
        CHECK (status IN ('OPEN','CLOSED','ESCALATED'))
    """)

    op.create_index("ix_threads_buyer", "conversation_threads", ["buyer_enterprise_id"])
    op.create_index("ix_threads_seller", "conversation_threads", ["seller_enterprise_id"])

    op.create_table(
        "messages",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("thread_id", UUID(as_uuid=True), sa.ForeignKey("conversation_threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_enterprise_id", UUID(as_uuid=True), sa.ForeignKey("enterprises.id"), nullable=False),
        sa.Column("sender_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("attachments", JSONB(), server_default="[]", nullable=True),
        sa.Column("is_system_generated", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("read_by", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_index("ix_messages_thread_created", "messages", ["thread_id", sa.text("created_at")])


def downgrade() -> None:
    op.drop_index("ix_messages_thread_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_threads_seller", table_name="conversation_threads")
    op.drop_index("ix_threads_buyer", table_name="conversation_threads")
    op.drop_table("conversation_threads")
