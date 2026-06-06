"""
SQLAlchemy ORM models for wallet bounded context.

Tables: x402_payments, wallet_ledger
"""

from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.infrastructure.db.base import Base


class X402PaymentModel(Base):
    """
    Persisted record of a confirmed x402 Algorand payment.

    buyer_address   — Algorand sender address (Magic wallet)
    tx_id           — Confirmed Algorand transaction ID (unique)
    amount          — Payment amount in microALGO
    resource_url    — The API path the payment unlocked
    nonce           — UUID-v4 nonce from the 402 response (replay protection)
    confirmed_round — Algorand block round in which the txn was confirmed
    paid_at         — Timestamp of payment confirmation
    created_at      — Row creation timestamp
    """

    __tablename__ = "x402_payments"
    __table_args__ = (
        Index("ix_x402_payments_buyer_address", "buyer_address"),
        Index("ix_x402_payments_nonce", "nonce"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    buyer_address: Mapped[str] = mapped_column(Text, nullable=False)
    tx_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    resource_url: Mapped[str] = mapped_column(Text, nullable=False)
    nonce: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    confirmed_round: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    paid_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WalletLedgerModel(Base):
    """Event-sourced wallet ledger for all ALGO movements.

    Tracks escrow fund/release/refund, x402 payments, and onramp deposits
    so historical balance can be reconstructed without blockchain queries.
    """

    __tablename__ = "wallet_ledger"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    algorand_address: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    amount_microalgo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tx_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reference_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    balance_before_microalgo: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    balance_after_microalgo: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
