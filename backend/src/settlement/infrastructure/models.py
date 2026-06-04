"""
SQLAlchemy ORM models for the settlement bounded context.

Tables: escrow_contracts, settlements
context.md §11 — Database Schema.
context.md §9.4 — Escrow State Machine: DEPLOYED(0) → FUNDED(1) → RELEASED(2) | REFUNDED(3)
context.md §11: escrow_contracts are never deleted (permanent audit record).
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.infrastructure.db.base import Base


class EscrowContractModel(Base):
    """
    Escrow contract aggregate (settlement bounded context).

    status: DEPLOYED | FUNDED | RELEASED | REFUNDED
    frozen: boolean flag (orthogonal to status — context.md §9.4)

    context.md §11: escrow_contracts are PERMANENT — never deleted.
    On-chain Merkle root provides cryptographic proof.
    """

    __tablename__ = "escrow_contracts"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_escrow_contracts_session_id"),
        # NOTE: algo_app_id is NOT unique — multiple escrows share the same
        # on-chain shared contract app_id (shared escrow architecture).
        CheckConstraint(
            "status IN ('PENDING_APPROVAL','APPROVED','DEPLOYED','FUNDED','DISPATCHED','RELEASED','REFUNDED','REJECTED','FROZEN')",
            name="ck_escrow_contracts_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("negotiation_sessions.id"),
        nullable=False,
        unique=True,
    )
    # Algorand application ID — shared contract reused across all escrow sessions
    algo_app_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Amount in microALGO
    amount_microalgo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    buyer_algorand_address: Mapped[str | None] = mapped_column(String(58), nullable=True)
    seller_algorand_address: Mapped[str | None] = mapped_column(String(58), nullable=True)
    # Creator address (Pera wallet deployer) — needed for release/refund authorization
    creator_address: Mapped[str | None] = mapped_column(String(58), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="PENDING_APPROVAL"
    )
    is_frozen: Mapped[bool] = mapped_column(
        nullable=False, server_default="false"  # type: ignore[call-arg]
    )
    # Transaction IDs for each lifecycle event
    deploy_tx_id: Mapped[str | None] = mapped_column(String(52), nullable=True)
    fund_tx_id: Mapped[str | None] = mapped_column(String(52), nullable=True)
    release_tx_id: Mapped[str | None] = mapped_column(String(52), nullable=True)
    refund_tx_id: Mapped[str | None] = mapped_column(String(52), nullable=True)
    # SHA-256 Merkle root anchored on-chain (context.md §8)
    merkle_root: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # context.md §11: NEVER deleted — permanent record
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    # Admin approval audit trail
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Agreed price in INR (from negotiation, pre-conversion)
    agreed_price_inr: Mapped[float | None] = mapped_column(nullable=True)
    buyer_enterprise_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    seller_enterprise_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Approval timeout — escrow auto-rejects if not approved within deadline
    approval_deadline: Mapped[str | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    settlements: Mapped[list[SettlementModel]] = relationship(
        "SettlementModel", back_populates="escrow"
    )


_escrow_session_idx = Index("ix_escrow_contracts_session_id", EscrowContractModel.session_id)
_escrow_app_id_idx = Index("ix_escrow_contracts_algo_app_id", EscrowContractModel.algo_app_id)


class SettlementModel(Base):
    """
    Settlement milestone record (settlement bounded context).

    Tracks milestone-based fund releases within an escrow contract.
    oracle_confirmation: JSONB blob from milestone oracle (context.md §7 Layer 7).
    """

    __tablename__ = "settlements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    escrow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("escrow_contracts.id"),
        nullable=False,
    )
    milestone_index: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_microalgo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tx_id: Mapped[str | None] = mapped_column(String(52), nullable=True)
    oracle_confirmation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    escrow: Mapped[EscrowContractModel] = relationship(
        "EscrowContractModel", back_populates="settlements"
    )


_settlements_escrow_idx = Index("ix_settlements_escrow_id", SettlementModel.escrow_id)
