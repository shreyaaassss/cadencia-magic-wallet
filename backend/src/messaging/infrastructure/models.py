"""SQLAlchemy ORM models for messaging bounded context."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infrastructure.db.base import Base


class ConversationThreadModel(Base):
    """Buyer-seller conversation thread scoped by deal."""

    __tablename__ = "conversation_threads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    thread_type: Mapped[str] = mapped_column(Text, nullable=False)
    rfq_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rfqs.id"), nullable=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("negotiation_sessions.id"), nullable=True
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
    status: Mapped[str] = mapped_column(Text, server_default="OPEN", nullable=False)
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MessageModel(Base):
    """Individual message within a conversation thread."""

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation_threads.id", ondelete="CASCADE"), nullable=False
    )
    sender_enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    sender_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[dict | None] = mapped_column(JSONB, server_default="[]", nullable=True)
    is_system_generated: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    read_by: Mapped[dict | None] = mapped_column(JSONB, server_default=func.cast("{}", JSONB), nullable=True)
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
