"""
Unit tests for Escrow aggregate root — state machine transitions.

context.md §9.4: DEPLOYED(0) → FUNDED(1) → RELEASED(2) | REFUNDED(3).
Frozen flag is orthogonal to status — blocks transitions when set.
"""

import uuid

import pytest

from src.settlement.domain.escrow import (
    Escrow,
    EscrowDeployed,
    EscrowFunded,
    EscrowStatus,
)
from src.settlement.domain.value_objects import (
    AlgoAppAddress,
    AlgoAppId,
    EscrowAmount,
    MerkleRoot,
    MicroAlgo,
    TxId,
)
from src.shared.domain.exceptions import ConflictError, PolicyViolation


# Valid 58-char base32 addresses
_BUYER_ADDR = "A" * 58
_SELLER_ADDR = "B" * 58
_APP_ADDR = "C" * 58
# Valid 52-char base32 TxId
_TX_DEPLOY = "D" * 52
_TX_FUND = "E" * 52
_TX_RELEASE = "F" * 52
_TX_REFUND = "G" * 52
# Valid 64-char hex Merkle root
_MERKLE = "a1b2c3d4" * 8


def _make_escrow(**kwargs) -> Escrow:
    """Factory helper with sensible defaults."""
    defaults = {
        "session_id": uuid.uuid4(),
        "buyer_address": _BUYER_ADDR,
        "seller_address": _SELLER_ADDR,
        "amount": EscrowAmount(value=MicroAlgo(value=10_000_000)),
    }
    defaults.update(kwargs)
    return Escrow(**defaults)


def _deploy(escrow: Escrow) -> EscrowDeployed:
    """Record deployment with valid mock values."""
    return escrow.record_deployment(
        app_id=AlgoAppId(value=12345),
        app_address=AlgoAppAddress(value=_APP_ADDR),
        tx_id=TxId(value=_TX_DEPLOY),
    )


# ── Deployment ────────────────────────────────────────────────────────────────


class TestEscrowDeployment:
    def test_initial_status_is_pending_approval(self):
        """Fresh Escrow starts in PENDING_APPROVAL — must be approved before deploy."""
        esc = _make_escrow()
        assert esc.status == EscrowStatus.PENDING_APPROVAL

    def test_record_approval_transitions_to_approved(self):
        """record_approval() advances PENDING_APPROVAL → APPROVED."""
        esc = _make_escrow()
        esc.record_approval()
        assert esc.status == EscrowStatus.APPROVED

    def test_record_deployment_success(self):
        esc = _make_escrow()
        esc.record_approval()  # must be APPROVED before record_deployment
        event = _deploy(esc)
        assert esc.algo_app_id == AlgoAppId(value=12345)
        assert isinstance(event, EscrowDeployed)
        assert event.algo_app_id == 12345

    def test_double_deploy_raises_conflict(self):
        esc = _make_escrow()
        esc.record_approval()
        _deploy(esc)
        with pytest.raises(ConflictError, match="already deployed"):
            _deploy(esc)


# ── Funding ───────────────────────────────────────────────────────────────────


class TestEscrowFunding:
    def test_fund_from_deployed(self):
        """Full path: PENDING_APPROVAL → DEPLOYED → FUNDED."""
        esc = _make_escrow()
        esc.record_approval()  # PENDING_APPROVAL → DEPLOYED
        _deploy(esc)           # attaches app_id
        event = esc.record_funding(TxId(value=_TX_FUND))
        assert esc.status == EscrowStatus.FUNDED
        assert isinstance(event, EscrowFunded)

    def test_fund_from_funded_raises_conflict(self):
        esc = _make_escrow(status=EscrowStatus.FUNDED)
        with pytest.raises(ConflictError, match="expected DEPLOYED"):
            esc.record_funding(TxId(value=_TX_FUND))

    def test_fund_when_frozen_raises_policy(self):
        esc = _make_escrow(frozen=True)
        with pytest.raises(PolicyViolation, match="frozen"):
            esc.record_funding(TxId(value=_TX_FUND))


