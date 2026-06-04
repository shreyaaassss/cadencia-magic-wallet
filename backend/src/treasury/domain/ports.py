# context.md §3 — Hexagonal Architecture: Protocol interfaces ONLY here.
# context.md §4.2 — Treasury bounded context ports.
# No concrete classes. No algosdk, sqlalchemy, fastapi, httpx imports.

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from src.treasury.domain.fx_position import FXPosition
from src.treasury.domain.liquidity_pool import LiquidityPool
from src.treasury.domain.value_objects import FXRate

# ── Repository Ports ──────────────────────────────────────────────────────────


@runtime_checkable
class ILiquidityRepository(Protocol):
    """Port for LiquidityPool persistence. context.md §13."""

    async def save(self, pool: LiquidityPool) -> None: ...
    async def get_by_enterprise_id(self, enterprise_id: uuid.UUID) -> LiquidityPool | None: ...
    async def update(self, pool: LiquidityPool) -> None: ...


@runtime_checkable
class IFXPositionRepository(Protocol):
    """Port for FXPosition persistence."""

    async def save(self, position: FXPosition) -> None: ...
    async def get_by_id(self, position_id: uuid.UUID) -> FXPosition | None: ...
    async def list_open_by_enterprise(
        self, enterprise_id: uuid.UUID
    ) -> list[FXPosition]: ...
    async def update(self, position: FXPosition) -> None: ...


# ── FX Provider Port ─────────────────────────────────────────────────────────


@runtime_checkable
class IFXProvider(Protocol):
    """
    Port for FX rate retrieval.

    context.md §6: Frankfurter FX Feed external integration.
    context.md §13: IFXProvider → FrankfurterFXAdapter.
    """

    async def get_rate(self, base: str, target: str) -> FXRate: ...
    async def get_historical_rates(
        self, base: str, target: str, days: int
    ) -> list[FXRate]: ...
