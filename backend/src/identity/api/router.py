# context.md §10: All endpoints versioned under /v1/.
# context.md §10: All responses use ApiResponse[T] envelope.
# context.md §14: Refresh token stored as httpOnly, SameSite=Strict cookie.

from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, UploadFile, File, status
from fastapi.responses import JSONResponse
from typing import List

from src.shared.api.responses import ApiResponse, success_response
from src.shared.infrastructure.logging import get_logger

from src.identity.api.dependencies import (
    get_current_user,
    get_identity_service,
    rate_limit,
    require_role,
)
from src.identity.api.schemas import (
    AgentConfigRequest,
    AgentConfigUpdateRequest,
    AgentConfigUpdateResponse,
    APIKeyListItem,
    APIKeyResponse,
    EnterpriseResponse,
    KYCStatusResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    CreateAPIKeyRequest,
    UserMeResponse,
    WalletChallengeResponse,
    EnterpriseWalletLinkRequest,
    WalletUnlinkResponse,
    WalletBalanceResponse,
    OptedInApp,
)
from src.identity.application.commands import (
    CreateAPIKeyCommand,
    LoginCommand,
    RefreshTokenCommand,
    RegisterEnterpriseCommand,
    RevokeAPIKeyCommand,
    SubmitKYCCommand,
    UpdateAgentConfigCommand,
)
from src.identity.application.queries import GetEnterpriseQuery, ListAPIKeysQuery
from src.identity.application.services import IdentityService
from src.identity.domain.user import User

log = get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["identity"])

_IS_PRODUCTION = os.environ.get("APP_ENV") == "production"
_SECURE_COOKIES = os.environ.get("SECURE_COOKIES", "true" if _IS_PRODUCTION else "false").lower() == "true"
_REFRESH_COOKIE_NAME = "refresh_token"


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """
    Set httpOnly refresh token cookie.
    SameSite=lax so the browser sends it with same-site + top-level navigations.
    Path scoped to /v1/auth/refresh so it's only sent on the refresh call.
    """
    max_age = 60 * 60 * 24 * 7  # 7 days
    response.set_cookie(
        key=_REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=_SECURE_COOKIES,
        samesite="lax",
        max_age=max_age,
        path="/v1/auth/",
    )


# ── POST /v1/auth/register ────────────────────────────────────────────────────

@router.post(
    "/auth/register",
    status_code=status.HTTP_200_OK,
    response_model=ApiResponse[TokenResponse],
    summary="Register a new enterprise and admin user",
)
async def register(
    request_body: RegisterRequest,
    response: Response,
    svc: IdentityService = Depends(get_identity_service),
) -> ApiResponse[TokenResponse]:
    from decimal import Decimal

    ent = request_body.enterprise
    cmd = RegisterEnterpriseCommand(
        legal_name=ent.legal_name,
        pan=ent.pan,
        gstin=ent.gstin,
        trade_role=ent.trade_role,
        email=str(request_body.user.email),
        password=request_body.user.password,
        full_name=request_body.user.full_name,
        role=request_body.user.role,
        commodities=list(ent.commodities),
        min_order_value=Decimal(str(ent.min_order_value))
            if ent.min_order_value is not None else None,
        max_order_value=Decimal(str(ent.max_order_value))
            if ent.max_order_value is not None else None,
        industry_vertical=ent.industry_vertical,
        geography=ent.geography,
        # Enhanced onboarding fields
        address=ent.address.model_dump() if ent.address else None,
        facility_type=ent.facility_type,
        payment_terms_accepted=list(ent.payment_terms_accepted) if ent.payment_terms_accepted else [],
        credit_period_days=ent.credit_period_days,
        years_in_operation=ent.years_in_operation,
        annual_turnover_inr=Decimal(str(ent.annual_turnover_inr))
            if ent.annual_turnover_inr is not None else None,
        quality_certifications=list(ent.quality_certifications) if ent.quality_certifications else [],
        test_certificate_available=ent.test_certificate_available,
        third_party_inspection_allowed=ent.third_party_inspection_allowed,
    )
    result = await svc.register_enterprise(cmd)

    _set_refresh_cookie(response, result["refresh_token"])

    return success_response(
        TokenResponse(
            access_token=result["access_token"],
            token_type="bearer",
            enterprise_id=result["enterprise_id"],
        )
    )


# ── POST /v1/auth/login ───────────────────────────────────────────────────────