# ── Release ───────────────────────────────────────────────────────────────────


class TestEscrowRelease:
    def test_release_from_funded(self):
        esc = _make_escrow(status=EscrowStatus.FUNDED)
        event = esc.record_release(
            tx_id=TxId(value=_TX_RELEASE),
            merkle_root=MerkleRoot(value=_MERKLE),
        )
        assert esc.status == EscrowStatus.RELEASED
        assert event.event_type == "EscrowReleased"

    def test_release_from_deployed_raises_conflict(self):
        esc = _make_escrow(status=EscrowStatus.DEPLOYED)
        with pytest.raises(ConflictError, match="expected FUNDED"):
            esc.record_release(
                tx_id=TxId(value=_TX_RELEASE),
                merkle_root=MerkleRoot(value=_MERKLE),
            )

    def test_release_when_frozen_raises_policy(self):
        esc = _make_escrow(status=EscrowStatus.FUNDED, frozen=True)
        with pytest.raises(PolicyViolation, match="frozen"):
            esc.record_release(
                tx_id=TxId(value=_TX_RELEASE),
                merkle_root=MerkleRoot(value=_MERKLE),
            )


# ── Refund ────────────────────────────────────────────────────────────────────


class TestEscrowRefund:
    def test_refund_from_funded(self):
        esc = _make_escrow(status=EscrowStatus.FUNDED)
        event = esc.record_refund(tx_id=TxId(value=_TX_REFUND))
        assert esc.status == EscrowStatus.REFUNDED
        assert event.event_type == "EscrowRefunded"

    def test_refund_from_deployed_raises(self):
        esc = _make_escrow(status=EscrowStatus.DEPLOYED)
        with pytest.raises(ConflictError, match="expected FUNDED"):
            esc.record_refund(tx_id=TxId(value=_TX_REFUND))


# ── Freeze / Unfreeze ─────────────────────────────────────────────────────────


class TestFreezeUnfreeze:
    def test_freeze_funded_escrow(self):
        esc = _make_escrow(status=EscrowStatus.FUNDED)
        esc.freeze()
        assert esc.frozen is True
        assert esc.status == EscrowStatus.FROZEN

    def test_unfreeze_restores_funded(self):
        esc = _make_escrow(status=EscrowStatus.FROZEN, frozen=True)
        esc.unfreeze()
        assert esc.frozen is False
        assert esc.status == EscrowStatus.FUNDED

    def test_cannot_freeze_already_frozen(self):
        esc = _make_escrow(status=EscrowStatus.FROZEN, frozen=True)
        with pytest.raises(ConflictError, match="already frozen"):
            esc.freeze()


# ── Full Lifecycle ────────────────────────────────────────────────────────────


class TestEscrowLifecycle:
    def test_deploy_fund_release(self):
        """Full happy path: PENDING_APPROVAL → DEPLOYED → FUNDED → RELEASED."""
        esc = _make_escrow()
        esc.record_approval()  # → DEPLOYED
        _deploy(esc)            # attaches app_id
        esc.record_funding(TxId(value=_TX_FUND))
        esc.record_release(
            tx_id=TxId(value=_TX_RELEASE),
            merkle_root=MerkleRoot(value=_MERKLE),
        )
        assert esc.status == EscrowStatus.RELEASED
        assert esc.merkle_root is not None

    def test_deploy_fund_refund(self):
        """Dispute path: PENDING_APPROVAL → DEPLOYED → FUNDED → REFUNDED."""
        esc = _make_escrow()
        esc.record_approval()  # → DEPLOYED
        _deploy(esc)            # attaches app_id
        esc.record_funding(TxId(value=_TX_FUND))
        esc.record_refund(tx_id=TxId(value=_TX_REFUND))
        assert esc.status == EscrowStatus.REFUNDED
