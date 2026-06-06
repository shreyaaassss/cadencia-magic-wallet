"""Add procurement_documents and procurement_document_amendments tables

Revision ID: 032
Revises: 031
Create Date: 2026-06-06

Post-negotiation procurement document (PO) generation and seller
acceptance workflow. Documents have versioning and amendment tracking.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "032"
down_revision: Union[str, None] = "031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "procurement_documents",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("po_number", sa.Text(), unique=True, nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("negotiation_sessions.id"), nullable=False),
        sa.Column("escrow_id", UUID(as_uuid=True), sa.ForeignKey("escrow_contracts.id"), nullable=True),
        sa.Column("buyer_enterprise_id", UUID(as_uuid=True), sa.ForeignKey("enterprises.id"), nullable=False),
        sa.Column("seller_enterprise_id", UUID(as_uuid=True), sa.ForeignKey("enterprises.id"), nullable=False),
        sa.Column("status", sa.Text(), server_default="DRAFT", nullable=False),
        sa.Column("document_snapshot", JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("pdf_storage_key", sa.Text(), nullable=True),
        sa.Column("buyer_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seller_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.execute("""
        ALTER TABLE procurement_documents ADD CONSTRAINT ck_procurement_status
        CHECK (status IN ('DRAFT','PENDING_SELLER_ACCEPTANCE','ACTIVE','AMENDED','CANCELLED'))
    """)

    op.create_index("ix_procurement_documents_session", "procurement_documents", ["session_id"])
    op.create_index("ix_procurement_documents_buyer", "procurement_documents", ["buyer_enterprise_id"])
    op.create_index("ix_procurement_documents_seller", "procurement_documents", ["seller_enterprise_id"])

    op.create_table(
        "procurement_document_amendments",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("procurement_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amendment_type", sa.Text(), nullable=False),
        sa.Column("old_value", JSONB(), nullable=True),
        sa.Column("new_value", JSONB(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("amended_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("agreed_by_both", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("procurement_document_amendments")
    op.drop_index("ix_procurement_documents_seller", table_name="procurement_documents")
    op.drop_index("ix_procurement_documents_buyer", table_name="procurement_documents")
    op.drop_index("ix_procurement_documents_session", table_name="procurement_documents")
    op.drop_table("procurement_documents")
