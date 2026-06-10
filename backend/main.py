"""
Cadencia FastAPI application factory.

context.md §4: API-first modular monolith, API prefix /v1/*.
context.md §16: Lifespan context manager (not deprecated on_event).
context.md §14: CORS locked to CORS_ALLOWED_ORIGINS. Wildcard * PROHIBITED in production.

Usage:
    uvicorn main:app --factory             # development
    gunicorn -k uvicorn.workers.UvicornWorker main:app  # production (4 workers)

The create_app() factory enables:
- Test isolation (fresh app instance per test)
- Environment-specific configuration
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the backend directory (supports running outside Docker)
load_dotenv(Path(__file__).resolve().parent / ".env")
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from src.compliance.api.router import audit_router, compliance_router
from src.health.router import router as health_router
from src.identity.api.router import router as identity_router
from src.settlement.api.router import router as settlement_router
from src.shared.api.error_handler import (
    domain_error_handler,
    http_exception_handler,
    validation_exception_handler,
    generic_exception_handler,
)
from src.shared.domain.exceptions import DomainError
from src.shared.infrastructure.cache import redis_client as redis_module
from src.shared.infrastructure.db.session import get_engine
from src.shared.api.x402_handler import enforce_no_simulation_mode_at_startup
from src.shared.infrastructure.events.handlers import (
    register_handlers,
    register_phase_five_handlers,
    register_phase_four_handlers,
    register_phase_seven_handlers,
    register_phase_six_handlers,
    register_phase_three_handlers,
    register_phase_two_handlers,
)
from src.shared.infrastructure.events.publisher import get_publisher
from src.shared.infrastructure.logging import configure_logging, get_logger

log = get_logger(__name__)


# ── Default Playbook Seeder ───────────────────────────────────────────────────

async def _seed_default_playbooks() -> None:
    """
    Ensure at least a 'general' industry playbook row exists in the DB.

    Idempotent: skips if the row already exists (checked by industry_name).
    The playbook content is industry-agnostic — it applies to any commodity
    vertical (steel, textiles, chemicals, electronics, agri, etc.).

    NEG-05 fix: without a 'general' playbook, every session shows
    "No industry playbook available." and the LLM negotiates without domain context.
    """
    from sqlalchemy import select
    from src.shared.infrastructure.db.session import get_session_factory

    # Industry-agnostic default playbook — works for all commodity sectors
    DEFAULT_PLAYBOOKS = [
        {
            "hsn_prefix": "00000000",
            "industry_name": "general",
            "playbook_text": (
                "General B2B commodity procurement playbook. "
                "Applies to any industry: steel, textiles, chemicals, electronics, agri-commodities, etc."
            ),
            "strategy_hints": {
                "pricing_norms": (
                    "Negotiate the TOTAL ORDER VALUE in INR. "
                    "Bulk orders (>10 units) typically command 5-15% discount off catalogue price. "
                    "Market reference price should anchor initial offers — do not open > 120% of market."
                ),
                "payment_schedules": (
                    "Standard B2B payment: 30% advance + 70% on delivery. "
                    "For large orders (>₹10L): LC at sight or bank guarantee is common. "
                    "Net 30/60 credit available for established relationships (>1 year)."
                ),
                "typical_discount_ranges": (
                    "2-5%: small orders, new relationships. "
                    "5-10%: repeat buyer, bulk order. "
                    "10-15%: strategic account, annual contract, or distress inventory."
                ),
                "seasonal_factors": (
                    "End of quarter (Mar, Jun, Sep, Dec): sellers more willing to close — push harder. "
                    "Festival season (Oct-Nov): demand peaks, prices firm. "
                    "Monsoon: logistics delays common — factor into SLA negotiations."
                ),
                "standard_slas": (
                    "Domestic delivery: 7-21 days standard. Express: 3-5 days at premium. "
                    "Quality inspection before dispatch — insist on mill test certificates for metals. "
                    "Penalty for late delivery: 0.5% of order value per week, max 5%."
                ),
                "common_terms": (
                    "Force majeure clause mandatory. Price validity: 7-15 days. "
                    "Governing law: Indian Contract Act 1872. "
                    "Dispute resolution: arbitration preferred over litigation."
                ),
            },
        },
    ]

    try:
        factory = get_session_factory()
        async with factory() as session:
            from src.negotiation.infrastructure.models import IndustryPlaybookModel
            for pb_data in DEFAULT_PLAYBOOKS:
                # Check if already exists
                result = await session.execute(
                    select(IndustryPlaybookModel).where(
                        IndustryPlaybookModel.industry_name == pb_data["industry_name"]
                    )
                )
                if result.scalar_one_or_none() is not None:
                    continue  # Already seeded

                pb = IndustryPlaybookModel(
                    hsn_prefix=pb_data["hsn_prefix"],
                    industry_name=pb_data["industry_name"],
                    playbook_text=pb_data["playbook_text"],
                    strategy_hints=pb_data["strategy_hints"],
                    is_active=True,
                )
                session.add(pb)
            await session.commit()
    except Exception as exc:
        log.warning("seed_default_playbooks_failed", error=str(exc))
        raise


async def _resume_stalled_negotiations() -> None:
    """
    On startup, find ACTIVE negotiation sessions that have incomplete rounds
    and resume their auto-negotiation. This handles sessions orphaned by
    PM2 restarts (asyncio.create_task tasks are lost on process restart).
    """
    import asyncio

    from sqlalchemy import text
    from src.shared.infrastructure.db.session import get_session_factory

    _log = structlog.get_logger("startup.resume_negotiations")

    async with get_session_factory()() as db_session:
        # Find active sessions that haven't completed (round_count < max_rounds, not terminal)
        result = await db_session.execute(text("""
            SELECT id FROM negotiation_sessions
            WHERE status IN ('ACTIVE', 'ROUND_LOOP', 'SELLER_RESPONSE', 'BUYER_ANCHOR')
              AND current_round < 30
              AND created_at > NOW() - INTERVAL '24 hours'
            ORDER BY created_at DESC
            LIMIT 20
        """))
        stalled_ids = [str(row[0]) for row in result.fetchall()]

    if not stalled_ids:
        _log.info("no_stalled_sessions_found")
        return

    _log.info("resuming_stalled_sessions", count=len(stalled_ids))

    # Import the standalone runner directly — no MarketplaceService needed
    from src.marketplace.application.services import MarketplaceService

    for i, sid in enumerate(stalled_ids):
        async def _resume(s_id: str, delay: float) -> None:
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                import uuid as _uuid
                # Use a throwaway MarketplaceService instance just for the standalone runner
                svc = MarketplaceService.__new__(MarketplaceService)
                await svc._run_auto_negotiation_standalone(_uuid.UUID(s_id))
                _log.info("session_resumed_ok", session_id=s_id)
            except Exception as e:
                _log.warning("session_resume_failed", session_id=s_id, error=str(e))
        asyncio.create_task(_resume(sid, i * 5.0))


# ── Request ID Middleware ─────────────────────────────────────────────────────

class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Inject X-Request-ID header and bind it to structlog context.

    context.md §5: request_id on every log line.
    """

    async def dispatch(self, request: Request, call_next: object) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        # Bind request_id to structlog context for this request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=str(request.url.path),
        )

        # Type-ignore: call_next signature is correct at runtime
        response: Response = await call_next(request)  # type: ignore[operator]
        response.headers["X-Request-ID"] = request_id
        return response


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Application lifespan — startup and shutdown hooks.

    context.md §16: Lifespan context manager (not deprecated on_event).
    Startup: verify DB, Redis, Algorand connectivity.
    Shutdown: close DB pool and Redis connection.
    """
    configure_logging()
    log.info("cadencia_startup", env=os.environ.get("APP_ENV", "development"))

    # ── Startup ───────────────────────────────────────────────────────────────
    # 1. Verify DB connection
    try:
        import sqlalchemy
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(sqlalchemy.text("SELECT 1"))
        log.info("startup_db_connected")
    except Exception as exc:
        log.error("startup_db_failed", error=str(exc))
        # Do not raise — allow health check to report the failure
        # The app will boot but /health will return unhealthy

    # 2. Verify Redis connection
    try:
        ok = await redis_module.ping()
        if ok:
            log.info("startup_redis_connected")
        else:
            log.warning("startup_redis_ping_failed")
    except Exception as exc:
        log.error("startup_redis_failed", error=str(exc))

    # 3. Verify Algorand algod (non-fatal — app boots without it)
    try:
        import httpx
        algod_address = os.environ.get("ALGORAND_ALGOD_ADDRESS", "http://localhost:4001")
        algod_token = os.environ.get(
            "ALGORAND_ALGOD_TOKEN",
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(
                f"{algod_address}/health",
                headers={"X-Algo-API-Token": algod_token},
            )
        if response.status_code == 200:
            log.info("startup_algorand_connected", address=algod_address)
        else:
            log.warning(
                "startup_algorand_unhealthy",
                status_code=response.status_code,
                address=algod_address,
            )
    except Exception as exc:
        log.warning("startup_algorand_unreachable", error=str(exc))

    # 4. Register domain event handlers (Phase 0/1 + Phase 2 + Phase 3)
    publisher = get_publisher()
    register_handlers(publisher)
    register_phase_two_handlers(publisher)
    register_phase_three_handlers(publisher)  # replaces Phase 2 stubs with compliance handlers
    register_phase_four_handlers(publisher)   # replaces SessionAgreedStub with real SessionAgreed handlers
    register_phase_five_handlers(publisher)    # marketplace → negotiation event wiring
    register_phase_six_handlers(publisher)     # negotiation memory normalization + insights
    register_phase_seven_handlers(publisher)   # wallet ledger event sourcing
    log.info("startup_event_handlers_registered")

    # 4b. Start background scheduler
    from src.settlement.application.background_jobs import (
        check_approval_deadlines,
        check_dispatch_timeouts,
    )
    from src.shared.infrastructure.scheduler import BackgroundScheduler

    _scheduler = BackgroundScheduler()
    _scheduler.register_periodic("approval_deadlines", check_approval_deadlines, 3600)
    _scheduler.register_periodic("dispatch_timeouts", check_dispatch_timeouts, 3600)
    _scheduler.register_periodic("resume_stalled_negotiations", _resume_stalled_negotiations, 120)
    await _scheduler.start()

    # 5. Enforce X402_SIMULATION_MODE — PROHIBITED in production
    enforce_no_simulation_mode_at_startup()

    # 6. Seed default industry playbooks (idempotent — skips if already present)
    try:
        await _seed_default_playbooks()
        log.info("startup_playbooks_seeded")
    except Exception as exc:
        log.warning("startup_playbooks_seed_failed", error=str(exc))

    # 7. Resume any active negotiation sessions that were orphaned by restart
    try:
        await _resume_stalled_negotiations()
        log.info("startup_stalled_negotiations_resumed")
    except Exception as exc:
        log.warning("startup_resume_negotiations_failed", error=str(exc))

    log.info("cadencia_ready")

    yield  # Application runs here

    # ── Shutdown — ordered sequence ─────────────────────────────────────────────
    # Phase Five: graceful shutdown with 30s drain (set via uvicorn --timeout-graceful-shutdown=30)
    log.info("cadencia_shutdown_started")

    # 1. Stop background scheduler
    try:
        await _scheduler.stop()
    except Exception:
        pass

    # 2. Close DB connection pool
    try:
        engine = get_engine()
        await engine.dispose()
        log.info("shutdown_db_pool_closed")
    except Exception as exc:
        log.warning("shutdown_db_pool_error", error=str(exc))

    # 3. Close Redis connection
    try:
        await redis_module.close()
        log.info("shutdown_redis_closed")
    except Exception as exc:
        log.warning("shutdown_redis_error", error=str(exc))

    log.info("cadencia_shutdown_complete")


# ── App Factory ───────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """
    FastAPI application factory.

    Called by Uvicorn/Gunicorn: `uvicorn main:app --factory`
    Called in tests: `app = create_app()` for isolated instances.
    """
    app_env = os.environ.get("APP_ENV", "development")

    app = FastAPI(
        title="Cadencia API",
        description=(
            "AI-native agentic B2B trade marketplace for Indian MSMEs. "
            "Autonomous procurement: RFQ → negotiation → Algorand escrow → compliance."
        ),
        version=os.environ.get("APP_VERSION", "0.1.0"),
        docs_url="/docs" if app_env != "production" else None,
        redoc_url="/redoc" if app_env != "production" else None,
        lifespan=lifespan,
    )

    # ── Middleware (applied in LIFO order — last added = outermost) ───────────

    # 1. Request ID (innermost — runs last)
    app.add_middleware(RequestIDMiddleware)

    # 1b. Response timing
    from src.shared.infrastructure.timing_middleware import TimingMiddleware
    app.add_middleware(TimingMiddleware)

    # 1c. Security headers (OWASP)
    from src.shared.api.security_headers import SecurityHeadersMiddleware
    app.add_middleware(SecurityHeadersMiddleware)

    # 1d. Request body size limit (1MB max — prevent large payload attacks)
    @app.middleware("http")
    async def limit_upload_size(request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > 1 * 1024 * 1024:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=413,
                content={"status": "error", "detail": "Request body too large. Maximum size is 1MB."},
            )
        return await call_next(request)

    # 2. CORS
    # context.md §14: wildcard * PROHIBITED in production
    cors_origins_raw = os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
    cors_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]

    if app_env == "production" and "*" in cors_origins:
        raise ValueError(
            "CORS wildcard '*' is PROHIBITED in production (context.md §14). "
            "Set CORS_ALLOWED_ORIGINS to explicit origins."
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    # 3. Trusted host (production only)
    if app_env == "production":
        trusted_hosts_raw = os.environ.get("TRUSTED_HOSTS", "")
        if trusted_hosts_raw:
            trusted_hosts = [h.strip() for h in trusted_hosts_raw.split(",")]
            app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)

    # ── Exception Handlers ────────────────────────────────────────────────────
    # All errors must emit: { "status": "error", "detail": "..." }
    app.add_exception_handler(DomainError, domain_error_handler)  # type: ignore[arg-type]

    from fastapi import HTTPException
    from fastapi.exceptions import RequestValidationError
    app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, generic_exception_handler)  # type: ignore[arg-type]

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(health_router)
    app.include_router(identity_router)
    app.include_router(settlement_router)
    app.include_router(audit_router)
    app.include_router(compliance_router)

    # Phase Four: Negotiation API
    from src.negotiation.api.router import router as negotiation_router
    app.include_router(negotiation_router)

    # Phase Four: Agent Memory API (S3/RAG endpoints)
    from src.negotiation.api.memory_router import router as memory_router
    app.include_router(memory_router)

    # Phase Six: Negotiation Records + Insights API
    from src.negotiation.api.memory_router import records_router, insights_router
    app.include_router(records_router)
    app.include_router(insights_router)

    # Phase Five: Marketplace API
    from src.marketplace.api.router import router as marketplace_router
    app.include_router(marketplace_router)

    # Admin API — platform administration (10 endpoints)
    from src.admin.api.router import router as admin_router
    app.include_router(admin_router)

    # Magic.link authentication — /v1/auth/magic-login and /v1/auth/magic-register
    from src.identity.api.magic_auth import router as magic_auth_router
    app.include_router(magic_auth_router)

    # Short-form Wallet API — /v1/wallet/* (proxies to identity wallet logic)
    from src.wallet.api.router import router as wallet_router
    app.include_router(wallet_router)

    # Treasury API (RW-01)
    from src.treasury.api.router import router as treasury_router
    app.include_router(treasury_router)

    # x402 payment protocol — public + verification endpoints
    from src.wallet.api.x402_routes import router as x402_router
    app.include_router(x402_router)

    # Procurement — PO generation and seller acceptance
    from src.procurement.api.router import router as procurement_router
    app.include_router(procurement_router)

    # Messaging — buyer-seller conversation threads
    from src.messaging.api.router import router as messaging_router
    app.include_router(messaging_router)

    # Prometheus metrics endpoint (RW-05)
    from src.shared.api.metrics_router import router as metrics_router
    app.include_router(metrics_router)

    # Auto-instrument HTTP metrics (RW-05)
    # context.md §5: Prometheus at /metrics
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        excluded_handlers=["/health", "/metrics"],
    ).instrument(app).expose(app, include_in_schema=False, should_gzip=False)

    return app


# Module-level app instance for Uvicorn/Gunicorn discovery.
# `uvicorn main:app` or `uvicorn main:app --factory`
app = create_app()
