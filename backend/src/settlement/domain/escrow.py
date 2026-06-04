# context.md §3 — Hexagonal Architecture: zero framework imports in domain layer.
# context.md §9.4: Escrow state machine must mirror Puya contract status codes exactly.
#   On-chain: 0=DEPLOYED, 1=FUNDED, 2=RELEASED, 3=REFUNDED + frozen flag (orthogonal).
# Pure Python aggregate root extending BaseEntity.

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from src.settlement.domain.value_objects import (
    AlgoAppAddress,
    AlgoAppId,
    EscrowAmount,
    MerkleRoot,
    MicroAlgo,
    TxId,
)
from src.shared.domain.base_entity import BaseEntity
from src.shared.domain.events import DomainEvent
from src.shared.domain.exceptions import ConflictError, PolicyViolation


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# ── Escrow Status ─────────────────────────────────────────────────────────────


class EscrowStatus(str, Enum):
    """
    Python-side escrow state machine.

    State flow:
        PENDING_APPROVAL  Admin gate — escrow record created, awaiting admin approval.
        APPROVED          Admin approved — buyer deploys the smart contract via Pera Wallet.
        DEPLOYED = 0      Contract created on-chain by buyer's Pera Wallet; awaiting funding.
        FUNDED   = 1      Buyer funded the contract.
        RELEASED = 2      Funds sent to seller.
        REFUNDED = 3      Funds returned to buyer.
        REJECTED          Admin rejected the escrow request (terminal).
        FROZEN            Orthogonal dispute-freeze flag; maps to is_frozen=True in DB.
                          Stored as FUNDED + is_frozen=True; unfreeze restores to FUNDED.
    """

    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    DEPLOYED = "DEPLOYED"
    FUNDED = "FUNDED"
    DISPATCHED = "DISPATCHED"  # Seller has shipped goods; awaiting buyer delivery confirmation
    RELEASED = "RELEASED"
    REFUNDED = "REFUNDED"
    REJECTED = "REJECTED"
    FROZEN = "FROZEN"  # Python-side convenience; persisted as FUNDED + is_frozen=True


# ── Escrow Aggregate ──────────────────────────────────────────────────────────


