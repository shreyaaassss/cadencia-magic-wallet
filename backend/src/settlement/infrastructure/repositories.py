# context.md §3 — SQLAlchemy ONLY in infrastructure layer, never in domain.
# Bidirectional mapping: EscrowContractModel ↔ Escrow domain entity.
# EscrowStatus.FROZEN is orthogonal — stored as status='FUNDED' + is_frozen=True in DB.

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.settlement.domain.escrow import Escrow, EscrowStatus
from src.settlement.domain.settlement import Settlement
from src.settlement.domain.value_objects import (
    AlgoAppAddress,
    AlgoAppId,
    EscrowAmount,
    MicroAlgo,
    TxId,
)
from src.settlement.infrastructure.models import EscrowContractModel, SettlementModel

# ── Unchecked constructors (bypass validation on DB reload) ───────────────────


def _make_txid_unchecked(value: str) -> TxId:
    """Bypass TxId validation on load — value was valid when saved."""
    obj = object.__new__(TxId)
    object.__setattr__(obj, "value", value)
    return obj


def _make_algo_app_address_unchecked(value: str) -> AlgoAppAddress:
    obj = object.__new__(AlgoAppAddress)
    object.__setattr__(obj, "value", value)
    return obj


def _get_app_address_from_app_id(app_id: int) -> str:
    """
    Compute Algorand application address from app_id.
    Uses algosdk in infrastructure layer — never called in domain.
    """
    import algosdk.logic as logic  # type: ignore[import-untyped]

    return str(logic.get_application_address(app_id))


# ── EscrowContractModel ↔ Escrow ──────────────────────────────────────────────


def _model_to_escrow(model: EscrowContractModel) -> Escrow:
    """Reconstruct Escrow aggregate from ORM model."""
    # Determine Python status (FROZEN is orthogonal — stored as is_frozen flag)
    if model.is_frozen:
        status = EscrowStatus.FROZEN
    else:
        status = EscrowStatus(model.status)

    # Compute app_address from app_id (always derivable — no DB column needed)
    algo_app_address: AlgoAppAddress | None = None
    if model.algo_app_id is not None:
        app_addr_str = _get_app_address_from_app_id(model.algo_app_id)
        algo_app_address = _make_algo_app_address_unchecked(app_addr_str)

    escrow = Escrow(
        session_id=model.session_id,
        buyer_address=model.buyer_algorand_address or "",
        seller_address=model.seller_algorand_address or "",
        amount=EscrowAmount(value=MicroAlgo(value=model.amount_microalgo)),
        status=status,
        algo_app_id=AlgoAppId(value=model.algo_app_id) if model.algo_app_id else None,
        algo_app_address=algo_app_address,
        deploy_tx_id=_make_txid_unchecked(model.deploy_tx_id) if model.deploy_tx_id else None,
        fund_tx_id=_make_txid_unchecked(model.fund_tx_id) if model.fund_tx_id else None,
        release_tx_id=(
            _make_txid_unchecked(model.release_tx_id) if model.release_tx_id else None
        ),
        refund_tx_id=(
            _make_txid_unchecked(model.refund_tx_id) if model.refund_tx_id else None
        ),
        merkle_root=None,  # loaded below
        frozen=model.is_frozen,
        settled_at=getattr(model, "settled_at", None),
    )
    # Set id and timestamps from model
    object.__setattr__(escrow, "id", model.id)  # type: ignore[arg-type]

    # MerkleRoot — bypass validation on load
    if model.merkle_root:
        from src.settlement.domain.value_objects import MerkleRoot

        mr = object.__new__(MerkleRoot)
        object.__setattr__(mr, "value", model.merkle_root)
        escrow.merkle_root = mr

    if model.created_at:
        ts = model.created_at
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        object.__setattr__(escrow, "created_at", ts)
    if model.updated_at:
        ts = model.updated_at
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        object.__setattr__(escrow, "updated_at", ts)

    return escrow


def _escrow_to_model(escrow: Escrow) -> EscrowContractModel:
    """Map Escrow domain entity → ORM model for persistence."""
    # FROZEN maps to FUNDED + is_frozen=True in DB (CHECK constraint excludes FROZEN)
    if escrow.status == EscrowStatus.FROZEN:
        db_status = "FUNDED"
        is_frozen = True
    else:
        db_status = escrow.status.value
        is_frozen = escrow.frozen

    model = EscrowContractModel()
    model.id = escrow.id
    model.session_id = escrow.session_id
    model.algo_app_id = escrow.algo_app_id.value if escrow.algo_app_id else None
    model.amount_microalgo = escrow.amount.value.value
    model.buyer_algorand_address = escrow.buyer_address or None
    model.seller_algorand_address = escrow.seller_address or None
    model.status = db_status
    model.is_frozen = is_frozen
    model.deploy_tx_id = escrow.deploy_tx_id.value if escrow.deploy_tx_id else None
    model.fund_tx_id = escrow.fund_tx_id.value if escrow.fund_tx_id else None
    model.release_tx_id = escrow.release_tx_id.value if escrow.release_tx_id else None
    model.refund_tx_id = escrow.refund_tx_id.value if escrow.refund_tx_id else None
    model.merkle_root = escrow.merkle_root.value if escrow.merkle_root else None
    if hasattr(model, "settled_at"):
        model.settled_at = escrow.settled_at  # type: ignore[assignment]
    return model


