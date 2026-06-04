# context.md §13: OnRampAdapter — convert_inr_to_usdc, convert_usdc_to_inr.
# context.md §6: On/Off-Ramp Provider listed as external integration.
# context.md §4 OCP: New on-ramp provider = new adapter file. Zero modification to TreasuryService.
#
# MoonPay production adapter for INR ↔ USDC on/off-ramp conversions.
# Uses MoonPay Buy/Sell API with webhook-based settlement confirmation.

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from src.shared.domain.exceptions import DomainError
from src.shared.infrastructure.logging import get_logger
from src.shared.infrastructure.metrics import ONRAMP_CONVERSIONS_TOTAL
from src.treasury.domain.value_objects import ConversionResult

log = get_logger(__name__)

# MoonPay API base URLs
_SANDBOX_BASE = "https://api.sandbox.moonpay.com"
_PRODUCTION_BASE = "https://api.moonpay.com"

# Retry configuration
_MAX_RETRIES = 3
_RETRY_DELAYS = [1.0, 2.0, 4.0]

# Fee structure (MoonPay charges ~1-4.5% depending on payment method)
_DEFAULT_FEE_PCT = Decimal("0.035")  # 3.5% default estimate


class OnRampProviderError(DomainError):
    """Raised when MoonPay API returns an error or is unreachable."""
    error_code = "ONRAMP_PROVIDER_ERROR"


