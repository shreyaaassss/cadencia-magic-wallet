"""
Magic.link authentication endpoint.

Verifies the DID token issued by Magic SDK on the frontend,
finds or creates the user, auto-links their ALGO address to their enterprise,
and returns a Cadencia JWT (same RS256 system as /v1/auth/login).
"""

from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from src.shared.api.responses import ApiResponse, success_response
from src.shared.infrastructure.logging import get_logger
from src.identity.api.dependencies import get_identity_service
from src.identity.api.router import _set_refresh_cookie
from src.identity.application.services import IdentityService

log = get_logger(__name__)
router = APIRouter(prefix="/v1/auth", tags=["auth"])


class MagicLoginRequest(BaseModel):
    did_token: str       # DID token from magic.user.getIdToken()
    email: str           # User's email — for find-or-create lookup
    algo_address: str    # magic metadata.publicAddress


class MagicLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str | None = None
    enterprise_id: str | None = None


@router.post(
    "/magic-login",
    response_model=ApiResponse[MagicLoginResponse],
    summary="Authenticate via Magic.link DID token and obtain Cadencia JWT",
)
async def magic_login(
    body: MagicLoginRequest,
    response: Response,
    svc: IdentityService = Depends(get_identity_service),
) -> ApiResponse[MagicLoginResponse]:
    """
    1. Verify Magic DID token with Magic Admin SDK
    2. Find user by email — raise 401 if not found (they must register first)
    3. Auto-link their Magic Algorand address if enterprise has no wallet yet
    4. Return Cadencia JWT (same RS256 system as /v1/auth/login)
    """
    magic_secret = os.environ.get("MAGIC_SECRET_KEY")
    if not magic_secret:
        raise HTTPException(status_code=500, detail="MAGIC_SECRET_KEY not configured")

    # Verify DID token — raises if invalid or expired
    try:
        from magic import Magic as MagicAdmin  # magic-admin SDK
        magic_client = MagicAdmin(secret_key=magic_secret)
        magic_client.Token.validate(body.did_token)
    except Exception as exc:
        log.warning("magic_did_token_invalid", error=str(exc))
        raise HTTPException(status_code=401, detail="Invalid or expired Magic token")

    # Find the user by email
    result = await svc.magic_login(
        email=body.email,
        algo_address=body.algo_address,
    )

    _set_refresh_cookie(response, result["refresh_token"])

    log.info(
        "magic_login_success",
        email=body.email,
        algo_address=body.algo_address[:8] if body.algo_address else "?",
    )

    return success_response(
        MagicLoginResponse(
            access_token=result["access_token"],
            token_type="bearer",
            user_id=str(result.get("user_id", "")),
            enterprise_id=str(result.get("enterprise_id", "")) if result.get("enterprise_id") else None,
        )
    )


class MagicRegisterRequest(BaseModel):
    """
    Combined Magic-based registration request.
    Same enterprise + user fields as the regular RegisterRequest,
    but with a Magic DID token instead of a password.
    """
    did_token: str
    algo_address: str
    enterprise: dict
    user: dict   # { email, full_name } — no password


@router.post(
    "/magic-register",
    response_model=ApiResponse[MagicLoginResponse],
    summary="Register a new enterprise via Magic.link (no password)",
)
async def magic_register(
    body: MagicRegisterRequest,
    response: Response,
    svc: IdentityService = Depends(get_identity_service),
) -> ApiResponse[MagicLoginResponse]:
    """
    1. Verify Magic DID token
    2. Create enterprise + user (no password — Magic is the auth provider)
    3. Auto-link Magic publicAddress as enterprise wallet
    4. Return Cadencia JWT
    """
    magic_secret = os.environ.get("MAGIC_SECRET_KEY")
    if not magic_secret:
        raise HTTPException(status_code=500, detail="MAGIC_SECRET_KEY not configured")

    try:
        from magic import Magic as MagicAdmin
        magic_client = MagicAdmin(secret_key=magic_secret)
        magic_client.Token.validate(body.did_token)
    except Exception as exc:
        log.warning("magic_did_token_invalid_register", error=str(exc))
        raise HTTPException(status_code=401, detail="Invalid or expired Magic token")

    from decimal import Decimal
    from src.identity.application.commands import RegisterEnterpriseCommand

    ent = body.enterprise
    user_data = body.user

    # Generate a strong random password — user will never use it (Magic is auth)
    import secrets
    random_password = secrets.token_urlsafe(32) + "Aa1!"

    cmd = RegisterEnterpriseCommand(
        legal_name=ent.get("legal_name", ""),
        pan=ent.get("pan", "").upper(),
        gstin=ent.get("gstin", "").upper(),
        trade_role=ent.get("trade_role", "BUYER"),
        email=user_data.get("email", ""),
        password=random_password,
        full_name=user_data.get("full_name", ""),
        role=user_data.get("role", "MEMBER"),
        commodities=ent.get("commodities", []),
        min_order_value=Decimal(str(ent["min_order_value"])) if ent.get("min_order_value") else None,
        max_order_value=Decimal(str(ent["max_order_value"])) if ent.get("max_order_value") else None,
        industry_vertical=ent.get("industry_vertical"),
        geography=ent.get("geography", "IN"),
        address=ent.get("address"),
        facility_type=ent.get("facility_type"),
        payment_terms_accepted=ent.get("payment_terms_accepted", []),
        credit_period_days=ent.get("credit_period_days"),
        years_in_operation=ent.get("years_in_operation"),
        annual_turnover_inr=Decimal(str(ent["annual_turnover_inr"])) if ent.get("annual_turnover_inr") else None,
        quality_certifications=ent.get("quality_certifications", []),
        test_certificate_available=ent.get("test_certificate_available", False),
        third_party_inspection_allowed=ent.get("third_party_inspection_allowed", False),
    )

    result = await svc.register_enterprise(cmd)

    # Auto-link the Magic Algorand address to the newly created enterprise
    if body.algo_address:
        try:
            from src.identity.application.commands import LinkWalletCommand
            await svc.link_wallet(
                LinkWalletCommand(
                    enterprise_id=result["enterprise_id"],
                    requesting_user_id=result["user_id"],
                    algorand_address=body.algo_address,
                )
            )
            log.info(
                "magic_wallet_auto_linked",
                enterprise_id=str(result["enterprise_id"]),
                address=body.algo_address[:8],
            )
        except Exception as exc:
            log.warning("magic_wallet_auto_link_failed", error=str(exc))

    _set_refresh_cookie(response, result["refresh_token"])

    log.info(
        "magic_register_success",
        email=user_data.get("email"),
        enterprise_id=str(result["enterprise_id"]),
    )

    return success_response(
        MagicLoginResponse(
            access_token=result["access_token"],
            token_type="bearer",
            user_id=str(result.get("user_id", "")),
            enterprise_id=str(result["enterprise_id"]),
        )
    )