@router.post(
    "/auth/login",
    response_model=ApiResponse[TokenResponse],
    summary="Authenticate and obtain JWT tokens",
)
async def login(
    request_body: LoginRequest,
    response: Response,
    svc: IdentityService = Depends(get_identity_service),
) -> ApiResponse[TokenResponse]:
    cmd = LoginCommand(
        email=str(request_body.email),
        password=request_body.password,
    )
    result = await svc.login(cmd)

    _set_refresh_cookie(response, result["refresh_token"])

    return success_response(
        TokenResponse(
            access_token=result["access_token"],
            token_type="bearer",
        )
    )


# ── POST /v1/auth/admin-login ─────────────────────────────────────────────────

@router.post(
    "/auth/admin-login",
    response_model=ApiResponse[TokenResponse],
    summary="Authenticate as platform admin (backdoor credentials)",
)
async def admin_login(
    request_body: LoginRequest,
    response: Response,
    svc: IdentityService = Depends(get_identity_service),
) -> ApiResponse[TokenResponse]:
    result = await svc.admin_login(
        email=str(request_body.email),
        password=request_body.password,
    )

    _set_refresh_cookie(response, result["refresh_token"])

    return success_response(
        TokenResponse(
            access_token=result["access_token"],
            token_type="bearer",
        )
    )


# ── POST /v1/auth/logout ──────────────────────────────────────────────────────


@router.post(
    "/auth/logout",
    response_model=ApiResponse[dict],
    summary="Logout — clears refresh token cookie and blacklists token",
)
async def logout(
    response: Response,
    refresh_token_cookie: str | None = Cookie(None, alias=_REFRESH_COOKIE_NAME),
) -> ApiResponse[dict]:
    """
    Blacklist the refresh token in Redis so it cannot be reused, then
    clear the httpOnly cookie. Cookie path is /v1/auth/ so it is sent
    to both /v1/auth/logout and /v1/auth/refresh.
    """
    if refresh_token_cookie:
        import hashlib
        from src.shared.infrastructure.cache.redis_client import get_redis_client
        token_hash = hashlib.sha256(refresh_token_cookie.encode()).hexdigest()
        redis = get_redis_client()
        # Blacklist for 31 days (longer than max refresh token lifetime)
        await redis.setex(f"rt:blacklist:{token_hash}", 60 * 60 * 24 * 31, "1")

    # Delete cookie at current path
    response.delete_cookie(
        key=_REFRESH_COOKIE_NAME,
        httponly=True,
        secure=_SECURE_COOKIES,
        samesite="lax",
        path="/v1/auth/",
    )
    # Also clear old cookie path from previous deployments
    response.delete_cookie(
        key=_REFRESH_COOKIE_NAME,
        httponly=True,
        secure=_SECURE_COOKIES,
        samesite="lax",
        path="/v1/auth/refresh",
    )
    return success_response({"message": "Logged out"})


# ── POST /v1/auth/refresh ─────────────────────────────────────────────────────

@router.post(
    "/auth/refresh",
    response_model=ApiResponse[TokenResponse],
    summary="Rotate access token using refresh cookie",
)
async def refresh_token(
    refresh_token_cookie: str | None = Cookie(None, alias=_REFRESH_COOKIE_NAME),
    svc: IdentityService = Depends(get_identity_service),
) -> ApiResponse[TokenResponse]:
    from fastapi import HTTPException

    if not refresh_token_cookie:
        raise HTTPException(status_code=401, detail="No refresh token")

    import hashlib
    from src.shared.infrastructure.cache.redis_client import get_redis_client
    token_hash = hashlib.sha256(refresh_token_cookie.encode()).hexdigest()
    redis = get_redis_client()
    if await redis.exists(f"rt:blacklist:{token_hash}"):
        raise HTTPException(status_code=401, detail="Token has been revoked")

    result = await svc.refresh_token(RefreshTokenCommand(refresh_token=refresh_token_cookie))

    # The access_token JWT contains user_id and enterprise_id in its claims
    # Decode the newly issued access token to extract these values
    user_id = None
    enterprise_id = None
    try:
        from src.identity.infrastructure.jwt_service import JWTService
        jwt_svc = JWTService()
        claims = jwt_svc.decode_access_token(result["access_token"])
        user_id = uuid.UUID(claims["sub"]) if claims.get("sub") else None
        eid = claims.get("enterprise_id")
        if eid:
            enterprise_id = uuid.UUID(str(eid)) if not isinstance(eid, uuid.UUID) else eid
    except Exception:
        pass  # Non-fatal — we still return the token

    return success_response(
        TokenResponse(
            access_token=result["access_token"],
            token_type="bearer",
            user_id=user_id,
            enterprise_id=enterprise_id,
        )
    )