@dataclass
class Escrow(BaseEntity):
    """
    Escrow aggregate root (settlement bounded context).

    Enforces the escrow state machine and domain invariants.
    No algosdk / sqlalchemy / fastapi imports — pure Python.

    INVARIANT: Python state machine MUST mirror on-chain contract state.
    """

    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
    buyer_address: str = ""
    seller_address: str = ""
    amount: EscrowAmount = field(
        default_factory=lambda: EscrowAmount(value=MicroAlgo(value=1))
    )
    status: EscrowStatus = EscrowStatus.PENDING_APPROVAL
    algo_app_id: AlgoAppId | None = None
    algo_app_address: AlgoAppAddress | None = None
    deploy_tx_id: TxId | None = None
    fund_tx_id: TxId | None = None
    release_tx_id: TxId | None = None
    refund_tx_id: TxId | None = None
    merkle_root: MerkleRoot | None = None
    frozen: bool = False
    settled_at: datetime | None = None

    # ── Lifecycle Methods ─────────────────────────────────────────────────────

    def record_approval(self) -> "EscrowApproved":
        """
        Transition: PENDING_APPROVAL → APPROVED (admin approved).

        The buyer must now deploy the smart contract via Pera Wallet.
        This triggers APPROVED → DEPLOYED when the buyer calls record_deployment().
        Guard: raises ConflictError if status != PENDING_APPROVAL.
        """
        if self.status != EscrowStatus.PENDING_APPROVAL:
            raise ConflictError(
                f"Cannot approve escrow {self.id}: expected PENDING_APPROVAL, "
                f"got '{self.status.value}'."
            )
        self.status = EscrowStatus.APPROVED
        self.touch()
        return EscrowApproved(
            aggregate_id=self.id,
            event_type="EscrowApproved",
            escrow_id=self.id,
            session_id=self.session_id,
        )

    def record_rejection(self, reason: str = "") -> "EscrowRejected":
        """
        Transition: PENDING_APPROVAL → REJECTED (admin rejected).

        Terminal state — no further transitions possible.
        Guard: raises ConflictError if status != PENDING_APPROVAL.
        """
        if self.status != EscrowStatus.PENDING_APPROVAL:
            raise ConflictError(
                f"Cannot reject escrow {self.id}: expected PENDING_APPROVAL, "
                f"got '{self.status.value}'."
            )
        self.status = EscrowStatus.REJECTED
        self.touch()
        return EscrowRejected(
            aggregate_id=self.id,
            event_type="EscrowRejected",
            escrow_id=self.id,
            session_id=self.session_id,
            reason=reason,
        )

    def record_deployment(
        self,
        app_id: AlgoAppId,
        app_address: AlgoAppAddress,
        tx_id: TxId,
    ) -> "EscrowDeployed":
        """
        Record that the Algorand smart contract was created on-chain by the buyer's Pera Wallet.

        Transitions: APPROVED → DEPLOYED (also works from PENDING_APPROVAL for legacy flows).
        Sets algo_app_id, algo_app_address, deploy_tx_id.
        Guard: raises ConflictError if app_id already set (double-deploy guard).
        """
        if self.algo_app_id is not None and self.algo_app_id.value != 0:
            raise ConflictError(
                f"Escrow {self.id} is already deployed to app_id={self.algo_app_id.value}."
            )
        self.algo_app_id = app_id
        self.algo_app_address = app_address
        self.deploy_tx_id = tx_id
        self.status = EscrowStatus.DEPLOYED  # APPROVED → DEPLOYED
        self.touch()
        return EscrowDeployed(
            aggregate_id=self.id,
            event_type="EscrowDeployed",
            escrow_id=self.id,
            session_id=self.session_id,
            algo_app_id=app_id.value,
            deploy_tx_id=tx_id.value,
        )

    def record_funding(self, tx_id: TxId) -> "EscrowFunded":
        """
        Transition: DEPLOYED → FUNDED.

        Guards:
          - ConflictError if status != DEPLOYED
          - PolicyViolation if frozen
        """
        if self.frozen:
            raise PolicyViolation(
                f"Cannot fund escrow {self.id}: escrow is frozen."
            )
        if self.status != EscrowStatus.DEPLOYED:
            raise ConflictError(
                f"Cannot fund escrow {self.id}: expected DEPLOYED, "
                f"got '{self.status.value}'."
            )
        self.status = EscrowStatus.FUNDED
        self.fund_tx_id = tx_id
        self.touch()
        return EscrowFunded(
            aggregate_id=self.id,
            event_type="EscrowFunded",
            escrow_id=self.id,
            session_id=self.session_id,
            amount_microalgo=self.amount.value.value,
            fund_tx_id=tx_id.value,
        )

    def mark_dispatched(self) -> "EscrowDispatched":
        """
        Transition: FUNDED → DISPATCHED.

        Seller has shipped goods. Buyer must confirm delivery to release funds.
        """
        if self.frozen:
            raise PolicyViolation(
                f"Cannot dispatch escrow {self.id}: escrow is frozen."
            )
        if self.status != EscrowStatus.FUNDED:
            raise ConflictError(
                f"Cannot dispatch escrow {self.id}: expected FUNDED, "
                f"got '{self.status.value}'."
            )
        self.status = EscrowStatus.DISPATCHED
        self.touch()
        return EscrowDispatched(
            aggregate_id=self.id,
            event_type="EscrowDispatched",
            escrow_id=self.id,
            session_id=self.session_id,
        )

    def record_release(self, tx_id: TxId, merkle_root: MerkleRoot) -> "EscrowReleased":
        """
        Transition: FUNDED/DISPATCHED → RELEASED.

        Guards:
          - ConflictError if status not in (FUNDED, DISPATCHED)
          - PolicyViolation if frozen
        """
        if self.frozen:
            raise PolicyViolation(
                f"Cannot release escrow {self.id}: escrow is frozen."
            )
        if self.status not in (EscrowStatus.FUNDED, EscrowStatus.DISPATCHED):
            raise ConflictError(
                f"Cannot release escrow {self.id}: expected FUNDED or DISPATCHED, "
                f"got '{self.status.value}'."
            )
        self.status = EscrowStatus.RELEASED
        self.release_tx_id = tx_id
        self.merkle_root = merkle_root
        self.settled_at = _utcnow()
        self.touch()
        return EscrowReleased(
            aggregate_id=self.id,
            event_type="EscrowReleased",
            escrow_id=self.id,
            session_id=self.session_id,
            amount_microalgo=self.amount.value.value,
            release_tx_id=tx_id.value,
            merkle_root=merkle_root.value,
        )

    def record_refund(self, tx_id: TxId) -> "EscrowRefunded":
        """
        Transition: FUNDED → REFUNDED.

        Guard: ConflictError if status != FUNDED.
        (Refund IS allowed while frozen — admin can force-refund frozen escrow.)
        """
        if self.status != EscrowStatus.FUNDED and self.status != EscrowStatus.FROZEN:
            raise ConflictError(
                f"Cannot refund escrow {self.id}: expected FUNDED or FROZEN, "
                f"got '{self.status.value}'."
            )
        self.status = EscrowStatus.REFUNDED
        self.frozen = False
        self.refund_tx_id = tx_id
        self.settled_at = _utcnow()
        self.touch()
        return EscrowRefunded(
            aggregate_id=self.id,
            event_type="EscrowRefunded",
            escrow_id=self.id,
            session_id=self.session_id,
            amount_microalgo=self.amount.value.value,
            refund_tx_id=tx_id.value,
            reason="",
        )

    def freeze(self) -> "EscrowFrozen":
        """
        Freeze the escrow to halt all state transitions.

        Guards:
          - ConflictError if status in (RELEASED, REFUNDED) — terminal states
          - ConflictError if already frozen
        """
        if self.status in (EscrowStatus.RELEASED, EscrowStatus.REFUNDED):
            raise ConflictError(
                f"Cannot freeze escrow {self.id}: already in terminal "
                f"state '{self.status.value}'."
            )
        if self.frozen:
            raise ConflictError(
                f"Escrow {self.id} is already frozen."
            )
        self.frozen = True
        self.status = EscrowStatus.FROZEN
        self.touch()
        return EscrowFrozen(
            aggregate_id=self.id,
            event_type="EscrowFrozen",
            escrow_id=self.id,
            session_id=self.session_id,
            frozen_by="ADMIN",
        )

    def unfreeze(self) -> "EscrowUnfrozen":
        """
        Unfreeze the escrow after dispute resolution.

        Guard: ConflictError if not frozen.
        Restores status to FUNDED (frozen escrow was always funded or deployed).
        """
        if not self.frozen:
            raise ConflictError(
                f"Escrow {self.id} is not frozen."
            )
        self.frozen = False
        self.status = EscrowStatus.FUNDED
        self.touch()
        return EscrowUnfrozen(
            aggregate_id=self.id,
            event_type="EscrowUnfrozen",
            escrow_id=self.id,
            session_id=self.session_id,
        )


