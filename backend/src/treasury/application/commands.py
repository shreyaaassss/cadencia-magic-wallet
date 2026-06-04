# context.md §3 — Application layer: orchestrates domain entities via ports.
# context.md §4.2 — Treasury bounded context commands and queries.
# No framework imports — pure Python dataclasses.

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

# ── Commands ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RecordDepositCommand:
    """Record a deposit into an enterprise's liquidity pool."""

    enterprise_id: uuid.UUID
    currency: str  # "INR", "USDC", "ALGO"
    amount: Decimal


@dataclass(frozen=True)
class RecordWithdrawalCommand:
    """Record a withdrawal from an enterprise's liquidity pool."""

    enterprise_id: uuid.UUID
    currency: str  # "INR", "USDC", "ALGO"
    amount: Decimal


@dataclass(frozen=True)
class UpdateFXRateCommand:
    """Fetch and update the latest FX rate from the provider."""

    enterprise_id: uuid.UUID
    base: str = "INR"
    target: str = "USD"


@dataclass(frozen=True)
class OpenFXPositionCommand:
    """Open a new FX exposure position."""

    enterprise_id: uuid.UUID
    currency_pair: str
    direction: str  # "LONG" or "SHORT"
    notional_amount: Decimal
    entry_rate: Decimal


@dataclass(frozen=True)
class CloseFXPositionCommand:
    """Close an existing FX position."""

    position_id: uuid.UUID
    enterprise_id: uuid.UUID


# ── Queries ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GetDashboardQuery:
    """Get treasury dashboard data for an enterprise."""

    enterprise_id: uuid.UUID


@dataclass(frozen=True)
class GetFXExposureQuery:
    """Get all open FX positions for an enterprise."""

    enterprise_id: uuid.UUID


@dataclass(frozen=True)
class GetLiquidityForecastQuery:
    """Get 30-day liquidity runway forecast for an enterprise."""

    enterprise_id: uuid.UUID
    forecast_days: int = 30
