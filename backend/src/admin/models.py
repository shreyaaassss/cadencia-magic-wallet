"""
SQLAlchemy ORM models for the admin bounded context.

Tables: llm_call_logs, broadcasts
These tables support the admin dashboard's LLM monitoring and broadcast features.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infrastructure.db.base import Base


class LLMCallLogModel(Base):
    """
    Persistent log of every LLM API call made by negotiation agents.

    Used by:
      - GET /v1/admin/llm-logs  (audit view)
      - GET /v1/admin/stats     (llm_calls_today aggregate)
      - GET /v1/admin/agents    (per-session average latency + model name)
    """

    __tablename__ = "llm_call_logs"
    __table_args__ = (
        CheckConstraint(
            "agent_role IN ('BUYER','SELLER')",
            name="ck_llm_call_logs_agent_role",
        ),
        CheckConstraint(
            "status IN ('SUCCESS','TIMEOUT','ERROR')",
            name="ck_llm_call_logs_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("negotiation_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_role: Mapped[str] = mapped_column(String(10), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="SUCCESS")
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


_llm_logs_session_idx = Index("ix_llm_call_logs_session_id", LLMCallLogModel.session_id)
_llm_logs_created_idx = Index("ix_llm_call_logs_created_at", LLMCallLogModel.created_at)


class BroadcastModel(Base):
    """
    Persisted platform-wide broadcast/notification record.

    Used by POST /v1/admin/broadcast.
    """

    __tablename__ = "broadcasts"
    __table_args__ = (
        CheckConstraint(
            "target IN ('all','active_enterprises','admins_only')",
            name="ck_broadcasts_target",
        ),
        CheckConstraint(
            "priority IN ('low','normal','high','critical')",
            name="ck_broadcasts_priority",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str] = mapped_column(String(25), nullable=False)
    priority: Mapped[str] = mapped_column(String(10), nullable=False, server_default="normal")
    sender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


_broadcasts_created_idx = Index("ix_broadcasts_created_at", BroadcastModel.created_at)