# ── Domain Events (defined here for proximity; re-exported from events.py) ────


@dataclass(frozen=True)
class EscrowApproved(DomainEvent):
    escrow_id: uuid.UUID = field(default_factory=uuid.uuid4)
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass(frozen=True)
class EscrowRejected(DomainEvent):
    escrow_id: uuid.UUID = field(default_factory=uuid.uuid4)
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
    reason: str = ""


@dataclass(frozen=True)
class EscrowDeployed(DomainEvent):
    escrow_id: uuid.UUID = field(default_factory=uuid.uuid4)
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
    algo_app_id: int = 0
    deploy_tx_id: str = ""


@dataclass(frozen=True)
class EscrowFunded(DomainEvent):
    escrow_id: uuid.UUID = field(default_factory=uuid.uuid4)
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
    amount_microalgo: int = 0
    fund_tx_id: str = ""


@dataclass(frozen=True)
class EscrowReleased(DomainEvent):
    escrow_id: uuid.UUID = field(default_factory=uuid.uuid4)
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
    amount_microalgo: int = 0
    release_tx_id: str = ""
    merkle_root: str = ""
    # Optional Phase 3+ fields — populated by SettlementService when
    # buyer/seller enterprise IDs are available (added non-breakingly).
    buyer_enterprise_id: uuid.UUID | None = None
    seller_enterprise_id: uuid.UUID | None = None
    inr_amount_paise: int = 0  # INR amount in paise (0 = unknown; treasury fills in Phase 7)


@dataclass(frozen=True)
class EscrowRefunded(DomainEvent):
    escrow_id: uuid.UUID = field(default_factory=uuid.uuid4)
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
    amount_microalgo: int = 0
    refund_tx_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class EscrowDispatched(DomainEvent):
    escrow_id: uuid.UUID = field(default_factory=uuid.uuid4)
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass(frozen=True)
class EscrowFrozen(DomainEvent):
    escrow_id: uuid.UUID = field(default_factory=uuid.uuid4)
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
    frozen_by: str = "ADMIN"


@dataclass(frozen=True)
class EscrowUnfrozen(DomainEvent):
    escrow_id: uuid.UUID = field(default_factory=uuid.uuid4)
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
