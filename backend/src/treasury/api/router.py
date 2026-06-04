# context.md §10: All endpoints versioned under /v1/.
# context.md §10: All responses use ApiResponse[T] envelope.
# context.md §4.2: Treasury bounded context API — 3 endpoints.

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.identity.api.dependencies import get_current_user, rate_limit
from src.identity.domain.user import User
from src.shared.api.responses import ApiResponse, success_response
from src.shared.infrastructure.logging import get_logger
from src.treasury.api.dependencies import get_treasury_service
from src.treasury.api.schemas import (
    DashboardResponse,
    ForecastDay,
    FXExposureResponse,
    FXPositionItem,
    FXRateInfo,
    LiquidityForecastResponse,
)
from src.treasury.application.commands import (
    GetDashboardQuery,
    GetFXExposureQuery,
    GetLiquidityForecastQuery,
)
from src.treasury.application.services import TreasuryService

log = get_logger(__name__)

router = APIRouter(prefix="/v1/treasury", tags=["treasury"])


# ── GET /v1/treasury/dashboard ────────────────────────────────────────────────


@router.get(
    "/dashboard",
    response_model=ApiResponse[DashboardResponse],
    summary="Get treasury dashboard — pool balances and FX rates",
    dependencies=[Depends(rate_limit)],
)
async def get_dashboard(
    current_user: User = Depends(get_current_user),
    svc: TreasuryService = Depends(get_treasury_service),
) -> ApiResponse[DashboardResponse]:
    data = await svc.get_dashboard(
        GetDashboardQuery(enterprise_id=current_user.enterprise_id)
    )
    return success_response(
        DashboardResponse(
            inr_pool_balance=data["inr_pool_balance"],
            usdc_pool_balance=data["usdc_pool_balance"],
            algo_pool_balance_microalgo=data["algo_pool_balance_microalgo"],
            algo_pool_balance_algo=data["algo_pool_balance_algo"],
            current_fx_rate=FXRateInfo(**data["current_fx_rate"]),
            total_value_inr=data["total_value_inr"],
            open_fx_positions=data["open_fx_positions"],
        )
    )


# ── GET /v1/treasury/fx-exposure ──────────────────────────────────────────────


@router.get(
    "/fx-exposure",
    response_model=ApiResponse[FXExposureResponse],
    summary="Get open FX positions and total exposure",
    dependencies=[Depends(rate_limit)],
)
async def get_fx_exposure(
    current_user: User = Depends(get_current_user),
    svc: TreasuryService = Depends(get_treasury_service),
) -> ApiResponse[FXExposureResponse]:
    data = await svc.get_fx_exposure(
        GetFXExposureQuery(enterprise_id=current_user.enterprise_id)
    )
    return success_response(
        FXExposureResponse(
            open_positions=[FXPositionItem(**p) for p in data["open_positions"]],
            total_unrealized_pnl=data["total_unrealized_pnl"],
            position_count=data["position_count"],
        )
    )


# ── GET /v1/treasury/liquidity-forecast ───────────────────────────────────────


@router.get(
    "/liquidity-forecast",
    response_model=ApiResponse[LiquidityForecastResponse],
    summary="Get 30-day liquidity runway forecast",
    dependencies=[Depends(rate_limit)],
)
async def get_liquidity_forecast(
    current_user: User = Depends(get_current_user),
    svc: TreasuryService = Depends(get_treasury_service),
) -> ApiResponse[LiquidityForecastResponse]:
    data = await svc.get_liquidity_forecast(
        GetLiquidityForecastQuery(enterprise_id=current_user.enterprise_id)
    )
    return success_response(
        LiquidityForecastResponse(
            forecast=[ForecastDay(**f) for f in data["forecast"]],
            runway_days=data["runway_days"],
            alert=data["alert"],
            current_inr_balance=data["current_inr_balance"],
            current_usdc_balance=data["current_usdc_balance"],
            estimated_daily_burn_inr=data["estimated_daily_burn_inr"],
        )
    )
