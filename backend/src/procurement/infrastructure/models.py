"""SQLAlchemy ORM models for procurement bounded context."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infrastructure.db.base import Base


class ProcurementDocumentModel(Base):
    """Purchase order / procurement document."""

    __tablename__ = "procurement_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    po_number: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("negotiation_sessions.id"), nullable=False
    )
    escrow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("escrow_contracts.id"), nullable=True
    )
    buyer_enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    seller_enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, server_default="DRAFT", nullable=False)
    document_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)
    pdf_storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    buyer_accepted_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    seller_accepted_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ProcurementDocumentAmendmentModel(Base):
    """Amendment record for a procurement document."""

    __tablename__ = "procurement_document_amendments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("procurement_documents.id", ondelete="CASCADE"), nullable=False
    )
    amendment_type: Mapped[str] = mapped_column(Text, nullable=False)
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    amended_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    agreed_by_both: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
