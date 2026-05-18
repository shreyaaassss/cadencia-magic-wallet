"""
x402 Algorand payment middleware — FastAPI dependency.

context.md §3: FastAPI imports ONLY in api/ and middleware layers.
Implements the Algorand-native x402 HTTP payment protocol:
  1. No X-PAYMENT header  → raise HTTP 402 with payment requirements + fresh nonce
  2. X-PAYMENT present    → decode signed txn, validate, broadcast, confirm, record

Usage:
    @router.get("/some/gated/route", dependencies=[Depends(require_x402_payment)])
    async def gated_endpoint(): ...
"""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.algorand_client import broadcast_and_confirm
from src.shared.infrastructure.cache.redis_client import get_redis
from src.shared.infrastructure.db.session import get_db_session
from src.shared.infrastructure.logging import get_logger

log = get_logger(__name__)

# ── Configuration helpers ─────────────────────────────────────────────────────


def _required_amount() -> int:
    return int(os.environ.get("X402_PAYMENT_AMOUNT_MICROALGO", "100000"))


def _platform_wallet() -> str:
    wallet = os.environ.get("PLATFORM_WALLET", "")
    if not wallet:
        raise RuntimeError(
            "PLATFORM_WALLET env var is not set. "
            "Required for x402 payment validation. See .env.example."
        )
    return wallet


def _nonce_ttl() -> int:
    return int(os.environ.get("X402_NONCE_TTL_SECONDS", "300"))


# ── Redis nonce key helpers ───────────────────────────────────────────────────

_PENDING_PREFIX = "x402:pending:"
_USED_PREFIX = "x402:used:"


# ── Pydantic model for payment requirements ───────────────────────────────────


class X402PaymentRequirements(BaseModel):
    """Payment requirements returned in HTTP 402 response body."""

    scheme: str = "algorand-payment"
    version: str = "1"
    amount: int
    recipient: str
    currency: str = "ALGO"
    nonce: str
    expires_at: int


def _build_requirements() -> X402PaymentRequirements:
    """Generate a fresh set of payment requirements with a new nonce."""
    ttl = _nonce_ttl()
    return X402PaymentRequirements(
        amount=_required_amount(),
        recipient=_platform_wallet(),
        nonce=str(uuid.uuid4()),
        expires_at=int(time.time()) + ttl,
    )


# ── Payment validation internals ──────────────────────────────────────────────


async def _raise_402(redis: Redis) -> None:
    """Generate fresh requirements, store pending nonce, raise HTTP 402."""
    req = _build_requirements()
    ttl = _nonce_ttl()

    # Store the pending nonce so we can verify it on retry
    pending_key = f"{_PENDING_PREFIX}{req.nonce}"
    try:
        await redis.setex(
            pending_key,
            ttl,
            json.dumps({"amount": req.amount, "recipient": req.recipient, "expires_at": req.expires_at}),
        )
    except Exception as exc:
        log.warning("x402_nonce_store_failed", error=str(exc))
        # Fallback: proceed without nonce pre-storage (less secure, but non-blocking)

    log.info("x402_payment_required", nonce=req.nonce[:8] + "...", amount=req.amount)
    raise HTTPException(status_code=402, detail=req.model_dump())


