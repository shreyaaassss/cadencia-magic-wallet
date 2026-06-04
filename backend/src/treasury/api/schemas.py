"""
Pydantic schemas for the treasury API layer.

context.md §10: All responses use ApiResponse[T] envelope.
context.md §4.2: Treasury bounded context API schemas.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ── Response Schemas ──────────────────────────────────────────────────────────


class FXRateInfo(BaseModel):
    """Current FX rate snapshot."""

    INR_USD: str = Field(description="INR/USD exchange rate")
    updated_at: str = Field(description="ISO 8601 timestamp of last rate update")


class DashboardResponse(BaseModel):
    """Treasury dashboard data for an enterprise."""

    inr_pool_balance: str = Field(description="INR pool balance")
    usdc_pool_balance: str = Field(description="USDC pool balance")
    algo_pool_balance_microalgo: int = Field(description="ALGO balance in microALGO")
    algo_pool_balance_algo: str = Field(description="ALGO balance in ALGO")
    current_fx_rate: FXRateInfo
    total_value_inr: str = Field(description="Estimated total pool value in INR")
    open_fx_positions: int = Field(description="Number of open FX positions")


class FXPositionItem(BaseModel):
    """Single FX exposure position."""

    position_id: str
    pair: str
    direction: str
    notional: str
    entry_rate: str
    current_rate: str
    unrealized_pnl: str


class FXExposureResponse(BaseModel):
    """FX exposure summary for an enterprise."""

    open_positions: list[FXPositionItem] = Field(default_factory=list)
    total_unrealized_pnl: str
    position_count: int


class ForecastDay(BaseModel):
    """Single day in the liquidity forecast."""

    date: str
    projected_inr_balance: str
    projected_usdc_balance: str


class LiquidityForecastResponse(BaseModel):
    """30-day liquidity runway forecast."""

    forecast: list[ForecastDay] = Field(default_factory=list)
    runway_days: int = Field(description="Estimated days until INR runs out")
    alert: str | None = Field(default=None, description="Warning if runway is low")
    current_inr_balance: str
    current_usdc_balance: str
    estimated_daily_burn_inr: str
