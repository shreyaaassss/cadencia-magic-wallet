"""
GET /health — infrastructure health check endpoint.

Returns TWO shapes:
1. Internal HealthResponse (for monitoring systems — unchanged)
2. Frontend-compatible shape wrapped in ApiResponse envelope:
   { "status": "success", "data": { "overall", "services", "timestamp" } }
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone

import httpx
import sqlalchemy
import structlog
from fastapi import APIRouter
from pydantic import BaseModel

from src.shared.api.responses import ApiResponse, success_response
from src.shared.infrastructure.cache.redis_client import ping as redis_ping
from src.shared.infrastructure.db.session import get_engine

log = structlog.get_logger(__name__)

router = APIRouter(tags=["health"])

APP_VERSION = os.environ.get("APP_VERSION", "0.1.0")
APP_ENV = os.environ.get("APP_ENV", "development")


class CheckResult(BaseModel):
    status: str              # "ok" | "error"
    latency_ms: float
    detail: str | None = None


class HealthResponse(BaseModel):
    """Internal health response (for monitoring — unchanged)."""
    status: str              # "healthy" | "degraded" | "unhealthy"
    checks: dict[str, CheckResult]
    version: str
    environment: str


# ── Frontend-facing health schemas ────────────────────────────────────────────


class FrontendHealthResponse(BaseModel):
    """Shape expected by the frontend's useHealthStatus hook."""
    overall: str                    # "healthy" | "degraded" | "down"
    services: dict[str, str]        # { database, redis, algorand, llm } → "healthy" | "down"
    timestamp: str                  # ISO 8601


# ── Health check functions ────────────────────────────────────────────────────


async def _check_db() -> CheckResult:
    """Verify PostgreSQL connectivity with SELECT 1."""
    start = time.monotonic()
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await asyncio.wait_for(conn.execute(sqlalchemy.text("SELECT 1")), timeout=3.0)
        latency = (time.monotonic() - start) * 1000
        return CheckResult(status="ok", latency_ms=round(latency, 2))
    except Exception as exc:
        latency = (time.monotonic() - start) * 1000
        log.warning("health_check_db_failed", error=str(exc))
        return CheckResult(status="error", latency_ms=round(latency, 2), detail=str(exc))


async def _check_redis() -> CheckResult:
    """Verify Redis connectivity with PING."""
    start = time.monotonic()
    try:
        ok = await asyncio.wait_for(redis_ping(), timeout=2.0)
        latency = (time.monotonic() - start) * 1000
        if ok:
            return CheckResult(status="ok", latency_ms=round(latency, 2))
        return CheckResult(status="error", latency_ms=round(latency, 2), detail="PING returned false")
    except Exception as exc:
        latency = (time.monotonic() - start) * 1000
        log.warning("health_check_redis_failed", error=str(exc))
        return CheckResult(status="error", latency_ms=round(latency, 2), detail=str(exc))


async def _check_algorand() -> CheckResult:
    """Verify Algorand algod connectivity with GET /health."""
    start = time.monotonic()
    algod_address = os.environ.get("ALGORAND_ALGOD_ADDRESS", "http://localhost:4001")
    algod_token = os.environ.get(
        "ALGORAND_ALGOD_TOKEN",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(
                f"{algod_address}/health",
                headers={"X-Algo-API-Token": algod_token},
            )
        latency = (time.monotonic() - start) * 1000
        if response.status_code == 200:
            return CheckResult(status="ok", latency_ms=round(latency, 2))
        return CheckResult(
            status="error",
            latency_ms=round(latency, 2),
            detail=f"HTTP {response.status_code}",
        )
    except Exception as exc:
        latency = (time.monotonic() - start) * 1000
        log.warning("health_check_algorand_failed", error=str(exc))
        return CheckResult(status="error", latency_ms=round(latency, 2), detail=str(exc))


async def _check_llm_api() -> CheckResult:
    """Verify LLM API connectivity. Skipped if LLM_PROVIDER=stub."""
    start = time.monotonic()
    provider = os.environ.get("LLM_PROVIDER", "stub")
    health_enabled = os.environ.get("LLM_HEALTH_CHECK_ENABLED", "true").lower()

    if provider == "stub" or health_enabled == "false":
        latency = (time.monotonic() - start) * 1000
        return CheckResult(
            status="ok", latency_ms=round(latency, 2), detail="stub_provider"
        )

    try:
        import openai
        if provider == "groq":
            api_key = os.environ.get("GROQ_API_KEY", "").strip()
            base_url = "https://api.groq.com/openai/v1"
            model = os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")
        elif provider == "gemini":
            api_key = os.environ.get("GEMINI_API_KEY", "").strip()
            base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
            model = os.environ.get("LLM_MODEL", "gemini-2.0-flash")
        else:
            api_key = os.environ.get("OPENAI_API_KEY", "")
            base_url = None
            model = os.environ.get("LLM_MODEL", "gpt-4o")
        if not api_key:
            latency = (time.monotonic() - start) * 1000
            return CheckResult(
                status="error",
                latency_ms=round(latency, 2),
                detail=f"no_api_key_for_{provider}",
            )
        client = (
            openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
            if base_url
            else openai.AsyncOpenAI(api_key=api_key)
        )
        await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            ),
            timeout=5.0,
        )
        latency = (time.monotonic() - start) * 1000
        return CheckResult(status="ok", latency_ms=round(latency, 2))
    except Exception as exc:
        latency = (time.monotonic() - start) * 1000
        log.warning("health_check_llm_failed", error=str(exc))
        return CheckResult(
            status="error", latency_ms=round(latency, 2), detail="unavailable"
        )


