# context.md §3: FastAPI imports ONLY in api/ layer.
# context.md §4 DIP: dependencies wired here; injected into service via Depends().

from __future__ import annotations

import os

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.infrastructure.cache.redis_client import get_redis
from src.shared.infrastructure.db.session import get_db_session
from src.shared.infrastructure.logging import get_logger
from src.treasury.application.services import TreasuryService
from src.treasury.infrastructure.frankfurter_fx_adapter import FrankfurterFXAdapter
from src.treasury.infrastructure.repositories import (
    PostgresFXPositionRepository,
    PostgresLiquidityRepository,
)

log = get_logger(__name__)


def _get_payment_provider(fx_provider=None):
    """
    Select on-ramp payment provider based on ONRAMP_PROVIDER.

    Production: uses MoonPayOnRampAdapter for real INR ↔ USDC conversions.
    Development: uses MockOnRampAdapter with optional FX rates.

    Environment Variables:
        APP_ENV:          'production' | 'development' (default)
        ONRAMP_PROVIDER:  'moonpay' | 'mock' (default)
        ONRAMP_API_KEY:   MoonPay publishable API key
        ONRAMP_API_SECRET: MoonPay secret key (for webhooks)
    """
    onramp_provider = os.environ.get("ONRAMP_PROVIDER", "mock")
    app_env = os.environ.get("APP_ENV", "development")

    if onramp_provider == "moonpay":
        api_key = os.environ.get("ONRAMP_API_KEY", "")
        if not api_key:
            log.warning(
                "moonpay_api_key_missing",
                hint="Set ONRAMP_API_KEY for MoonPay integration",
            )
            from src.settlement.infrastructure.onramp_adapter import MockOnRampAdapter
            return MockOnRampAdapter(fx_provider=fx_provider)
        from src.settlement.infrastructure.moonpay_onramp_adapter import MoonPayOnRampAdapter
        is_sandbox = app_env != "production"
        return MoonPayOnRampAdapter(
            api_key=api_key,
            api_secret=os.environ.get("ONRAMP_API_SECRET"),
            sandbox=is_sandbox,
        )

    if app_env == "production" and onramp_provider == "mock":
        log.warning(
            "onramp_mock_in_production",
            hint="Set ONRAMP_PROVIDER=moonpay and provide ONRAMP_API_KEY",
        )

    from src.settlement.infrastructure.onramp_adapter import MockOnRampAdapter
    return MockOnRampAdapter(fx_provider=fx_provider)


def get_treasury_service(
    session: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),  # type: ignore[type-arg]
) -> TreasuryService:
    """Build TreasuryService with all concrete adapters wired."""
    fx_adapter = FrankfurterFXAdapter(redis=redis)
    return TreasuryService(
        liquidity_repo=PostgresLiquidityRepository(session),
        fx_position_repo=PostgresFXPositionRepository(session),
        fx_provider=fx_adapter,
        payment_provider=_get_payment_provider(fx_provider=fx_adapter),
    )
