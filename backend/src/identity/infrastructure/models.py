"""
SQLAlchemy ORM models for the identity bounded context.

Tables: enterprises, users, api_keys
context.md §11 — Database Schema.

Design rules:
- UUID PKs with gen_random_uuid() server_default
- Enum columns use VARCHAR + CHECK constraints (avoids migration lock-in)
- TIMESTAMPTZ with server_default=func.now()
- JSONB columns use JSON type in SQLAlchemy
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.infrastructure.db.base import Base


class EnterpriseModel(Base):
    """
    enterprise aggregate root (identity bounded context).

    kyc_status:  PENDING | KYC_SUBMITTED | VERIFIED | ACTIVE
    trade_role:  BUYER | SELLER | BOTH
    """

    __tablename__ = "enterprises"
    __table_args__ = (
        UniqueConstraint("pan", name="uq_enterprises_pan"),
        UniqueConstraint("gstin", name="uq_enterprises_gstin"),
        CheckConstraint(
            "kyc_status IN ('PENDING','KYC_SUBMITTED','VERIFIED','ACTIVE')",
            name="ck_enterprises_kyc_status",
        ),
        CheckConstraint(
            "trade_role IN ('BUYER','SELLER','BOTH')",
            name="ck_enterprises_trade_role",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    pan: Mapped[str] = mapped_column(String(10), nullable=False)
    gstin: Mapped[str] = mapped_column(String(15), nullable=False)
    kyc_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="PENDING"
    )
    trade_role: Mapped[str] = mapped_column(String(10), nullable=False)
    algorand_wallet: Mapped[str | None] = mapped_column(String(58), nullable=True)
    algorand_wallet_changed_at: Mapped[str | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    kyc_documents: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    agent_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Enhanced onboarding fields
    facility_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    payment_terms_accepted: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    credit_period_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    years_in_operation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    annual_turnover_inr: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    quality_certifications: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    test_certificate_available: Mapped[bool | None] = mapped_column(
        Boolean, server_default="false", nullable=True
    )
    third_party_inspection_allowed: Mapped[bool | None] = mapped_column(
        Boolean, server_default="false", nullable=True
    )
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    users: Mapped[list[UserModel]] = relationship("UserModel", back_populates="enterprise")
    api_keys: Mapped[list[APIKeyModel]] = relationship(
        "APIKeyModel", back_populates="enterprise"
    )


# Indexes declared separately for clarity
_enterprises_pan_idx = Index("ix_enterprises_pan", EnterpriseModel.pan)
_enterprises_gstin_idx = Index("ix_enterprises_gstin", EnterpriseModel.gstin)


class UserModel(Base):
    """
    User entity (identity bounded context).

    role: ADMIN | MEMBER | BUYER | SELLER | COMPLIANCE_OFFICER | TREASURY_MANAGER | AUDITOR
    """

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        CheckConstraint(
            "role IN ('ADMIN','MEMBER','BUYER','SELLER','COMPLIANCE_OFFICER','TREASURY_MANAGER','AUDITOR')",
            name="ck_users_role",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("enterprises.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    last_login_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    enterprise: Mapped[EnterpriseModel] = relationship(
        "EnterpriseModel", back_populates="users"
    )


_users_email_idx = Index("ix_users_email", UserModel.email)
_users_enterprise_idx = Index("ix_users_enterprise_id", UserModel.enterprise_id)


class APIKeyModel(Base):
    """
    API key for M2M authentication (identity bounded context).

    context.md §14: key_hash stores HMAC-SHA256 hash.
    Plaintext NEVER persisted or logged.
    """

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("enterprises.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # context.md §14: HMAC-SHA256 hash — plaintext never stored
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    expires_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    enterprise: Mapped[EnterpriseModel] = relationship(
        "EnterpriseModel", back_populates="api_keys"
    )


_api_keys_hash_idx = Index("ix_api_keys_key_hash", APIKeyModel.key_hash, unique=True)
_api_keys_enterprise_idx = Index("ix_api_keys_enterprise_id", APIKeyModel.enterprise_id)