async def _validate_payment(
    x_payment: str,
    x_payment_nonce: str,
    request: Request,
    session: AsyncSession,
    redis: Redis,
) -> None:
    """
    Full payment validation pipeline:
      1. Check nonce not already used (anti-replay)
      2. Look up pending nonce in Redis (authenticity check)
      3. Decode signed transaction
      4. Validate amount, recipient, nonce match, expiry
      5. Broadcast + confirm on Algorand
      6. Mark nonce as used
      7. Record payment in x402_payments table
    """
    from algosdk import encoding  # type: ignore[import-untyped]

    # ── 1. Anti-replay: reject already-used nonces ────────────────────────────
    used_key = f"{_USED_PREFIX}{x_payment_nonce}"
    if await redis.get(used_key):
        log.warning("x402_nonce_replay_attempt", nonce=x_payment_nonce[:8])
        raise HTTPException(status_code=402, detail="Nonce already used — replay rejected")

    # ── 2. Verify nonce was legitimately issued by this server ────────────────
    pending_key = f"{_PENDING_PREFIX}{x_payment_nonce}"
    pending_raw = await redis.get(pending_key)
    if pending_raw is None:
        log.warning("x402_unknown_nonce", nonce=x_payment_nonce[:8])
        raise HTTPException(
            status_code=402,
            detail="Unknown or expired payment nonce — request a new 402 challenge",
        )

    pending_data: dict[str, Any] = json.loads(pending_raw)

    # Check expiry from stored pending data
    if time.time() > pending_data.get("expires_at", 0):
        await redis.delete(pending_key)
        raise HTTPException(status_code=402, detail="Payment nonce has expired")

    # ── 3. Decode signed transaction ──────────────────────────────────────────
    try:
        stxn = encoding.msgpack_decode(x_payment)
        txn = stxn.transaction
    except Exception as exc:
        log.warning("x402_txn_decode_error", error=str(exc))
        raise HTTPException(status_code=402, detail=f"Invalid signed transaction: {exc}")

    # ── 4a. Validate recipient matches platform wallet ────────────────────────
    platform_wallet = _platform_wallet()
    txn_receiver = getattr(txn, "receiver", None)
    if txn_receiver != platform_wallet:
        log.warning(
            "x402_wrong_recipient",
            expected=platform_wallet[:8],
            got=str(txn_receiver)[:8] if txn_receiver else "none",
        )
        raise HTTPException(status_code=402, detail="Payment recipient does not match platform wallet")

    # ── 4b. Validate amount ───────────────────────────────────────────────────
    txn_amount = getattr(txn, "amt", 0) or 0
    required = pending_data.get("amount", _required_amount())
    if txn_amount < required:
        log.warning("x402_insufficient_amount", required=required, got=txn_amount)
        raise HTTPException(
            status_code=402,
            detail=f"Payment amount insufficient: required {required} microALGO, got {txn_amount}",
        )

    # ── 4c. Validate nonce embedded in transaction note ───────────────────────
    note_bytes = getattr(txn, "note", None)
    if note_bytes:
        try:
            note_text = note_bytes.decode("utf-8") if isinstance(note_bytes, bytes) else str(note_bytes)
            note_data = json.loads(note_text)
            note_nonce = note_data.get("nonce", "")
            if note_nonce and note_nonce != x_payment_nonce:
                log.warning("x402_nonce_mismatch_in_txn", header=x_payment_nonce[:8])
                raise HTTPException(status_code=402, detail="Nonce in transaction note does not match header")
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Note field may not contain JSON — tolerate missing nonce in note
            pass

    # ── 5. Broadcast and confirm on Algorand ──────────────────────────────────
    try:
        confirm_result = await broadcast_and_confirm(x_payment)
    except RuntimeError as exc:
        log.warning("x402_broadcast_failed", error=str(exc))
        raise HTTPException(status_code=402, detail=f"Algorand payment failed: {exc}")

    tx_id: str = confirm_result["tx_id"]
    confirmed_round: int = confirm_result.get("confirmed_round", 0)

    # ── 6. Consume nonce: delete pending, mark used ───────────────────────────
    ttl_remaining = max(1, int(pending_data.get("expires_at", 0)) - int(time.time()))
    await redis.delete(pending_key)
    await redis.setex(used_key, ttl_remaining + 60, "1")  # keep used marker a bit longer

    # ── 7. Record payment in x402_payments table ──────────────────────────────
    try:
        from src.wallet.models import X402PaymentModel  # local import avoids circular deps

        sender = getattr(txn, "sender", "unknown")
        resource_url = str(request.url.path)

        payment_record = X402PaymentModel(
            id=uuid.uuid4(),
            buyer_address=sender,
            tx_id=tx_id,
            amount=txn_amount,
            resource_url=resource_url,
            nonce=x_payment_nonce,
            confirmed_round=confirmed_round,
        )
        session.add(payment_record)
        await session.commit()
    except Exception as exc:
        # Non-fatal: payment is already confirmed on-chain; DB record failure should not block response
        log.warning("x402_record_failed", tx_id=tx_id[:12], error=str(exc))
        await session.rollback()

    log.info(
        "x402_payment_accepted",
        tx_id=tx_id[:12] + "...",
        amount=txn_amount,
        confirmed_round=confirmed_round,
        path=str(request.url.path),
    )


# ── Public FastAPI dependency ─────────────────────────────────────────────────


async def require_x402_payment(
    request: Request,
    x_payment: Annotated[str | None, Header()] = None,
    x_payment_nonce: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),  # type: ignore[type-arg]
) -> None:
    """
    FastAPI dependency enforcing x402 Algorand payment on protected endpoints.

    No payment headers   → HTTP 402 with fresh payment requirements JSON
    Valid payment        → request proceeds (returns None)
    Invalid payment      → HTTP 402 with error detail
    """
    if not x_payment or not x_payment_nonce:
        await _raise_402(redis)
        return  # unreachable — _raise_402 always raises

    await _validate_payment(
        x_payment=x_payment,
        x_payment_nonce=x_payment_nonce,
        request=request,
        session=session,
        redis=redis,
    )
