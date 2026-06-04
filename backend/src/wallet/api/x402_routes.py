"""
x402 public routes — payment requirements and verification.

GET /x402/payment-requirements  — Returns a fresh payment requirements object.
                                   No auth required; called before making a gated request.
GET /x402/verify/{tx_id}        — Check if a given Algorand txId has been paid and confirmed.
GET /x402/payment-history       — List x402 payments for a given buyer_address (authenticated).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.api.responses import ApiResponse, success_response
from src.shared.infrastructure.db.session import get_db_session
from src.shared.infrastructure.logging import get_logger
from src.shared.middleware.x402_payment import X402PaymentRequirements, _build_requirements
from src.wallet.models import X402PaymentModel

log = get_logger(__name__)

router = APIRouter(prefix="/v1/x402", tags=["x402"])


# ── GET /x402/payment-requirements ───────────────────────────────────────────


@router.get(
    "/payment-requirements",
    response_model=ApiResponse[X402PaymentRequirements],
    summary="Get current x402 payment requirements (no auth required)",
)
async def get_payment_requirements() -> dict:
    """
    Returns a fresh X402PaymentRequirements object with a new nonce.

    Clients can call this proactively to pre-fetch requirements before
    hitting a gated endpoint, saving one round-trip.

    Note: This endpoint does NOT pre-store the nonce in Redis. The nonce
    is only stored when the 402 is actually raised by require_x402_payment.
    For the authoritative nonce, use the 402 response from the gated endpoint.
    """
    req = _build_requirements()
    return success_response(req)


# ── GET /x402/verify/{tx_id} ─────────────────────────────────────────────────


@router.get(
    "/verify/{tx_id}",
    response_model=ApiResponse[dict],
    summary="Verify a payment transaction by Algorand txId",
)
async def verify_payment(
    tx_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Check whether the given Algorand transaction ID exists in the x402_payments
    table (i.e. was accepted by this server) and return its confirmation status.
    """
    stmt = select(X402PaymentModel).where(X402PaymentModel.tx_id == tx_id)
    result = await session.execute(stmt)
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"Transaction '{tx_id}' not found in x402 payment records",
        )

    return success_response(
        {
            "tx_id": record.tx_id,
            "confirmed": record.confirmed_round is not None,
            "confirmed_round": record.confirmed_round,
            "amount": record.amount,
            "buyer_address": record.buyer_address,
            "resource_url": record.resource_url,
            "paid_at": record.paid_at,
        }
    )


# ── GET /x402/payment-history ─────────────────────────────────────────────────


@router.get(
    "/payment-history",
    response_model=ApiResponse[list],
    summary="List x402 payment records for a buyer address",
)
async def payment_history(
    buyer_address: str = Query(..., description="Algorand address to look up"),
    limit: int = Query(default=5, ge=1, le=50),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Returns the most recent x402 payments made from a given Algorand address.
    Used by the WalletWidget to display payment history.
    """
    stmt = (
        select(X402PaymentModel)
        .where(X402PaymentModel.buyer_address == buyer_address)
        .order_by(X402PaymentModel.paid_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    records = result.scalars().all()

    return success_response(
        [
            {
                "id": str(r.id),
                "tx_id": r.tx_id,
                "amount": r.amount,
                "resource_url": r.resource_url,
                "nonce": r.nonce,
                "confirmed_round": r.confirmed_round,
                "paid_at": r.paid_at,
            }
            for r in records
        ]
    )
