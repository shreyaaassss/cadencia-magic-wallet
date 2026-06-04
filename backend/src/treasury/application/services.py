# context.md §3 — Application layer: orchestration only.
# context.md §4.2 — Treasury bounded context application service.

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from src.shared.infrastructure.logging import get_logger
from src.treasury.application.commands import (
    CloseFXPositionCommand,
    GetDashboardQuery,
    GetFXExposureQuery,
    GetLiquidityForecastQuery,
    OpenFXPositionCommand,
    RecordDepositCommand,
    RecordWithdrawalCommand,
    UpdateFXRateCommand,
)
from src.treasury.domain.fx_position import FXPosition
from src.treasury.domain.liquidity_pool import LiquidityPool
from src.treasury.domain.ports import IFXPositionRepository, IFXProvider, ILiquidityRepository

log = get_logger(__name__)


class TreasuryService:
    """
    Application service for the treasury bounded context.

    Orchestrates domain entities via injected port implementations.
    context.md §3: application layer ONLY calls domain entities + ports.
    """

    def __init__(
        self,
        liquidity_repo: ILiquidityRepository,
        fx_position_repo: IFXPositionRepository,
        fx_provider: IFXProvider,
        payment_provider: object | None = None,
    ) -> None:
        self._liquidity_repo = liquidity_repo
        self._fx_position_repo = fx_position_repo
        self._fx_provider = fx_provider
        self._fx_adapter = fx_provider  # Alias for backward compat in _estimate_daily_burn
        self._payment_provider = payment_provider  # On/off-ramp adapter (MockOnRampAdapter or production)

    # ── Commands ──────────────────────────────────────────────────────────────

    async def record_deposit(self, cmd: RecordDepositCommand) -> dict[str, Any]:
        """Record a deposit into an enterprise's liquidity pool."""
        pool = await self._get_or_create_pool(cmd.enterprise_id)

        if cmd.currency == "INR":
            pool.deposit_inr(cmd.amount)
        elif cmd.currency == "USDC":
            pool.deposit_usdc(cmd.amount)
        elif cmd.currency == "ALGO":
            pool.deposit_algo(int(cmd.amount))
        else:
            from src.shared.domain.exceptions import ValidationError
            raise ValidationError(
                f"Unsupported currency: {cmd.currency}", field="currency"
            )

        await self._liquidity_repo.update(pool)
        log.info(
            "deposit_recorded",
            enterprise_id=str(cmd.enterprise_id),
            currency=cmd.currency,
            amount=str(cmd.amount),
        )
        return {"enterprise_id": cmd.enterprise_id, "currency": cmd.currency, "amount": cmd.amount}

    async def record_withdrawal(self, cmd: RecordWithdrawalCommand) -> dict[str, Any]:
        """Record a withdrawal from an enterprise's liquidity pool."""
        pool = await self._get_or_create_pool(cmd.enterprise_id)

        if cmd.currency == "INR":
            pool.withdraw_inr(cmd.amount)
        elif cmd.currency == "USDC":
            pool.withdraw_usdc(cmd.amount)
        elif cmd.currency == "ALGO":
            pool.withdraw_algo(int(cmd.amount))
        else:
            from src.shared.domain.exceptions import ValidationError
            raise ValidationError(
                f"Unsupported currency: {cmd.currency}", field="currency"
            )

        await self._liquidity_repo.update(pool)
        log.info(
            "withdrawal_recorded",
            enterprise_id=str(cmd.enterprise_id),
            currency=cmd.currency,
            amount=str(cmd.amount),
        )
        return {"enterprise_id": cmd.enterprise_id, "currency": cmd.currency, "amount": cmd.amount}

    async def update_fx_rate(self, cmd: UpdateFXRateCommand) -> dict[str, Any]:
        """Fetch latest FX rate and update the pool."""
        pool = await self._get_or_create_pool(cmd.enterprise_id)
        fx_rate = await self._fx_provider.get_rate(cmd.base, cmd.target)

        event = pool.update_fx_rate(fx_rate.rate)
        await self._liquidity_repo.update(pool)

        # Update all open FX positions with new rate
        open_positions = await self._fx_position_repo.list_open_by_enterprise(
            cmd.enterprise_id
        )
        for pos in open_positions:
            if pos.currency_pair == f"{cmd.base}/{cmd.target}":
                pos.update_current_rate(fx_rate.rate)
                await self._fx_position_repo.update(pos)

        log.info(
            "fx_rate_updated",
            enterprise_id=str(cmd.enterprise_id),
            pair=fx_rate.pair,
            rate=str(fx_rate.rate),
            source=fx_rate.source,
        )
        return {
            "pair": fx_rate.pair,
            "rate": str(fx_rate.rate),
            "source": fx_rate.source,
            "old_rate": str(event.old_rate),
        }

    async def open_fx_position(self, cmd: OpenFXPositionCommand) -> dict[str, Any]:
        """Open a new FX exposure position."""
        position = FXPosition(
            enterprise_id=cmd.enterprise_id,
            currency_pair=cmd.currency_pair,
            direction=cmd.direction,
            notional_amount=cmd.notional_amount,
            entry_rate=cmd.entry_rate,
            current_rate=cmd.entry_rate,
        )
        await self._fx_position_repo.save(position)
        log.info(
            "fx_position_opened",
            position_id=str(position.id),
            enterprise_id=str(cmd.enterprise_id),
            pair=cmd.currency_pair,
            direction=cmd.direction,
        )
        return {"position_id": position.id}

    async def close_fx_position(self, cmd: CloseFXPositionCommand) -> dict[str, Any]:
        """Close an FX position and realize PnL."""
        from src.shared.domain.exceptions import NotFoundError

        position = await self._fx_position_repo.get_by_id(cmd.position_id)
        if position is None or position.enterprise_id != cmd.enterprise_id:
            raise NotFoundError("FXPosition", cmd.position_id)

        realized_pnl = position.close()
        await self._fx_position_repo.update(position)
        log.info(
            "fx_position_closed",
            position_id=str(cmd.position_id),
            realized_pnl=str(realized_pnl),
        )
        return {"position_id": cmd.position_id, "realized_pnl": str(realized_pnl)}

    # ── Queries ───────────────────────────────────────────────────────────────

    async def get_dashboard(self, query: GetDashboardQuery) -> dict[str, Any]:
        """Get treasury dashboard data."""
        pool = await self._get_or_create_pool(query.enterprise_id)

        # Try to fetch latest FX rate
        try:
            fx_rate = await self._fx_provider.get_rate("INR", "USD")
            current_fx = {"INR_USD": str(fx_rate.rate), "updated_at": fx_rate.fetched_at.isoformat()}
        except Exception:
            current_fx = {
                "INR_USD": str(pool.last_fx_rate_inr_usd),
                "updated_at": pool.last_rate_updated_at.isoformat(),
            }

        # Count open FX positions
        open_positions = await self._fx_position_repo.list_open_by_enterprise(
            query.enterprise_id
        )

        return {
            "inr_pool_balance": str(pool.inr_balance),
            "usdc_pool_balance": str(pool.usdc_balance),
            "algo_pool_balance_microalgo": pool.algo_balance_microalgo,
            "algo_pool_balance_algo": str(pool.algo_balance_algo),
            "current_fx_rate": current_fx,
            "total_value_inr": str(pool.total_value_inr),
            "open_fx_positions": len(open_positions),
        }

    async def get_fx_exposure(self, query: GetFXExposureQuery) -> dict[str, Any]:
        """Get all open FX positions and total exposure."""
        positions = await self._fx_position_repo.list_open_by_enterprise(
            query.enterprise_id
        )

        position_list = []
        total_unrealized_pnl = Decimal("0")
        for pos in positions:
            pnl = pos.unrealized_pnl
            total_unrealized_pnl += pnl
            position_list.append({
                "position_id": str(pos.id),
                "pair": pos.currency_pair,
                "direction": pos.direction,
                "notional": str(pos.notional_amount),
                "entry_rate": str(pos.entry_rate),
                "current_rate": str(pos.current_rate),
                "unrealized_pnl": str(pnl),
            })

        return {
            "open_positions": position_list,
            "total_unrealized_pnl": str(total_unrealized_pnl),
            "position_count": len(positions),
        }

    async def get_liquidity_forecast(
        self, query: GetLiquidityForecastQuery
    ) -> dict[str, Any]:
        """
        Generate a 30-day liquidity runway forecast.

        Uses actual historical settlement data to compute daily burn rate.
        Falls back to 2% of balance if no settlement history exists.
        """
        pool = await self._get_or_create_pool(query.enterprise_id)

        # Query real settlement history for burn rate estimation
        daily_burn_inr = await self._estimate_daily_burn(
            query.enterprise_id, pool.inr_balance
        )
        daily_burn_usdc = pool.usdc_balance * Decimal("0.02")  # USDC: flat 2% until stablecoin pipeline matures

        forecast: list[dict[str, Any]] = []
        projected_inr = pool.inr_balance
        projected_usdc = pool.usdc_balance

        now = datetime.now(tz=timezone.utc)
        for day_offset in range(1, query.forecast_days + 1):
            projected_inr = max(Decimal("0"), projected_inr - daily_burn_inr)
            projected_usdc = max(Decimal("0"), projected_usdc - daily_burn_usdc)
            forecast.append({
                "date": (now + timedelta(days=day_offset)).strftime("%Y-%m-%d"),
                "projected_inr_balance": str(projected_inr.quantize(Decimal("0.01"))),
                "projected_usdc_balance": str(projected_usdc.quantize(Decimal("0.01"))),
            })

        # Calculate runway (days until INR drops to zero)
        runway_days = (
            int(pool.inr_balance / daily_burn_inr) if daily_burn_inr > 0 else 999
        )

        alert = None
        if runway_days < 7:
            alert = "CRITICAL: Less than 7 days of INR liquidity remaining"
        elif runway_days < 14:
            alert = "WARNING: Less than 14 days of INR liquidity remaining"

        return {
            "forecast": forecast,
            "runway_days": min(runway_days, 999),
            "alert": alert,
            "current_inr_balance": str(pool.inr_balance),
            "current_usdc_balance": str(pool.usdc_balance),
            "estimated_daily_burn_inr": str(daily_burn_inr.quantize(Decimal("0.01"))),
        }

    async def _estimate_daily_burn(
        self, enterprise_id: uuid.UUID, current_balance: Decimal
    ) -> Decimal:
        """
        Estimate daily INR burn from real settlement history.

        Queries the average daily settlement volume (microALGO * FX rate)
        for escrows where this enterprise is buyer, over the last 30 days.
        Falls back to 2% of current balance if no data exists.
        """
        try:
            from sqlalchemy import text

            from src.shared.infrastructure.db.session import get_session_factory

            async with get_session_factory()() as db_session:
                result = await db_session.execute(text(
                    "SELECT COALESCE("
                    "  SUM(e.amount_microalgo) / 1000000.0 / "
                    "  GREATEST(EXTRACT(DAY FROM (NOW() - MIN(e.created_at))), 1), "
                    "  0"
                    ") as avg_daily_algo "
                    "FROM escrows e "
                    "JOIN negotiation_sessions ns ON ns.id = e.session_id "
                    "WHERE (ns.buyer_enterprise_id = :eid OR ns.seller_enterprise_id = :eid) "
                    "AND e.created_at >= NOW() - INTERVAL '30 days' "
                    "AND e.status IN ('FUNDED', 'RELEASED')"
                ), {"eid": str(enterprise_id)})

                row = result.one_or_none()
                if row and row.avg_daily_algo and Decimal(str(row.avg_daily_algo)) > 0:
                    # Convert ALGO to INR using current FX rate
                    try:
                        fx_rate = await self._fx_adapter.get_rate("USD", "INR")
                        algo_to_inr = fx_rate.rate  # approximate: 1 ALGO ≈ 1 USD
                    except Exception:
                        algo_to_inr = Decimal("85")  # fallback INR/USD

                    return (Decimal(str(row.avg_daily_algo)) * algo_to_inr).quantize(
                        Decimal("0.01")
                    )
        except Exception:
            pass

        # Fallback: 2% of current balance
        return current_balance * Decimal("0.02")

    # ── Internal Helpers ──────────────────────────────────────────────────────

    async def _get_or_create_pool(self, enterprise_id: uuid.UUID) -> LiquidityPool:
        """Get existing pool or create a new empty one."""
        pool = await self._liquidity_repo.get_by_enterprise_id(enterprise_id)
        if pool is None:
            pool = LiquidityPool(enterprise_id=enterprise_id)
            await self._liquidity_repo.save(pool)
        return pool
