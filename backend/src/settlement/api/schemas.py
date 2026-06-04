# context.md §3: FastAPI/Pydantic imports ONLY in api/ layer.
# Pydantic v2 DTOs — completely separate from domain entities.

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_serializer

from src.settlement.domain.escrow import Escrow
from src.settlement.domain.settlement import Settlement

# ── Response Schemas ──────────────────────────────────────────────────────────


class EscrowResponse(BaseModel):
    escrow_id: uuid.UUID
    session_id: uuid.UUID
    algo_app_id: int | None
    algo_app_address: str | None
    amount_microalgo: int
    amount_algo: Decimal
    status: str

    @field_serializer('amount_algo')
    def serialize_amount_algo(self, value: Decimal) -> float:
        return float(value)
    frozen: bool
    deploy_tx_id: str | None
    fund_tx_id: str | None
    release_tx_id: str | None
    refund_tx_id: str | None
    merkle_root: str | None
    created_at: datetime
    settled_at: datetime | None

    @classmethod
    def from_domain(cls, escrow: Escrow) -> "EscrowResponse":
        amount_micro = escrow.amount.value.value
        return cls(
            escrow_id=escrow.id,
            session_id=escrow.session_id,
            algo_app_id=escrow.algo_app_id.value if escrow.algo_app_id else None,
            algo_app_address=(
                escrow.algo_app_address.value if escrow.algo_app_address else None
            ),
            amount_microalgo=amount_micro,
            amount_algo=Decimal(amount_micro) / Decimal("1000000"),
            status=escrow.status.value,
            frozen=escrow.frozen,
            deploy_tx_id=escrow.deploy_tx_id.value if escrow.deploy_tx_id else None,
            fund_tx_id=escrow.fund_tx_id.value if escrow.fund_tx_id else None,
            release_tx_id=escrow.release_tx_id.value if escrow.release_tx_id else None,
            refund_tx_id=escrow.refund_tx_id.value if escrow.refund_tx_id else None,
            merkle_root=escrow.merkle_root.value if escrow.merkle_root else None,
            created_at=escrow.created_at,
            settled_at=escrow.settled_at,
        )


class SettlementResponse(BaseModel):
    settlement_id: uuid.UUID
    escrow_id: uuid.UUID
    milestone_index: int
    amount_microalgo: int
    tx_id: str
    settled_at: datetime

    @classmethod
    def from_domain(cls, s: Settlement) -> "SettlementResponse":
        return cls(
            settlement_id=s.id,
            escrow_id=s.escrow_id,
            milestone_index=s.milestone_index,
            amount_microalgo=s.amount.value,
            tx_id=s.tx_id.value,
            settled_at=s.settled_at,
        )


# ── Request Schemas ───────────────────────────────────────────────────────────


class DeployEscrowRequest(BaseModel):
    """
    Phase Two convenience endpoint to deploy escrow via API.
    In Phase Four+, deployment is triggered by SessionAgreed domain event.
    """

    buyer_enterprise_id: uuid.UUID
    seller_enterprise_id: uuid.UUID
    buyer_algo_address: str = Field(min_length=58, max_length=58)
    seller_algo_address: str = Field(min_length=58, max_length=58)
    agreed_price_microalgo: int = Field(gt=0)


class FundEscrowRequest(BaseModel):
    """
    Buyer provides their Algorand mnemonic to fund the escrow.

    SECURITY: mnemonic converted to sk in dependency layer — NEVER logged.
    """

    funder_algo_mnemonic: str = Field(
        min_length=100,
        description="25-word Algorand mnemonic for buyer wallet",
    )


class ReleaseEscrowRequest(BaseModel):
    """No body required — admin action, escrow identified by path param."""

    pass


class RefundEscrowRequest(BaseModel):
    reason: str = Field(
        min_length=10,
        max_length=500,
        description="Required reason for audit trail",
    )


class FreezeEscrowRequest(BaseModel):
    frozen_by_role: Literal["BUYER", "SELLER", "ADMIN"] = "ADMIN"


class DeployEscrowResponse(BaseModel):
    escrow_id: uuid.UUID
    algo_app_id: int | None
    algo_app_address: str | None
    status: str
    tx_id: str | None