# ── GET /v1/auth/me ───────────────────────────────────────────────────────────

@router.get(
    "/auth/me",
    response_model=ApiResponse[UserMeResponse],
    summary="Get current authenticated user profile",
)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> ApiResponse[UserMeResponse]:
    # Map role for frontend: frontend only knows "ADMIN" and "MEMBER"
    frontend_role = current_user.role.value
    if frontend_role not in ("ADMIN",):
        frontend_role = "MEMBER"

    # Extract email string from value object
    email_str = current_user.email.value if hasattr(current_user.email, 'value') else str(current_user.email)
    # Derive full_name from email if not set
    full_name = current_user.full_name or email_str.split("@")[0]

    return success_response(
        UserMeResponse(
            id=current_user.id,
            email=email_str,
            full_name=full_name,
            role=frontend_role,
            enterprise_id=current_user.enterprise_id,
        )
    )


# ── POST /v1/auth/api-keys ────────────────────────────────────────────────────

# ── GET /v1/auth/api-keys ─────────────────────────────────────────────────────

@router.get(
    "/auth/api-keys",
    response_model=ApiResponse[list[APIKeyListItem]],
    summary="List API keys for the current user's enterprise",
)
async def list_api_keys(
    current_user: User = Depends(get_current_user),
    svc: IdentityService = Depends(get_identity_service),
) -> ApiResponse[list[APIKeyListItem]]:
    keys = await svc.list_api_keys(
        ListAPIKeysQuery(
            enterprise_id=current_user.enterprise_id,
            requesting_user_id=current_user.id,
        )
    )
    return success_response(
        [
            APIKeyListItem(
                id=k["key_id"],
                label=k.get("label"),
                created_at=k.get("created_at"),
                last_used=k.get("last_used_at"),
            )
            for k in keys
        ]
    )


# ── POST /v1/auth/api-keys ────────────────────────────────────────────────────

@router.post(
    "/auth/api-keys",
    response_model=ApiResponse[APIKeyResponse],
    summary="Create a new API key for M2M authentication",
    dependencies=[Depends(rate_limit)],
)
async def create_api_key(
    request_body: CreateAPIKeyRequest,
    current_user: User = Depends(get_current_user),
    svc: IdentityService = Depends(get_identity_service),
) -> ApiResponse[APIKeyResponse]:
    result = await svc.create_api_key(
        CreateAPIKeyCommand(
            enterprise_id=current_user.enterprise_id,
            requesting_user_id=current_user.id,
            label=request_body.label,
        )
    )
    return success_response(
        APIKeyResponse(
            id=result["key_id"],
            key=result["raw_key"],
            label=result["label"],
        )
    )


# ── DELETE /v1/auth/api-keys/{key_id} ─────────────────────────────────────────

@router.delete(
    "/auth/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
    dependencies=[Depends(rate_limit)],
    response_class=Response,
)
async def revoke_api_key(
    key_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    svc: IdentityService = Depends(get_identity_service),
) -> Response:
    await svc.revoke_api_key(
        RevokeAPIKeyCommand(
            key_id=key_id,
            enterprise_id=current_user.enterprise_id,
            requesting_user_id=current_user.id,
        )
    )
    return Response(status_code=204)


# ── Enterprise ownership dependency ──────────────────────────────────────────


async def require_enterprise_access(
    enterprise_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
) -> uuid.UUID:
    """Verify current_user belongs to the target enterprise. Returns enterprise_id."""
    if current_user.enterprise_id is None:
        raise HTTPException(status_code=403, detail="User has no associated enterprise")
    if str(current_user.enterprise_id) != str(enterprise_id):
        raise HTTPException(status_code=403, detail="Access denied")
    return enterprise_id


# ── GET /v1/enterprises/{enterprise_id} ───────────────────────────────────

@router.get(
    "/enterprises/{enterprise_id}",
    response_model=ApiResponse[EnterpriseResponse],
    summary="Get enterprise profile",
    dependencies=[Depends(rate_limit)],
)
async def get_enterprise(
    enterprise_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    svc: IdentityService = Depends(get_identity_service),
) -> ApiResponse[EnterpriseResponse]:
    enterprise = await svc.get_enterprise(
        GetEnterpriseQuery(
            enterprise_id=enterprise_id,
            requesting_user_id=current_user.id,
        )
    )
    return success_response(EnterpriseResponse.from_domain(enterprise))