async def _check_circuits() -> CheckResult:
    """Check circuit breaker states from Redis. Returns OK if all CLOSED."""
    start = time.monotonic()
    try:
        from src.shared.infrastructure.cache import redis_client
        redis = redis_client.get_redis()

        states = {}
        for name in ["llm", "algorand"]:
            raw = await redis.get(f"cb:{name}:state")
            states[name] = raw.decode() if isinstance(raw, bytes) else (raw or "CLOSED")

        latency = (time.monotonic() - start) * 1000
        any_open = any(s == "OPEN" for s in states.values())

        if any_open:
            return CheckResult(
                status="error", latency_ms=round(latency, 2),
                detail=f"circuits: {states}"
            )
        return CheckResult(status="ok", latency_ms=round(latency, 2))
    except Exception:
        latency = (time.monotonic() - start) * 1000
        return CheckResult(
            status="ok", latency_ms=round(latency, 2),
            detail="circuit_check_skipped"
        )


# ── Mapping helpers ───────────────────────────────────────────────────────────


def _map_check_status(raw: str) -> str:
    """Map internal 'ok'/'error' to frontend 'healthy'/'down'."""
    return "healthy" if raw == "ok" else "down"


def _derive_overall(services: dict[str, str]) -> str:
    """Derive overall status from individual service statuses."""
    statuses = set(services.values())
    if statuses == {"healthy"}:
        return "healthy"
    elif "down" in statuses:
        return "degraded"
    return "healthy"


def _compute_overall_status(
    db: CheckResult,
    redis: CheckResult,
    algorand: CheckResult,
    llm_api: CheckResult,
    circuits: CheckResult,
) -> str:
    if db.status != "ok" or redis.status != "ok":
        return "unhealthy"
    all_ok = all(c.status == "ok" for c in [algorand, llm_api, circuits])
    return "healthy" if all_ok else "degraded"


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.get(
    "/health",
    response_model=ApiResponse[FrontendHealthResponse],
    summary="Infrastructure health check",
)
async def health_check() -> ApiResponse[FrontendHealthResponse]:
    """
    Check DB, Redis, Algorand, LLM API concurrently.

    Returns the frontend-compatible shape wrapped in ApiResponse envelope:
    { "status": "success", "data": { "overall", "services", "timestamp" } }
    """
    db_result, redis_result, algorand_result, llm_result, circuits_result = (
        await asyncio.gather(
            _check_db(),
            _check_redis(),
            _check_algorand(),
            _check_llm_api(),
            _check_circuits(),
        )
    )

    # Build the frontend services map (circuit_breakers excluded)
    services = {
        "database": _map_check_status(db_result.status),
        "redis": _map_check_status(redis_result.status),
        "algorand": _map_check_status(algorand_result.status),
        "llm": _map_check_status(llm_result.status),
    }

    overall = _derive_overall(services)

    log.info(
        "health_check_completed",
        status=overall,
        db=db_result.status,
        redis=redis_result.status,
        algorand=algorand_result.status,
        llm_api=llm_result.status,
        circuits=circuits_result.status,
    )

    return success_response(
        FrontendHealthResponse(
            overall=overall,
            services=services,
            timestamp=datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        )
    )
