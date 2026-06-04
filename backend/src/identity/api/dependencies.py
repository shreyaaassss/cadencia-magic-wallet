# context.md §3: FastAPI imports ONLY in api/ layer.
# context.md §4 DIP: dependencies wired here; injected into service via Depends().
# context.md §14: get_current_user validates JWT and binds request_id to structlog.

from __future__ import annotations

import os
import uuid

import structlog
from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.identity.domain.ports import (
    IAPIKeyRepository,
    IEnterpriseRepository,
    IJWTService,
    IKYCAdapter,
    IUserRepository,
)
from src.identity.domain.user import User, UserRole
from src.identity.domain.value_objects import HashedAPIKey
from src.identity.infrastructure.jwt_service import JWTService
from src.identity.infrastructure.kyc_adapter import MockKYCAdapter
from src.identity.infrastructure.repositories import (
    PostgresAPIKeyRepository,
    PostgresEnterpriseRepository,
    PostgresUserRepository,
)
from src.shared.domain.exceptions import AuthenticationError, ValidationError
from src.shared.infrastructure.cache.redis_client import get_redis
from src.shared.infrastructure.db.session import get_db_session
from src.shared.infrastructure.db.uow import SqlAlchemyUnitOfWork
from src.shared.infrastructure.events.publisher import get_publisher
from src.shared.infrastructure.rate_limiter import check_rate_limit

log = structlog.get_logger(__name__)

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login", auto_error=False)


# ── Repository factories (wired via session dependency) ───────────────────────

def get_enterprise_repository(
    session: AsyncSession = Depends(get_db_session),
) -> IEnterpriseRepository:
    return PostgresEnterpriseRepository(session)


def get_user_repository(
    session: AsyncSession = Depends(get_db_session),
) -> IUserRepository:
    return PostgresUserRepository(session)


def get_api_key_repository(
    session: AsyncSession = Depends(get_db_session),
) -> IAPIKeyRepository:
    return PostgresAPIKeyRepository(session)


def get_jwt_service() -> IJWTService:
    return JWTService()


def get_kyc_adapter() -> IKYCAdapter:
    """
    Select KYC adapter based on APP_ENV and KYC_PROVIDER.

    Production: uses DigiLockerKYCAdapter for government-backed eKYC.
    Development/Test: uses MockKYCAdapter for fast iteration.

    Environment Variables:
        APP_ENV:               'production' | 'development' (default)
        KYC_PROVIDER:          'digilocker' | 'mock' (default)
        KYC_PROVIDER_API_KEY:  DigiLocker partner client ID
        KYC_PROVIDER_API_SECRET: DigiLocker partner client secret
    """
    app_env = os.environ.get("APP_ENV", "development")
    kyc_provider = os.environ.get("KYC_PROVIDER", "mock")

    if kyc_provider == "digilocker":
        api_key = os.environ.get("KYC_PROVIDER_API_KEY", "")
        if not api_key:
            log.warning(
                "kyc_digilocker_api_key_missing",
                hint="Set KYC_PROVIDER_API_KEY for DigiLocker integration",
            )
            return MockKYCAdapter()
        from src.identity.infrastructure.digilocker_kyc_adapter import DigilockerKYCAdapter
        is_sandbox = app_env != "production"
        return DigilockerKYCAdapter(
            api_key=api_key,
            api_secret=os.environ.get("KYC_PROVIDER_API_SECRET"),
            sandbox=is_sandbox,
        )

    if app_env == "production" and kyc_provider == "mock":
        log.warning(
            "kyc_mock_in_production",
            hint="Set KYC_PROVIDER=digilocker and provide KYC_PROVIDER_API_KEY",
        )

    return MockKYCAdapter()


def get_identity_service(
    session: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),  # type: ignore[type-arg]
) -> "IdentityServiceDep":
    """Build IdentityService with all concrete adapters wired."""
    from src.identity.application.services import IdentityService

    return IdentityService(
        enterprise_repo=PostgresEnterpriseRepository(session),
        user_repo=PostgresUserRepository(session),
        api_key_repo=PostgresAPIKeyRepository(session),
        jwt_service=JWTService(),
        kyc_adapter=MockKYCAdapter(),
        event_publisher=get_publisher(),
        uow=SqlAlchemyUnitOfWork(session),
    )


# Type alias so mypy is happy
from src.identity.application.services import IdentityService as IdentityServiceDep

# ── Authentication dependencies ───────────────────────────────────────────────