# ── PATCH /v1/enterprises/{enterprise_id}/kyc ─────────────────────────────

ALLOWED_CONTENT_TYPES = {"application/pdf", "image/jpeg", "image/png"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB

@router.patch(
    "/enterprises/{enterprise_id}/kyc",
    response_model=ApiResponse[KYCStatusResponse],
    summary="Submit KYC documents (multipart/form-data)",
    dependencies=[Depends(require_role("ADMIN", "MEMBER"))],
)
async def submit_kyc(
    enterprise_id: uuid.UUID = Depends(require_enterprise_access),
    documents: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    svc: IdentityService = Depends(get_identity_service),
) -> ApiResponse[KYCStatusResponse]:
    import pathlib

    # Validate file types and sizes
    for doc in documents:
        if doc.content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"File '{doc.filename}' has unsupported type '{doc.content_type}'. Allowed: PDF, JPG, PNG",
            )
        contents = await doc.read()
        if len(contents) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File '{doc.filename}' exceeds 10MB limit",
            )
        await doc.seek(0)  # Reset file pointer after reading

    # Store files to disk
    upload_dir = pathlib.Path("uploads/kyc") / str(enterprise_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_metadata = []
    for doc in documents:
        file_path = upload_dir / (doc.filename or "document")
        contents = await doc.read()
        file_path.write_bytes(contents)
        file_metadata.append({
            "filename": doc.filename,
            "content_type": doc.content_type,
            "size_bytes": len(contents),
            "storage_path": str(file_path),
        })

    # Submit KYC via service layer (transitions status to KYC_SUBMITTED/PENDING)
    result = await svc.submit_kyc(
        SubmitKYCCommand(
            enterprise_id=enterprise_id,
            requesting_user_id=current_user.id,
            documents={"files": file_metadata},
        )
    )

    # Map backend KYC status to frontend value
    from src.identity.api.schemas import _KYC_STATUS_MAP
    frontend_status = _KYC_STATUS_MAP.get(result["kyc_status"], "PENDING")

    return success_response(
        KYCStatusResponse(
            kyc_status=frontend_status,
            message="KYC documents submitted for review",
        )
    )


# ── PUT /v1/enterprises/{enterprise_id}/agent-config ──────────────────────────

@router.put(
    "/enterprises/{enterprise_id}/agent-config",
    response_model=ApiResponse[AgentConfigUpdateResponse],
    summary="Update AI agent configuration",
    dependencies=[Depends(require_role("ADMIN", "MEMBER"))],
)
async def update_agent_config(
    request_body: AgentConfigUpdateRequest,
    enterprise_id: uuid.UUID = Depends(require_enterprise_access),
    current_user: User = Depends(get_current_user),
    svc: IdentityService = Depends(get_identity_service),
) -> ApiResponse[AgentConfigUpdateResponse]:
    # Store as structured JSONB in the agent_config column
    config_dict = request_body.agent_config.model_dump()

    enterprise = await svc.update_agent_config(
        UpdateAgentConfigCommand(
            enterprise_id=enterprise_id,
            requesting_user_id=current_user.id,
            config={"__agent_config__": config_dict},
        )
    )

    return success_response(AgentConfigUpdateResponse())


# ── Wallet Endpoints (RW-02: Pera Wallet Integration) ────────────────────────


@router.get(
    "/enterprises/{enterprise_id}/wallet/challenge",
    response_model=ApiResponse[WalletChallengeResponse],
    summary="Generate wallet ownership challenge for Pera Wallet signing",
    dependencies=[Depends(require_role("ADMIN", "MEMBER", "BUYER", "SELLER")), Depends(rate_limit)],
)
async def get_wallet_challenge(
    enterprise_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
) -> ApiResponse:
    from redis.asyncio import Redis
    from src.shared.infrastructure.cache.redis_client import get_redis_instance
    from src.identity.infrastructure.wallet_verifier import WalletVerifier

    redis = await get_redis_instance()
    verifier = WalletVerifier(redis=redis)
    challenge = await verifier.create_challenge(enterprise_id)

    return success_response(
        WalletChallengeResponse(
            challenge_id=challenge.challenge_id,
            nonce=challenge.nonce,
            message_to_sign=challenge.message_to_sign,
            expires_at=challenge.expires_at.isoformat(),
        )
    )


@router.post(
    "/enterprises/{enterprise_id}/wallet/link",
    response_model=ApiResponse[EnterpriseResponse],
    summary="Link Algorand wallet after verifying signed challenge",
    dependencies=[Depends(require_role("ADMIN", "MEMBER", "BUYER", "SELLER")), Depends(rate_limit)],
)
async def link_wallet(
    enterprise_id: uuid.UUID,
    request_body: EnterpriseWalletLinkRequest,
    current_user: User = Depends(get_current_user),
    svc: IdentityService = Depends(get_identity_service),
) -> ApiResponse[EnterpriseResponse]:
    from fastapi import HTTPException
    from src.shared.infrastructure.cache.redis_client import get_redis_instance
    from src.identity.infrastructure.wallet_verifier import WalletVerifier

    redis = await get_redis_instance()
    verifier = WalletVerifier(redis=redis)

    # Verify the challenge signature
    is_valid = await verifier.verify_challenge(
        challenge_id=request_body.challenge_id,
        algorand_address=request_body.algorand_address,
        signature_b64=request_body.signature,
    )
    if not is_valid:
        raise HTTPException(
            status_code=403,
            detail="Wallet ownership verification failed. Invalid signature or expired challenge.",
        )

    # Link wallet to enterprise via dedicated domain command
    from src.identity.application.commands import LinkWalletCommand
    enterprise = await svc.link_wallet(
        LinkWalletCommand(
            enterprise_id=enterprise_id,
            requesting_user_id=current_user.id,
            algorand_address=request_body.algorand_address,
        )
    )

    log.info(
        "wallet_linked",
        enterprise_id=str(enterprise_id),
        address=request_body.algorand_address[:8] + "...",
    )
    return success_response(EnterpriseResponse.from_domain(enterprise))


@router.delete(
    "/enterprises/{enterprise_id}/wallet",
    response_model=ApiResponse[WalletUnlinkResponse],
    summary="Unlink Algorand wallet from enterprise",
    dependencies=[Depends(require_role("ADMIN", "MEMBER", "BUYER", "SELLER")), Depends(rate_limit)],
)
async def unlink_wallet(
    enterprise_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    svc: IdentityService = Depends(get_identity_service),
) -> ApiResponse[WalletUnlinkResponse]:
    from src.identity.application.commands import UnlinkWalletCommand

    enterprise = await svc.unlink_wallet(
        UnlinkWalletCommand(
            enterprise_id=enterprise_id,
            requesting_user_id=current_user.id,
        )
    )

    log.info("wallet_unlinked", enterprise_id=str(enterprise_id))
    return success_response(
        WalletUnlinkResponse(enterprise_id=str(enterprise_id))
    )


@router.get(
    "/enterprises/{enterprise_id}/wallet/balance",
    response_model=ApiResponse[WalletBalanceResponse],
    summary="Query on-chain ALGO balance and opted-in apps",
    dependencies=[Depends(rate_limit)],
)
async def get_wallet_balance(
    enterprise_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    svc: IdentityService = Depends(get_identity_service),
) -> ApiResponse[WalletBalanceResponse]:
    from fastapi import HTTPException
    from src.identity.application.queries import GetEnterpriseQuery

    enterprise = await svc.get_enterprise(
        GetEnterpriseQuery(
            enterprise_id=enterprise_id,
            requesting_user_id=current_user.id,
        )
    )

    if not enterprise.algorand_wallet:
        raise HTTPException(
            status_code=404,
            detail="No wallet linked to this enterprise",
        )

    address = enterprise.algorand_wallet.value

    # Query Algorand node for balance
    try:
        import os
        from algosdk.v2client.algod import AlgodClient

        algod_address = os.environ.get(
            "ALGORAND_ALGOD_ADDRESS", "http://localhost:4001"
        )
        algod_token = os.environ.get(
            "ALGORAND_ALGOD_TOKEN",
            "a" * 64,
        )
        client = AlgodClient(algod_token, algod_address)
        info = client.account_info(address)

        balance = info.get("amount", 0)
        min_balance = info.get("min-balance", 100000)
        available = max(0, balance - min_balance)

        apps = []
        for app in info.get("apps-local-state", []):
            apps.append(OptedInApp(app_id=app["id"], app_name=None))

        return success_response(
            WalletBalanceResponse(
                algorand_address=address,
                algo_balance_microalgo=balance,
                algo_balance_algo=str(balance / 1_000_000),
                min_balance=min_balance,
                available_balance=available,
                opted_in_apps=apps,
            )
        )
    except Exception as exc:
        log.warning(
            "wallet_balance_query_failed",
            address=address[:8] + "...",
            error=str(exc),
        )
        raise HTTPException(
            status_code=502,
            detail=f"Failed to query Algorand node: {exc}",
        )
