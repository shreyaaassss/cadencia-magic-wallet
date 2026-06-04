# context.md §3 — Hexagonal Architecture: Protocol interfaces ONLY here.
# No concrete classes. No algosdk, sqlalchemy, fastapi imports.
# AlgorandGateway, Repositories, MerkleService live ONLY in infrastructure/.

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Protocol, runtime_checkable

from src.settlement.domain.escrow import Escrow, EscrowStatus
from src.settlement.domain.settlement import Settlement
from src.settlement.domain.value_objects import MerkleRoot, TxId
from src.shared.domain.protocols import IMerkleService  # noqa: F401 — re-exported for callers

# ── Repository Ports ──────────────────────────────────────────────────────────


@runtime_checkable
class IEscrowRepository(Protocol):
    async def save(self, escrow: Escrow) -> None: ...
    async def get_by_id(self, escrow_id: uuid.UUID) -> Escrow | None: ...
    async def get_by_session_id(self, session_id: uuid.UUID) -> Escrow | None: ...
    async def update(self, escrow: Escrow) -> None: ...
    async def list_by_status(
        self, status: EscrowStatus, limit: int, offset: int
    ) -> list[Escrow]: ...
    async def list_by_enterprise(
        self, enterprise_id: uuid.UUID, status: str | None, limit: int, offset: int,
    ) -> list[Escrow]: ...


@runtime_checkable
class ISettlementRepository(Protocol):
    async def save(self, settlement: Settlement) -> None: ...
    async def list_by_escrow(self, escrow_id: uuid.UUID) -> list[Settlement]: ...


# ── Blockchain Gateway Port ───────────────────────────────────────────────────


@runtime_checkable
class IBlockchainGateway(Protocol):
    """
    Abstraction over all Algorand contract interactions.
    context.md §4.4: domain NEVER calls algosdk directly — only through this port.
    """

    async def deploy_escrow(
        self,
        buyer_address: str,
        seller_address: str,
        amount_microalgo: int,
        session_id: str,
    ) -> dict:
        """Returns: {"app_id": int, "app_address": str, "tx_id": str}"""
        ...

    async def fund_escrow(
        self,
        app_id: int,
        app_address: str,
        amount_microalgo: int,
        funder_sk: str,
    ) -> dict:
        """Returns: {"tx_id": str, "confirmed_round": int}"""
        ...

    async def release_escrow(
        self,
        app_id: int,
        merkle_root: str,
    ) -> dict:
        """Returns: {"tx_id": str, "confirmed_round": int}"""
        ...

    async def refund_escrow(
        self,
        app_id: int,
        reason: str,
    ) -> dict:
        """Returns: {"tx_id": str, "confirmed_round": int}"""
        ...

    async def freeze_escrow(self, app_id: int) -> dict:
        """Returns: {"tx_id": str}"""
        ...

    async def unfreeze_escrow(self, app_id: int) -> dict:
        """Returns: {"tx_id": str}"""
        ...

    async def get_app_state(self, app_id: int) -> dict:
        """
        Returns on-chain global state decoded as:
          {"status": int, "frozen": int, "buyer": str, "seller": str, "amount": int}
        """
        ...


# ── Merkle Service Port ───────────────────────────────────────────────────────
# IMerkleService is now defined in shared/domain/protocols.py (Phase 3 refactor).
# Re-exported above via noqa F401 for backward compatibility with existing imports.
# New code should import from src.shared.domain.protocols directly.


# ── Anchor Service Port ───────────────────────────────────────────────────────


@runtime_checkable
class IAnchorService(Protocol):
    async def anchor_root(
        self, merkle_root: MerkleRoot, session_id: uuid.UUID
    ) -> TxId: ...


# ── Payment Provider Port ─────────────────────────────────────────────────────


@runtime_checkable
class IPaymentProvider(Protocol):
    """
    Port for INR ↔ USDC on/off-ramp conversions.

    context.md §13: OnRampAdapter — convert_inr_to_usdc, convert_usdc_to_inr.
    Concrete adapter: src/settlement/infrastructure/onramp_adapter.py
    """

    async def get_exchange_rate(self, from_ccy: str, to_ccy: str) -> Decimal: ...
    async def convert_inr_to_usdc(
        self, amount_inr: Decimal, enterprise_id: "uuid.UUID"
    ) -> dict: ...
    async def convert_usdc_to_inr(
        self, amount_usdc: Decimal, enterprise_id: "uuid.UUID"
    ) -> dict: ...

