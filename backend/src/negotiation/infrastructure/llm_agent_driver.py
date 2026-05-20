# context.md §1.2: openai import ONLY in infrastructure — never in domain.
# context.md §1.4 OCP: IAgentDriver is the only interface.
# LLM_PROVIDER env var selects which driver is wired (default "openai").

from __future__ import annotations

import asyncio
import json
import os
import time
from decimal import Decimal

import structlog

from src.shared.api.llm_sanitizer import sanitize_llm_input, validate_agent_output
from src.shared.domain.exceptions import DomainError, ValidationError
from src.shared.infrastructure.metrics import (
    LLM_LATENCY_SECONDS,
    LLM_REQUESTS_TOTAL,
)

log = structlog.get_logger(__name__)

RETRY_DELAYS = [2.0, 5.0, 10.0, 20.0]


class LLMExhaustedException(DomainError):
    """LLM failed after all retry attempts. Mapped to HTTP 503."""
    error_code = "LLM_EXHAUSTED"


class LLMAgentDriver:
    """LLM-backed agent driver implementing IAgentDriver. Supports OpenAI, Groq, and Gemini."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        temperature: float = 0.3,
        max_tokens: int = 512,
        base_url: str | None = None,
        extra_api_keys: list[str] | None = None,
    ) -> None:
        self._base_url = base_url
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._api_keys = [api_key] + (extra_api_keys or [])
        self._clients = [self._make_client(k) for k in self._api_keys]
        self.client = self._clients[0]  # kept for backwards compatibility

    def _make_client(self, api_key: str):
        import openai  # type: ignore[import-untyped]
        kwargs: dict = {"api_key": api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        return openai.AsyncOpenAI(**kwargs)

    async def generate_offer(
        self,
        system_prompt: str,
        session_context: dict,
        offer_history: list[dict],
        logistics_context: dict | None = None,
    ) -> dict:
        start_time = time.monotonic()

        # Inject logistics/delivery context into system prompt if available
        if logistics_context:
            logistics_section = (
                "\n\nLOGISTICS CONTEXT:\n"
                f"- Distance: {logistics_context.get('distance_km', 'N/A')} km between buyer and seller\n"
                f"- Transit time: {logistics_context.get('transit_days', 'N/A')} days estimated\n"
                f"- Manufacturing lead: {logistics_context.get('lead_days', 'N/A')} days\n"
                f"- Total delivery: {logistics_context.get('total_days', 'N/A')} days\n"
                f"- Buyer deadline: {logistics_context.get('deadline_days', 'N/A')} days\n"
                f"- Buffer remaining: {logistics_context.get('buffer_days', 'N/A')} days\n"
                f"- Urgency: {logistics_context.get('urgency_level', 'LOW')}\n"
                "\nURGENCY RULES:\n"
                "- CRITICAL: push for immediate agreement, max 3 rounds\n"
                "- HIGH: reduce concession rounds, aim for quick convergence\n"
                "- MODERATE: normal pace with awareness of timeline\n"
                "- LOW: negotiate freely, maximize value\n"
            )
            system_prompt = system_prompt + logistics_section

        system_prompt = sanitize_llm_input(system_prompt)
        user_content = json.dumps({
            "session": session_context,
            "offer_history": offer_history,
            "instruction": "Generate your next negotiation action as JSON.",
        })
        user_content = sanitize_llm_input(user_content)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        import openai  # type: ignore[import-untyped]
        last_error: Exception | None = None
        for attempt, delay in enumerate([0.0] + RETRY_DELAYS):
            if delay > 0:
                await asyncio.sleep(delay)
            # On each attempt, cycle through all API keys so a quota error on one
            # key doesn't block the request — try the next key immediately.
            for key_idx, client in enumerate(self._clients):
                try:
                    response = await client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        response_format={"type": "json_object"},
                    )
                    raw_content = response.choices[0].message.content or ""
                    result = validate_agent_output(raw_content)

                    # Prometheus: record success
                    elapsed = time.monotonic() - start_time
                    LLM_LATENCY_SECONDS.labels(provider=self.model.split("-")[0]).observe(elapsed)
                    LLM_REQUESTS_TOTAL.labels(provider=self.model.split("-")[0], status="success").inc()

                    return result
                except openai.RateLimitError as e:
                    last_error = e
                    log.warning("llm_rate_limit", attempt=attempt, key_idx=key_idx, total_keys=len(self._clients))
                    # Try next key immediately; if this was the last key the outer
                    # loop will sleep and cycle through all keys again.
                    continue
                except openai.APITimeoutError as e:
                    # BUG-01 FIX: `continue` instead of `break` so remaining keys
                    # are tried before waiting RETRY_DELAY seconds.
                    last_error = e
                    log.warning("llm_timeout", attempt=attempt, key_idx=key_idx)
                    continue  # try next key before sleeping
                except openai.APIConnectionError as e:
                    # BUG-01 FIX: same — try all keys before sleeping.
                    last_error = e
                    log.error("llm_connection_error", attempt=attempt, key_idx=key_idx)
                    continue  # try next key
                except ValidationError as e:
                    # Content-related error: retrying the same model with the same
                    # input won't help — break inner loop and let outer loop sleep.
                    last_error = e
                    log.warning("llm_invalid_output", attempt=attempt, key_idx=key_idx, error=str(e))
                    break
                except Exception as e:
                    # BUG-01 FIX: unknown errors should also try remaining keys.
                    last_error = e
                    log.error("llm_unexpected_error", attempt=attempt, key_idx=key_idx, error=str(e))
                    continue  # try next key

        # Prometheus: record failure
        elapsed = time.monotonic() - start_time
        LLM_LATENCY_SECONDS.labels(provider=self.model.split("-")[0]).observe(elapsed)
        LLM_REQUESTS_TOTAL.labels(provider=self.model.split("-")[0], status="error").inc()

        raise LLMExhaustedException(
            f"LLM failed after {len(RETRY_DELAYS) + 1} attempts: {last_error}"
        ) from last_error


class StubAgentDriver:
    """Deterministic stub for testing — no LLM calls. Implements IAgentDriver."""

    async def generate_offer(
        self,
        system_prompt: str,
        session_context: dict,
        offer_history: list[dict],
        logistics_context: dict | None = None,
    ) -> dict:
        round_num = session_context.get("round_count", 0)
        last_price = offer_history[-1]["price"] if offer_history else 100000.0
        new_price = last_price * 0.98
        action = "ACCEPT" if round_num >= 5 else "OFFER"
        return {
            "action": action,
            "price": round(new_price, 2),
            "reasoning": (
                f"Stub agent round {round_num}: "
                f"{'accepting' if action == 'ACCEPT' else 'conceding 2%'}"
            ),
            "confidence": 0.75,
        }


def get_agent_driver() -> object:
    """
    Wire the correct LLM agent driver based on environment configuration.

    Environment Variables:
        LLM_PROVIDER:   "openai" | "gemini" | "stub" (default: "stub")
        LLM_MODEL:      Model identifier (default varies by provider)
                        OpenAI: "gpt-4o" (default), "gpt-4o-mini", "gpt-4-turbo"
                        Gemini: "gemini-1.5-pro" (default), "gemini-1.5-flash"
        OPENAI_API_KEY: Required when LLM_PROVIDER=openai
        GEMINI_API_KEY: Required when LLM_PROVIDER=gemini
        LLM_TEMPERATURE: Float 0.0-1.0 (default: 0.3)
        LLM_MAX_TOKENS:  Int (default: 512)

    Returns:
        LLMAgentDriver for production LLM, StubAgentDriver for testing.
    """
    provider = os.getenv("LLM_PROVIDER", "stub")
    temperature = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    max_tokens = int(os.getenv("LLM_MAX_TOKENS", "2048"))

    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            log.warning("openai_api_key_missing_falling_back_to_stub")
            return StubAgentDriver()
        return LLMAgentDriver(
            api_key=api_key,
            model=os.getenv("LLM_MODEL", "gpt-4o"),
            temperature=temperature,
            max_tokens=max_tokens,
        )

    if provider == "groq":
        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            log.warning("groq_api_key_missing_falling_back_to_stub")
            return StubAgentDriver()
        # BUG-02 FIX: collect additional fallback keys with strip() and deduplication.
        # The walrus-operator list-comp was fragile: it didn't strip whitespace and
        # didn't filter duplicates (if the same key was set under two env var names).
        extra_keys: list[str] = []
        for k in ("GROQ_API_KEY_2", "GROQ_API_KEY_3", "GROQ_API_KEY_4", "GROQ_API_KEY_5"):
            v = os.environ.get(k, "").strip()
            if v and v != api_key and v not in extra_keys:
                extra_keys.append(v)
        log.info(
            "groq_driver_initialized",
            primary_key_prefix=api_key[:12],
            total_keys=1 + len(extra_keys),
        )
        return LLMAgentDriver(
            api_key=api_key,
            model=os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"),
            temperature=temperature,
            max_tokens=max_tokens,
            base_url="https://api.groq.com/openai/v1",
            extra_api_keys=extra_keys,
        )

    if provider == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            log.warning("gemini_api_key_missing_falling_back_to_stub")
            return StubAgentDriver()
        # BUG-14 FIX: Gemini has an OpenAI-compatible endpoint — must specify
        # base_url or calls will hit OpenAI's endpoint with a Gemini key (→ 401).
        return LLMAgentDriver(
            api_key=api_key,
            model=os.getenv("LLM_MODEL", "gemini-2.0-flash"),
            temperature=temperature,
            max_tokens=max_tokens,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )

    if provider != "stub":
        log.warning(
            "unknown_llm_provider_falling_back_to_stub",
            provider=provider,
            hint="Supported: openai, groq, gemini, stub",
        )

    return StubAgentDriver()
