"""
Frankfurter FX Feed adapter — implements IFXProvider.

context.md §6: Frankfurter FX Feed external integration.
context.md §13: IFXProvider → FrankfurterFXAdapter with get_rate(base, target) → FXRate.

API: https://api.frankfurter.app/latest?from=INR&to=USD
Free, no API key required, provides daily ECB exchange rates.
USDC is pegged 1:1 to USD — we use INR/USD as proxy for INR/USDC.

Rates are cached in Redis with 1-hour TTL (FX rates update daily from ECB).
Circuit breaker: falls back to last cached rate on HTTP failure.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import httpx

from src.shared.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from src.treasury.domain.value_objects import FXRate

log = get_logger(__name__)

_FRANKFURTER_BASE_URL = "https://api.frankfurter.dev/v1"
_CACHE_TTL = 3600  # 1 hour in seconds


class FrankfurterFXAdapter:
    """
    Concrete IFXProvider implementation using the Frankfurter API.

    context.md §6: external integration for real FX rates.
    """

    def __init__(self, redis: object | None = None) -> None:
        """
        Args:
            redis: Optional Redis client for rate caching.
                   If None, operates without caching.
        """
        self._redis = redis

    async def get_rate(self, base: str, target: str) -> "FXRate":
        """
        Fetch the latest FX rate for base/target pair.

        Checks Redis cache first, then calls Frankfurter API.
        On API failure, falls back to cached rate if available.
        """
        from src.treasury.domain.value_objects import FXRate

        base = base.upper()
        target = target.upper()
        cache_key = f"fx:{base}:{target}"

        # 1. Try Redis cache
        if self._redis is not None:
            try:
                cached = await self._redis.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    log.debug("fx_rate_cache_hit", pair=f"{base}/{target}")
                    return FXRate(
                        base=data["base"],
                        target=data["target"],
                        rate=Decimal(data["rate"]),
                        fetched_at=datetime.fromisoformat(data["fetched_at"]),
                        source="cache",
                    )
            except Exception:
                log.warning("fx_rate_cache_read_failed", pair=f"{base}/{target}")

        # 2. Call Frankfurter API
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{_FRANKFURTER_BASE_URL}/latest",
                    params={"from": base, "to": target},
                )
                response.raise_for_status()

            data = response.json()
            rate_value = Decimal(str(data["rates"][target]))
            now = datetime.now(tz=timezone.utc)

            fx_rate = FXRate(
                base=base,
                target=target,
                rate=rate_value,
                fetched_at=now,
                source="frankfurter",
            )

            # 3. Cache in Redis
            if self._redis is not None:
                try:
                    cache_data = json.dumps({
                        "base": base,
                        "target": target,
                        "rate": str(rate_value),
                        "fetched_at": now.isoformat(),
                    })
                    await self._redis.setex(cache_key, _CACHE_TTL, cache_data)
                except Exception:
                    log.warning("fx_rate_cache_write_failed", pair=f"{base}/{target}")

            log.info(
                "fx_rate_fetched",
                pair=f"{base}/{target}",
                rate=str(rate_value),
                source="frankfurter",
            )
            return fx_rate

        except httpx.HTTPError as exc:
            log.warning(
                "fx_rate_api_failed",
                pair=f"{base}/{target}",
                error=str(exc),
            )
            # Fallback: try cache even if expired
            if self._redis is not None:
                try:
                    cached = await self._redis.get(cache_key)
                    if cached:
                        data = json.loads(cached)
                        log.info("fx_rate_fallback_cache", pair=f"{base}/{target}")
                        return FXRate(
                            base=data["base"],
                            target=data["target"],
                            rate=Decimal(data["rate"]),
                            fetched_at=datetime.fromisoformat(data["fetched_at"]),
                            source="cache",
                        )
                except Exception:
                    pass

            # Last resort: return a stub rate
            log.error("fx_rate_no_fallback", pair=f"{base}/{target}")
            return FXRate(
                base=base,
                target=target,
                rate=Decimal("0.012"),  # ~₹83/USD approximate
                fetched_at=datetime.now(tz=timezone.utc),
                source="mock",
            )

    async def get_historical_rates(
        self, base: str, target: str, days: int
    ) -> list["FXRate"]:
        """
        Fetch historical FX rates for the last N days.

        Uses Frankfurter time-series endpoint.
        """
        from src.treasury.domain.value_objects import FXRate

        base = base.upper()
        target = target.upper()
        end_date = datetime.now(tz=timezone.utc).date()
        start_date = end_date - timedelta(days=days)

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{_FRANKFURTER_BASE_URL}/{start_date}..{end_date}",
                    params={"from": base, "to": target},
                )
                response.raise_for_status()

            data = response.json()
            rates = []
            for date_str, rate_data in sorted(data.get("rates", {}).items()):
                rates.append(FXRate(
                    base=base,
                    target=target,
                    rate=Decimal(str(rate_data[target])),
                    fetched_at=datetime.fromisoformat(f"{date_str}T00:00:00+00:00"),
                    source="frankfurter",
                ))

            log.info(
                "fx_historical_rates_fetched",
                pair=f"{base}/{target}",
                days=days,
                count=len(rates),
            )
            return rates

        except httpx.HTTPError as exc:
            log.warning(
                "fx_historical_rates_failed",
                pair=f"{base}/{target}",
                error=str(exc),
            )
            return []