# ── PostgresEscrowRepository ──────────────────────────────────────────────────


class PostgresEscrowRepository:
    """Implements IEscrowRepository using AsyncSession."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, escrow: Escrow) -> None:
        model = _escrow_to_model(escrow)
        self._session.add(model)
        await self._session.flush()

    async def get_by_id(self, escrow_id: uuid.UUID) -> Escrow | None:
        result = await self._session.get(EscrowContractModel, escrow_id)
        if result is None:
            return None
        return _model_to_escrow(result)

    async def get_by_session_id(self, session_id: uuid.UUID) -> Escrow | None:
        stmt = select(EscrowContractModel).where(
            EscrowContractModel.session_id == session_id
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return _model_to_escrow(model)

    async def update(self, escrow: Escrow) -> None:
        model = _escrow_to_model(escrow)
        await self._session.merge(model)
        await self._session.flush()

    async def list_by_status(
        self, status: EscrowStatus, limit: int, offset: int
    ) -> list[Escrow]:
        # FROZEN is stored as is_frozen=True; translate for query
        if status == EscrowStatus.FROZEN:
            stmt = (
                select(EscrowContractModel)
                .where(EscrowContractModel.is_frozen.is_(True))
                .limit(limit)
                .offset(offset)
            )
        else:
            stmt = (
                select(EscrowContractModel)
                .where(
                    EscrowContractModel.status == status.value,
                    EscrowContractModel.is_frozen.is_(False),
                )
                .limit(limit)
                .offset(offset)
            )
        result = await self._session.execute(stmt)
        return [_model_to_escrow(m) for m in result.scalars().all()]

    async def list_by_enterprise(
        self,
        enterprise_id: uuid.UUID,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[Escrow]:
        """List escrows where the calling enterprise is buyer or seller.

        Filters on the denormalized buyer_enterprise_id / seller_enterprise_id
        columns backfilled by migration backfill_escrow_enterprise_ids (Phase 1.1).
        An unscoped SELECT is never issued — every query is enterprise-isolated.
        """
        from sqlalchemy import or_

        stmt = select(EscrowContractModel).where(
            or_(
                EscrowContractModel.buyer_enterprise_id == enterprise_id,
                EscrowContractModel.seller_enterprise_id == enterprise_id,
            )
        )
        if status:
            stmt = stmt.where(EscrowContractModel.status == status)
        stmt = stmt.order_by(EscrowContractModel.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return [_model_to_escrow(m) for m in result.scalars().all()]

    async def list_pending_approval(self, limit: int = 50) -> list[Escrow]:
        """List all escrows in PENDING_APPROVAL or APPROVED state (admin queue).

        PENDING_APPROVAL = awaiting admin action.
        APPROVED         = admin approved, buyer hasn't deployed via Pera Wallet yet.
        Both are shown in the admin queue as actionable items.
        """
        from sqlalchemy import or_
        stmt = (
            select(EscrowContractModel)
            .where(
                or_(
                    EscrowContractModel.status == "PENDING_APPROVAL",
                    EscrowContractModel.status == "APPROVED",
                )
            )
            .order_by(EscrowContractModel.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [_model_to_escrow(m) for m in result.scalars().all()]



# ── SettlementModel ↔ Settlement ──────────────────────────────────────────────


def _model_to_settlement(model: SettlementModel) -> Settlement:
    s = Settlement(
        escrow_id=model.escrow_id,
        milestone_index=model.milestone_index,
        amount=MicroAlgo(value=model.amount_microalgo),
        tx_id=_make_txid_unchecked(model.tx_id) if model.tx_id else TxId(value="A" * 52),
        oracle_confirmation=model.oracle_confirmation,
        settled_at=(
            datetime.fromisoformat(model.created_at)
            if isinstance(model.created_at, str)
            else (model.created_at or datetime.now(tz=timezone.utc))
        ),
    )
    object.__setattr__(s, "id", model.id)
    return s


def _settlement_to_model(settlement: Settlement) -> SettlementModel:
    model = SettlementModel()
    model.id = settlement.id
    model.escrow_id = settlement.escrow_id
    model.milestone_index = settlement.milestone_index
    model.amount_microalgo = settlement.amount.value
    model.tx_id = settlement.tx_id.value
    model.oracle_confirmation = settlement.oracle_confirmation
    return model


# ── PostgresSettlementRepository ──────────────────────────────────────────────


class PostgresSettlementRepository:
    """Implements ISettlementRepository using AsyncSession."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, settlement: Settlement) -> None:
        model = _settlement_to_model(settlement)
        self._session.add(model)
        await self._session.flush()

    async def list_by_escrow(self, escrow_id: uuid.UUID) -> list[Settlement]:
        stmt = select(SettlementModel).where(SettlementModel.escrow_id == escrow_id)
        result = await self._session.execute(stmt)
        return [_model_to_settlement(m) for m in result.scalars().all()]
