# context.md §4 DIP: dependencies wired here via FastAPI Depends().
# context.md §3: FastAPI imports ONLY in api/ layer.

from __future__ import annotations

import os

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.settlement.domain.ports import (
    IAnchorService,
    IBlockchainGateway,
    IEscrowRepository,
    IMerkleService,
    ISettlementRepository,
)
from src.settlement.infrastructure.algorand_gateway import AlgorandGateway
from src.settlement.infrastructure.anchor_service import AnchorService, _load_creator_sk
from src.settlement.infrastructure.repositories import (
    PostgresEscrowRepository,
    PostgresSettlementRepository,
)
from src.shared.infrastructure.db.session import get_db_session
from src.shared.infrastructure.db.uow import SqlAlchemyUnitOfWork
from src.shared.infrastructure.events.publisher import get_publisher
from src.shared.infrastructure.merkle_service import MerkleService as _SharedMerkleService

# ── Repository factories ──────────────────────────────────────────────────────


def get_escrow_repository(
    session: AsyncSession = Depends(get_db_session),
) -> IEscrowRepository:
    return PostgresEscrowRepository(session)


def get_settlement_repository(
    session: AsyncSession = Depends(get_db_session),
) -> ISettlementRepository:
    return PostgresSettlementRepository(session)


# ── Service factories ─────────────────────────────────────────────────────────


def get_merkle_service() -> IMerkleService:
    return _SharedMerkleService()  # type: ignore[return-value]


def get_blockchain_gateway() -> IBlockchainGateway:
    """
    Singleton-style: AlgorandGateway is expensive to init (loads keys, connects algod).
    In production, mount via app.state or use lru_cache. For Phase 2, construct each
    request (acceptable cost for low-volume blockchain operations).
    """
    return AlgorandGateway()


def get_anchor_service() -> IAnchorService:
    """
    Build AnchorService when ALGORAND_ESCROW_CREATOR_MNEMONIC is set.

    When no mnemonic is configured (Pera Wallet-only / buyer-funded mode), returns a
    no-op stub so that ALL escrow endpoints continue to work.  On-chain Merkle root
    anchoring is simply skipped.  Payment/funding is handled exclusively by the buyer's
    linked Pera Wallet — no platform mnemonic is required for that flow.
    """
    raw_mnemonic = os.environ.get("ALGORAND_ESCROW_CREATOR_MNEMONIC", "")
    if not raw_mnemonic:
        import structlog as _sl
        _sl.get_logger(__name__).info(
            "anchor_service_noop_mode",
            msg="ALGORAND_ESCROW_CREATOR_MNEMONIC not set — on-chain anchoring disabled. "
                "Pera Wallet buyer-funded flow is unaffected.",
        )
        return _NoOpAnchorService()  # type: ignore[return-value]

    from algosdk.v2client.algod import AlgodClient
    algod_address = os.environ.get("ALGORAND_ALGOD_ADDRESS", "https://testnet-api.4160.nodely.dev")
    algod_token = os.environ.get("ALGORAND_ALGOD_TOKEN", "")
    algod = AlgodClient(algod_token, algod_address)
    creator_sk = _load_creator_sk()
    return AnchorService(algod_client=algod, creator_sk=creator_sk)


# ── No-op stub — used when platform mnemonic is absent ───────────────────────

class _NoOpAnchorService:
    """
    Satisfies IAnchorService when ALGORAND_ESCROW_CREATOR_MNEMONIC is not set.

    Returns a sentinel TxId("noop-anchor") and logs a warning.
    All other settlement operations (create, read, fund via Pera Wallet) are
    completely unaffected.
    """

    async def anchor_root(self, merkle_root: object, session_id: object) -> object:
        import structlog as _sl
        _sl.get_logger(__name__).warning(
            "anchor_root_skipped",
            msg="No-op: platform mnemonic not configured — Merkle root NOT anchored on-chain.",
            session_id=str(session_id),
        )
        from src.settlement.domain.value_objects import TxId
        return TxId(value="noop-anchor")


# ── SettlementService factory ─────────────────────────────────────────────────


def get_settlement_service(
    session: AsyncSession = Depends(get_db_session),
    escrow_repo: IEscrowRepository = Depends(get_escrow_repository),
    settlement_repo: ISettlementRepository = Depends(get_settlement_repository),
    merkle_service: IMerkleService = Depends(get_merkle_service),
) -> "SettlementServiceDep":
    """Wire SettlementService with all concrete adapters."""
    from src.settlement.application.services import SettlementService

    return SettlementService(
        escrow_repo=escrow_repo,
        settlement_repo=settlement_repo,
        blockchain_gateway=get_blockchain_gateway(),
        merkle_service=merkle_service,
        anchor_service=get_anchor_service(),
        event_publisher=get_publisher(),
        uow=SqlAlchemyUnitOfWork(session),
    )


# Type alias for mypy
from src.settlement.application.services import (
    SettlementService as SettlementServiceDep,  # noqa: E402
)
