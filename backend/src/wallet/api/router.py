"""
Short-form wallet router — /v1/wallet/* endpoints.

These proxy to the existing enterprise-scoped wallet logic in the identity module,
resolving enterprise_id from the JWT's claims automatically. The frontend's
WalletContext.tsx calls these short-form paths exclusively.

Existing enterprise-scoped routes remain untouched at /v1/enterprises/{id}/wallet/*.
"""

from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.identity.api.dependencies import (
    get_current_user,
    get_identity_service,
)
from src.identity.application.commands import LinkWalletCommand, UnlinkWalletCommand
from src.identity.domain.user import User
from src.identity.infrastructure.models import EnterpriseModel
from src.settlement.infrastructure.models import EscrowContractModel
from src.shared.api.responses import ApiResponse, success_response
from src.shared.infrastructure.db.session import get_db_session
from src.shared.infrastructure.logging import get_logger
from src.wallet.schemas import (
    OptedInApp,
    WalletBalanceResponse,
    WalletChallengeResponse,
    WalletLinkRequest,
    WalletLinkResponse,
    WalletUnlinkResponse,
)

log = get_logger(__name__)

router = APIRouter(
    prefix="/v1/wallet",
    tags=["wallet"],
    dependencies=[Depends(get_current_user)],
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _require_enterprise(user: User) -> uuid.UUID:
    """Extract enterprise_id from JWT-authenticated user. 400 if missing."""
    if not user.enterprise_id:
        raise HTTPException(
            status_code=400,
            detail="No enterprise associated with this account",
        )
    return user.enterprise_id


# ── 1. GET /v1/wallet/challenge ───────────────────────────────────────────────


@router.get(
    "/challenge",
    response_model=ApiResponse[WalletChallengeResponse],
    summary="Generate wallet ownership challenge for Pera Wallet signing",
)
async def get_wallet_challenge(
    current_user: User = Depends(get_current_user),
) -> ApiResponse[WalletChallengeResponse]:
    """
    Initiates the wallet linking flow. Returns a unique nonce that the user
    must sign with their Algorand private key via Pera Wallet.
    """
    enterprise_id = _require_enterprise(current_user)

    from src.identity.infrastructure.wallet_verifier import WalletVerifier
    from src.shared.infrastructure.cache.redis_client import get_redis_instance

    redis = await get_redis_instance()
    verifier = WalletVerifier(redis=redis)

    # Invalidate any prior unused challenge for this enterprise
    # (Redis key pattern: wallet_challenge:wc-*)
    # The verifier's create_challenge generates a new unique key each time;
    # old keys expire via TTL. For strict single-active-challenge, delete prior ones.
    pattern = "wallet_challenge:*"
    try:
        async for key in redis.scan_iter(match=pattern):
            stored = await redis.get(key)
            if stored:
                stored_str = stored.decode() if isinstance(stored, bytes) else stored
                parts = stored_str.split("|", 1)
                if len(parts) == 2 and parts[1] == str(enterprise_id):
                    await redis.delete(key)
    except Exception:
        pass  # Best-effort cleanup — Redis scan failures are non-fatal

    challenge = await verifier.create_challenge(enterprise_id)

    return success_response(
        WalletChallengeResponse(
            challenge=challenge.message_to_sign,
            enterprise_id=str(enterprise_id),
            expires_at=challenge.expires_at.isoformat(),
        )
    )


# ── 2. POST /v1/wallet/link ──────────────────────────────────────────────────


@router.post(
    "/link",
    response_model=ApiResponse[WalletLinkResponse],
    summary="Link Algorand wallet after verifying signed challenge transaction",
)
async def link_wallet(
    body: WalletLinkRequest,
    current_user: User = Depends(get_current_user),
    svc=Depends(get_identity_service),
    db: AsyncSession = Depends(get_db_session),
) -> ApiResponse[WalletLinkResponse]:
    """
    Completes the wallet linking flow. The frontend signs a zero-value
    self-payment transaction containing the challenge message in the note
    field. This endpoint decodes and verifies the signed transaction.

    Works with any Algorand wallet (Pera, Defly, etc.) via @txnlab/use-wallet.
    """
    enterprise_id = _require_enterprise(current_user)

    # Check if address is already linked to a different enterprise
    existing = await db.execute(
        select(EnterpriseModel).where(
            and_(
                EnterpriseModel.algorand_wallet == body.algorand_address,
                EnterpriseModel.id != enterprise_id,
            )
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail="This wallet address is already linked to another enterprise",
        )

    # Verify the signed challenge transaction
    from src.identity.infrastructure.wallet_verifier import WalletVerifier
    from src.shared.infrastructure.cache.redis_client import get_redis_instance

    redis = await get_redis_instance()
    verifier = WalletVerifier(redis=redis)

    is_valid = await verifier.verify_challenge_txn(
        enterprise_id=enterprise_id,
        algorand_address=body.algorand_address,
        signed_txn_b64=body.signed_txn,
    )
    if not is_valid:
        raise HTTPException(
            status_code=400,
            detail="Challenge verification failed. Ensure you signed the correct challenge with the claimed wallet.",
        )

    # Link wallet via the existing identity service
    await svc.link_wallet(
        LinkWalletCommand(
            enterprise_id=enterprise_id,
            requesting_user_id=current_user.id,
            algorand_address=body.algorand_address,
        )
    )

    log.info(
        "wallet_linked_shortform",
        enterprise_id=str(enterprise_id),
        address=body.algorand_address[:8] + "...",
    )

    return success_response(
        WalletLinkResponse(
            algorand_address=body.algorand_address,
            message="Wallet linked successfully",
        )
    )


# ── 3. DELETE /v1/wallet/link ─────────────────────────────────────────────────


@router.delete(
    "/link",
    response_model=ApiResponse[WalletUnlinkResponse],
    summary="Unlink Algorand wallet from enterprise",
)
async def unlink_wallet(
    current_user: User = Depends(get_current_user),
    svc=Depends(get_identity_service),
    db: AsyncSession = Depends(get_db_session),
) -> ApiResponse[WalletUnlinkResponse]:
    """
    Unlinks the Algorand wallet from the enterprise. Blocks if there are
    active or funded escrow contracts.
    """
    enterprise_id = _require_enterprise(current_user)

    # Check if enterprise has a wallet linked
    result = await db.execute(
        select(EnterpriseModel.algorand_wallet).where(
            EnterpriseModel.id == enterprise_id
        )
    )
    wallet_address = result.scalar_one_or_none()
    if not wallet_address:
        raise HTTPException(
            status_code=400,
            detail="No wallet is currently linked to this enterprise",
        )

    # Block unlink if there are active/funded escrows
    active_escrow_statuses = ("DEPLOYED", "FUNDED")
    escrow_result = await db.execute(
        select(EscrowContractModel.id).where(
            and_(
                EscrowContractModel.buyer_algorand_address == wallet_address,
                EscrowContractModel.status.in_(active_escrow_statuses),
            )
        ).limit(1)
    )
    # Also check seller side
    if escrow_result.scalar_one_or_none() is None:
        escrow_result = await db.execute(
            select(EscrowContractModel.id).where(
                and_(
                    EscrowContractModel.seller_algorand_address == wallet_address,
                    EscrowContractModel.status.in_(active_escrow_statuses),
                )
            ).limit(1)
        )
    if escrow_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=400,
            detail="Cannot unlink wallet while active escrow contracts exist",
        )

    # Unlink via the identity service
    await svc.unlink_wallet(
        UnlinkWalletCommand(
            enterprise_id=enterprise_id,
            requesting_user_id=current_user.id,
        )
    )

    # Invalidate any active challenges for this enterprise
    try:
        from src.shared.infrastructure.cache.redis_client import get_redis_instance

        redis = await get_redis_instance()
        async for key in redis.scan_iter(match="wallet_challenge:*"):
            stored = await redis.get(key)
            if stored:
                stored_str = stored.decode() if isinstance(stored, bytes) else stored
                parts = stored_str.split("|", 1)
                if len(parts) == 2 and parts[1] == str(enterprise_id):
                    await redis.delete(key)
    except Exception:
        pass  # Best-effort

    log.info("wallet_unlinked_shortform", enterprise_id=str(enterprise_id))

    return success_response(
        WalletUnlinkResponse(message="Wallet unlinked successfully")
    )


# ── 4. GET /v1/wallet/balance ─────────────────────────────────────────────────


@router.get(
    "/balance",
    response_model=ApiResponse[WalletBalanceResponse],
    summary="Query on-chain ALGO balance and opted-in apps",
)
async def get_wallet_balance(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ApiResponse[WalletBalanceResponse]:
    """
    Fetches the current ALGO balance and opted-in app state for the
    enterprise's linked Algorand wallet from the live blockchain.

    Uses ALGORAND_BALANCE_ALGOD_ADDRESS to query the same network the
    frontend wallet (Pera) is connected to (e.g. TestNet).
    Falls back to ALGORAND_ALGOD_ADDRESS for backward compatibility.
    """
    enterprise_id = _require_enterprise(current_user)

    # Get the enterprise's wallet address
    result = await db.execute(
        select(EnterpriseModel.algorand_wallet).where(
            EnterpriseModel.id == enterprise_id
        )
    )
    wallet_address = result.scalar_one_or_none()
    if not wallet_address:
        raise HTTPException(
            status_code=404,
            detail="No wallet linked to this enterprise",
        )

    # Use a separate Algod address for balance queries.
    # ALGORAND_BALANCE_ALGOD_ADDRESS → the network the user's wallet is on (TestNet)
    # ALGORAND_ALGOD_ADDRESS → the Docker localnet (for escrow ops)
    balance_algod_address = os.environ.get(
        "ALGORAND_BALANCE_ALGOD_ADDRESS",
        os.environ.get("ALGORAND_ALGOD_ADDRESS", "https://testnet-api.4160.nodely.dev"),
    )
    balance_algod_token = os.environ.get(
        "ALGORAND_BALANCE_ALGOD_TOKEN",
        os.environ.get("ALGORAND_ALGOD_TOKEN", ""),
    )

    try:
        import httpx

        # Use async httpx to avoid blocking the event loop
        headers = {}
        if balance_algod_token:
            headers["X-Algo-API-Token"] = balance_algod_token

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{balance_algod_address}/v2/accounts/{wallet_address}",
                headers=headers,
            )

        if response.status_code != 200:
            log.warning(
                "wallet_balance_algod_error",
                address=wallet_address[:8] + "...",
                status_code=response.status_code,
                algod_address=balance_algod_address,
                body=response.text[:200],
            )
            raise HTTPException(
                status_code=502,
                detail=f"Algorand node returned {response.status_code}. Ensure the wallet exists on the configured network.",
            )

        info = response.json()
        balance_microalgo = info.get("amount", 0)
        min_balance = info.get("min-balance", 100000)
        available = balance_microalgo - min_balance

        # Build opted-in apps list, cross-referencing escrow table for names
        apps = []
        for app in info.get("apps-local-state", []):
            app_id = app.get("id", 0)
            app_name = None

            try:
                escrow = await db.execute(
                    select(EscrowContractModel.id).where(
                        EscrowContractModel.algo_app_id == app_id
                    )
                )
                if escrow.scalar_one_or_none() is not None:
                    app_name = "Cadencia Escrow"
            except Exception:
                pass

            apps.append(OptedInApp(app_id=app_id, app_name=app_name))

        log.info(
            "wallet_balance_fetched",
            address=wallet_address[:8] + "...",
            balance_algo=str(balance_microalgo / 1_000_000),
            algod=balance_algod_address,
        )

        return success_response(
            WalletBalanceResponse(
                algorand_address=wallet_address,
                algo_balance_microalgo=balance_microalgo,
                algo_balance_algo=str(balance_microalgo / 1_000_000),
                min_balance=min_balance,
                available_balance=available,
                opted_in_apps=apps,
            )
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.warning(
            "wallet_balance_query_failed",
            address=wallet_address[:8] + "...",
            error=str(exc),
            algod_address=balance_algod_address,
        )
        raise HTTPException(
            status_code=502,
            detail="Unable to reach Algorand network. Please try again.",
        )