class MoonPayOnRampAdapter:
    """
    MoonPay on/off-ramp adapter — implements IPaymentProvider Protocol.

    Handles INR ↔ USDC conversions via MoonPay's Buy and Sell APIs.
    Supports both sandbox (test) and production modes.

    Required Environment Variables:
        ONRAMP_API_KEY:         MoonPay publishable API key
        ONRAMP_API_SECRET:      MoonPay secret key (for webhook verification)
        APP_ENV:                'production' or 'development' (default)

    Flow:
        1. get_exchange_rate()    → Fetch live INR/USD rate from MoonPay
        2. convert_inr_to_usdc() → Initiate buy order (INR → USDC)
        3. convert_usdc_to_inr() → Initiate sell order (USDC → INR)
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str | None = None,
        sandbox: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret or os.environ.get("ONRAMP_API_SECRET", "")
        self._base_url = _SANDBOX_BASE if sandbox else _PRODUCTION_BASE
        self._timeout = timeout
        self._circuit_open = False
        self._consecutive_failures = 0
        self._circuit_threshold = 5
        # Rate cache (avoid hitting API for every request)
        self._rate_cache: dict[str, tuple[Decimal, float]] = {}
        self._cache_ttl = 60.0  # 60 seconds

    async def get_exchange_rate(self, from_ccy: str, to_ccy: str) -> Decimal:
        """
        Fetch live exchange rate from MoonPay.

        Falls back to cached rate if API is unreachable.
        Falls back to hardcoded rate as last resort.
        """
        cache_key = f"{from_ccy.upper()}_{to_ccy.upper()}"
        now = datetime.now(tz=timezone.utc).timestamp()

        # Check cache
        if cache_key in self._rate_cache:
            cached_rate, cached_at = self._rate_cache[cache_key]
            if now - cached_at < self._cache_ttl:
                return cached_rate

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                # MoonPay quotes endpoint
                response = await client.get(
                    f"{self._base_url}/v3/currencies/usdc/quote",
                    params={
                        "apiKey": self._api_key,
                        "baseCurrencyCode": from_ccy.lower(),
                        "baseCurrencyAmount": "1000",  # Quote for 1000 units
                        "areFeesIncluded": "false",
                    },
                )

            if response.status_code == 200:
                data = response.json()
                quote_amount = Decimal(str(data.get("quoteCurrencyAmount", "0")))
                base_amount = Decimal(str(data.get("baseCurrencyAmount", "1000")))
                if base_amount > 0 and quote_amount > 0:
                    rate = quote_amount / base_amount
                    self._rate_cache[cache_key] = (rate, now)
                    return rate

        except Exception as e:
            log.warning(
                "moonpay_rate_fetch_failed",
                from_ccy=from_ccy,
                to_ccy=to_ccy,
                error=str(e),
            )

        # Fallback rates
        if from_ccy.upper() == "INR" and to_ccy.upper() in ("USD", "USDC"):
            return Decimal("0.012")  # ~₹83/USD
        if from_ccy.upper() in ("USD", "USDC") and to_ccy.upper() == "INR":
            return Decimal("83.0")
        return Decimal("1")

    async def convert_inr_to_usdc(
        self,
        amount_inr: Decimal,
        enterprise_id: uuid.UUID,
    ) -> ConversionResult:
        """
        Initiate INR → USDC buy order via MoonPay.

        Creates a MoonPay transaction for the enterprise, applying
        current exchange rates and MoonPay's fee structure.

        Args:
            amount_inr: Amount in INR to convert.
            enterprise_id: UUID of the enterprise making the conversion.

        Returns:
            ConversionResult with amounts, rate, fee, and tx reference.

        Raises:
            OnRampProviderError: On API failure after retries.
        """
        if self._circuit_open:
            raise OnRampProviderError(
                "MoonPay circuit breaker is open — service temporarily unavailable"
            )

        rate = await self.get_exchange_rate("INR", "USDC")
        gross_usdc = amount_inr * rate
        fee = gross_usdc * _DEFAULT_FEE_PCT
        net_usdc = gross_usdc - fee

        payload = {
            "apiKey": self._api_key,
            "currencyCode": "usdc",
            "baseCurrencyCode": "inr",
            "baseCurrencyAmount": str(amount_inr),
            "walletAddress": "",  # Set by enterprise's linked wallet
            "externalCustomerId": str(enterprise_id),
        }

        last_error: Exception | None = None
        for attempt, delay in enumerate([0.0] + list(_RETRY_DELAYS)):
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        f"{self._base_url}/v3/transactions",
                        json=payload,
                        headers={
                            "Authorization": f"Api-Key {self._api_key}",
                            "Content-Type": "application/json",
                        },
                    )

                if response.status_code in (200, 201):
                    data = response.json()
                    tx_id = data.get("id", str(uuid.uuid4()))
                    actual_usdc = Decimal(
                        str(data.get("quoteCurrencyAmount", net_usdc))
                    )
                    actual_fee = Decimal(str(data.get("feeAmount", fee)))

                    self._consecutive_failures = 0
                    ONRAMP_CONVERSIONS_TOTAL.labels(direction="inr_to_usdc").inc()

                    result = ConversionResult(
                        source_amount=amount_inr,
                        source_currency="INR",
                        target_amount=actual_usdc.quantize(Decimal("0.000001")),
                        target_currency="USDC",
                        rate_used=rate,
                        fee=actual_fee.quantize(Decimal("0.000001")),
                        tx_reference=f"MOONPAY-BUY-{tx_id}",
                        converted_at=datetime.now(tz=timezone.utc),
                    )

                    log.info(
                        "moonpay_inr_to_usdc_success",
                        enterprise_id=str(enterprise_id),
                        amount_inr=str(amount_inr),
                        usdc_received=str(result.target_amount),
                        tx_reference=result.tx_reference,
                    )
                    return result

                elif response.status_code == 429:
                    last_error = OnRampProviderError("MoonPay rate limit hit")
                    log.warning("moonpay_rate_limited", attempt=attempt)
                else:
                    last_error = OnRampProviderError(
                        f"MoonPay API error: HTTP {response.status_code}"
                    )
                    log.error(
                        "moonpay_buy_error",
                        status_code=response.status_code,
                        attempt=attempt,
                    )

            except httpx.TimeoutException as e:
                last_error = e
                log.warning("moonpay_timeout", attempt=attempt)
            except httpx.ConnectError as e:
                last_error = e
                log.error("moonpay_connection_error", attempt=attempt)
            except Exception as e:
                last_error = e
                log.error("moonpay_unexpected_error", error=str(e), attempt=attempt)

        # All retries exhausted
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._circuit_threshold:
            self._circuit_open = True
            log.error(
                "moonpay_circuit_breaker_tripped",
                failures=self._consecutive_failures,
            )

        raise OnRampProviderError(
            f"MoonPay INR→USDC conversion failed after {_MAX_RETRIES + 1} attempts: "
            f"{last_error}"
        ) from last_error

    async def convert_usdc_to_inr(
        self,
        amount_usdc: Decimal,
        enterprise_id: uuid.UUID,
    ) -> ConversionResult:
        """
        Initiate USDC → INR sell order via MoonPay.

        Creates a MoonPay sell transaction for the enterprise.

        Args:
            amount_usdc: Amount in USDC to convert.
            enterprise_id: UUID of the enterprise making the conversion.

        Returns:
            ConversionResult with amounts, rate, fee, and tx reference.

        Raises:
            OnRampProviderError: On API failure after retries.
        """
        if self._circuit_open:
            raise OnRampProviderError(
                "MoonPay circuit breaker is open — service temporarily unavailable"
            )

        rate = await self.get_exchange_rate("USDC", "INR")
        gross_inr = amount_usdc * rate
        fee = gross_inr * _DEFAULT_FEE_PCT
        net_inr = gross_inr - fee

        payload = {
            "apiKey": self._api_key,
            "baseCurrencyCode": "usdc",
            "quoteCurrencyCode": "inr",
            "baseCurrencyAmount": str(amount_usdc),
            "externalCustomerId": str(enterprise_id),
        }

        last_error: Exception | None = None
        for attempt, delay in enumerate([0.0] + list(_RETRY_DELAYS)):
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        f"{self._base_url}/v3/sell_transactions",
                        json=payload,
                        headers={
                            "Authorization": f"Api-Key {self._api_key}",
                            "Content-Type": "application/json",
                        },
                    )

                if response.status_code in (200, 201):
                    data = response.json()
                    tx_id = data.get("id", str(uuid.uuid4()))
                    actual_inr = Decimal(
                        str(data.get("quoteCurrencyAmount", net_inr))
                    )
                    actual_fee = Decimal(str(data.get("feeAmount", fee)))

                    self._consecutive_failures = 0
                    ONRAMP_CONVERSIONS_TOTAL.labels(direction="usdc_to_inr").inc()

                    result = ConversionResult(
                        source_amount=amount_usdc,
                        source_currency="USDC",
                        target_amount=actual_inr.quantize(Decimal("0.01")),
                        target_currency="INR",
                        rate_used=rate,
                        fee=actual_fee.quantize(Decimal("0.01")),
                        tx_reference=f"MOONPAY-SELL-{tx_id}",
                        converted_at=datetime.now(tz=timezone.utc),
                    )

                    log.info(
                        "moonpay_usdc_to_inr_success",
                        enterprise_id=str(enterprise_id),
                        amount_usdc=str(amount_usdc),
                        inr_received=str(result.target_amount),
                        tx_reference=result.tx_reference,
                    )
                    return result

                elif response.status_code == 429:
                    last_error = OnRampProviderError("MoonPay rate limit hit")
                    log.warning("moonpay_rate_limited", attempt=attempt)
                else:
                    last_error = OnRampProviderError(
                        f"MoonPay API error: HTTP {response.status_code}"
                    )
                    log.error(
                        "moonpay_sell_error",
                        status_code=response.status_code,
                        attempt=attempt,
                    )

            except httpx.TimeoutException as e:
                last_error = e
                log.warning("moonpay_timeout", attempt=attempt)
            except httpx.ConnectError as e:
                last_error = e
                log.error("moonpay_connection_error", attempt=attempt)
            except Exception as e:
                last_error = e
                log.error("moonpay_unexpected_error", error=str(e), attempt=attempt)

        self._consecutive_failures += 1
        if self._consecutive_failures >= self._circuit_threshold:
            self._circuit_open = True
            log.error(
                "moonpay_circuit_breaker_tripped",
                failures=self._consecutive_failures,
            )

        raise OnRampProviderError(
            f"MoonPay USDC→INR conversion failed after {_MAX_RETRIES + 1} attempts: "
            f"{last_error}"
        ) from last_error

    def verify_webhook_signature(
        self, payload: bytes, signature: str
    ) -> bool:
        """
        Verify MoonPay webhook signature to authenticate inbound webhooks.

        MoonPay signs webhooks with HMAC-SHA256 using the secret key.

        Args:
            payload: Raw request body bytes.
            signature: Signature from X-MoonPay-Signature header.

        Returns:
            True if signature is valid.
        """
        if not self._api_secret:
            log.warning("moonpay_webhook_secret_not_configured")
            return False

        expected = hmac.HMAC(
            self._api_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)

    def reset_circuit_breaker(self) -> None:
        """Manually reset the circuit breaker (admin action)."""
        self._circuit_open = False
        self._consecutive_failures = 0
        log.info("moonpay_circuit_breaker_reset")