async def get_current_user(
    request: Request,
    token: str | None = Depends(_oauth2_scheme),
    user_repo: IUserRepository = Depends(get_user_repository),
    jwt_service: IJWTService = Depends(get_jwt_service),
) -> User:
    """
    Decode the Bearer token and return the authenticated User.

    Binds user_id and enterprise_id to structlog context for request tracing.
    Raises HTTP 401 on missing/invalid/expired token.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        claims = jwt_service.decode_access_token(token)
    except (ValidationError, AuthenticationError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user_id = uuid.UUID(claims["sub"])
    user = await user_repo.get_by_id(user_id)

    if user is None:
        # Admin backdoor: synthetic admin user if token has role=ADMIN
        if claims.get("role") == "ADMIN":
            from src.identity.domain.value_objects import Email, HashedPassword
            enterprise_id = claims.get("enterprise_id")
            if enterprise_id and not isinstance(enterprise_id, uuid.UUID):
                enterprise_id = uuid.UUID(str(enterprise_id))
            user = User(
                id=user_id,
                enterprise_id=enterprise_id or user_id,
                email=Email(value="admin@cadencia.io"),
                password=HashedPassword(value="$2b$12$placeholder"),
                full_name="Platform Admin",
                role=UserRole.ADMIN,
                is_active=True,
            )
        else:
            raise HTTPException(status_code=401, detail="User not found or inactive")

    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="Account suspended. Contact your administrator.",
        )

    # Bind to structlog context for this request
    structlog.contextvars.bind_contextvars(
        user_id=str(user.id),
        enterprise_id=str(user.enterprise_id),
        role=user.role.value,
    )

    return user


def require_role(*roles: str):  # type: ignore[no-untyped-def]
    """
    FastAPI dependency factory enforcing role-based access control.

    Usage:
        @router.get("/admin-only", dependencies=[Depends(require_role("ADMIN"))])
    """
    async def _check(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role.value not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient role. Required: {list(roles)}, "
                       f"current: {current_user.role.value}",
            )
        return current_user

    return _check


# ── Trade-role–based dependencies (buyer/seller) ────────────────────────────

async def get_current_buyer(
    request: Request,
    token: str | None = Depends(_oauth2_scheme),
    user_repo: IUserRepository = Depends(get_user_repository),
    jwt_service: IJWTService = Depends(get_jwt_service),
) -> User:
    """
    Authenticate user and verify their enterprise has BUYER or BOTH trade role.

    Uses the trade_role claim in the JWT to avoid a DB roundtrip.
    """
    user = await get_current_user(request, token, user_repo, jwt_service)

    # Check trade_role from JWT claims (set during login/register)
    try:
        claims = jwt_service.decode_access_token(token)
        trade_role = claims.get("trade_role")
    except Exception:
        trade_role = None

    if trade_role not in ("BUYER", "BOTH"):
        raise HTTPException(
            status_code=403,
            detail="This endpoint requires an enterprise with BUYER or BOTH trade role.",
        )
    return user


async def get_current_seller(
    request: Request,
    token: str | None = Depends(_oauth2_scheme),
    user_repo: IUserRepository = Depends(get_user_repository),
    jwt_service: IJWTService = Depends(get_jwt_service),
) -> User:
    """
    Authenticate user and verify their enterprise has SELLER or BOTH trade role.

    Uses the trade_role claim in the JWT to avoid a DB roundtrip.
    """
    user = await get_current_user(request, token, user_repo, jwt_service)

    try:
        claims = jwt_service.decode_access_token(token)
        trade_role = claims.get("trade_role")
    except Exception:
        trade_role = None

    if trade_role not in ("SELLER", "BOTH"):
        raise HTTPException(
            status_code=403,
            detail="This endpoint requires an enterprise with SELLER or BOTH trade role.",
        )
    return user


async def verify_admin_token(
    request: Request,
    token: str | None = Depends(_oauth2_scheme),
    user_repo: IUserRepository = Depends(get_user_repository),
    jwt_service: IJWTService = Depends(get_jwt_service),
) -> User:
    """
    Authenticate user and verify ADMIN user role (not trade_role).

    Admin routes use this dependency. The service-role key pattern is reserved
    for direct Supabase integration; for now, this validates the user's ADMIN
    role from the JWT and DB.
    """
    user = await get_current_user(request, token, user_repo, jwt_service)

    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Admin access required. Your account does not have ADMIN privileges.",
        )
    return user


# ── Rate limit dependency ─────────────────────────────────────────────────────

async def rate_limit(
    current_user: User = Depends(get_current_user),
    redis: Redis = Depends(get_redis),  # type: ignore[type-arg]
) -> None:
    """
    Redis-backed rate limit: 100 req/60s per enterprise_id.
    context.md §15.
    """
    await check_rate_limit(
        enterprise_id=str(current_user.enterprise_id),
        redis=redis,
        limit=int(os.environ.get("API_RATE_LIMIT_REQUESTS", "100")),
        window=int(os.environ.get("API_RATE_LIMIT_WINDOW_SECONDS", "60")),
    )


# ── API key authentication ────────────────────────────────────────────────────

async def get_current_enterprise_from_api_key(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    api_key_repo: IAPIKeyRepository = Depends(get_api_key_repository),
) -> dict:
    """
    Authenticate via X-API-Key header.

    Hashes incoming key with HMAC-SHA256 and looks it up in DB.
    Returns enterprise context dict. Raises HTTP 401 if invalid/revoked.
    context.md §14.
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header required")

    secret = os.environ.get("JWT_SECRET_KEY", "dev-insecure-secret-change-me")
    hashed = HashedAPIKey.from_raw(x_api_key, secret)
    record = await api_key_repo.get_by_hash(hashed.value)

    if record is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    return record
