# context.md §7.3: HMAC-signed outbound webhooks for settlement events.
# Phase 3: webhook notifier sends HTTP POST with HMAC-SHA256 signature.
# Subscribes to EscrowFunded, EscrowReleased, EscrowRefunded, EscrowFrozen events.
# NEVER sends PAN or GSTIN in webhook payload — only IDs and amounts.

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

_WEBHOOK_SECRET = os.environ.get("WEBHOOK_SIGNING_SECRET", "")
_WEBHOOK_URL = os.environ.get("WEBHOOK_DELIVERY_URL", "")
_WEBHOOK_TIMEOUT_SECONDS = int(os.environ.get("WEBHOOK_TIMEOUT_SECONDS", "10"))
_WEBHOOK_MAX_RETRIES = int(os.environ.get("WEBHOOK_MAX_RETRIES", "3"))


# ── Webhook Payload ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WebhookPayload:
    """
    Outbound webhook payload for settlement events.

    SECURITY: No PAN, GSTIN, mnemonic, or private keys in payload.
    Only IDs, amounts, transaction references, and status transitions.
    """

    webhook_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(tz=timezone.utc).isoformat()
    )
    data: dict = field(default_factory=dict)


# ── HMAC Signing ──────────────────────────────────────────────────────────────


def compute_webhook_signature(payload_bytes: bytes, secret: str) -> str:
    """
    Compute HMAC-SHA256 signature for webhook payload.

    The signature is sent as X-Cadencia-Signature header.
    Receivers should verify using constant-time comparison (hmac.compare_digest).
    """
    return hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()


def verify_webhook_signature(
    payload_bytes: bytes, signature: str, secret: str
) -> bool:
    """
    Verify HMAC-SHA256 webhook signature using constant-time comparison.

    Used by webhook receivers to authenticate webhook origin.
    """
    expected = compute_webhook_signature(payload_bytes, secret)
    return hmac.compare_digest(signature, expected)


# ── Webhook Delivery ──────────────────────────────────────────────────────────


async def deliver_webhook(
    payload: WebhookPayload,
    url: str | None = None,
    secret: str | None = None,
) -> dict:
    """
    Deliver a webhook via HTTP POST with HMAC-SHA256 signature.

    Headers:
        Content-Type:           application/json
        X-Cadencia-Event:       event type (e.g., "EscrowFunded")
        X-Cadencia-Signature:   HMAC-SHA256 hex digest
        X-Cadencia-Timestamp:   ISO-8601 timestamp
        X-Cadencia-Webhook-Id:  unique webhook delivery ID

    Retries up to WEBHOOK_MAX_RETRIES on network errors.
    Returns delivery result dict with status and response code.

    If WEBHOOK_DELIVERY_URL is not configured, logs and returns silently.
    """
    delivery_url = url or _WEBHOOK_URL
    signing_secret = secret or _WEBHOOK_SECRET

    if not delivery_url:
        log.debug(
            "webhook_delivery_skipped_no_url",
            event_type=payload.event_type,
            message="WEBHOOK_DELIVERY_URL not configured — webhook not sent.",
        )
        return {"status": "skipped", "reason": "no_url_configured"}

    # Serialize payload
    payload_json = json.dumps(
        {
            "webhook_id": payload.webhook_id,
            "event_type": payload.event_type,
            "timestamp": payload.timestamp,
            "data": payload.data,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    payload_bytes = payload_json.encode("utf-8")

    # Compute HMAC signature
    signature = compute_webhook_signature(payload_bytes, signing_secret)

    headers = {
        "Content-Type": "application/json",
        "X-Cadencia-Event": payload.event_type,
        "X-Cadencia-Signature": signature,
        "X-Cadencia-Timestamp": payload.timestamp,
        "X-Cadencia-Webhook-Id": payload.webhook_id,
    }

    # Deliver with retries
    import httpx

    last_error: str = ""
    for attempt in range(1, _WEBHOOK_MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=_WEBHOOK_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    delivery_url,
                    content=payload_bytes,
                    headers=headers,
                )

            if response.status_code < 300:
                log.info(
                    "webhook_delivered",
                    webhook_id=payload.webhook_id,
                    event_type=payload.event_type,
                    url=delivery_url,
                    status_code=response.status_code,
                    attempt=attempt,
                )
                return {
                    "status": "delivered",
                    "webhook_id": payload.webhook_id,
                    "status_code": response.status_code,
                    "attempt": attempt,
                }
            else:
                last_error = f"HTTP {response.status_code}"
                log.warning(
                    "webhook_delivery_non_2xx",
                    webhook_id=payload.webhook_id,
                    event_type=payload.event_type,
                    status_code=response.status_code,
                    attempt=attempt,
                )

        except Exception as exc:
            last_error = str(exc)
            log.warning(
                "webhook_delivery_error",
                webhook_id=payload.webhook_id,
                event_type=payload.event_type,
                attempt=attempt,
                error=str(exc),
            )

    # All retries exhausted
    log.error(
        "webhook_delivery_failed",
        webhook_id=payload.webhook_id,
        event_type=payload.event_type,
        url=delivery_url,
        last_error=last_error,
        max_retries=_WEBHOOK_MAX_RETRIES,
    )
    return {
        "status": "failed",
        "webhook_id": payload.webhook_id,
        "last_error": last_error,
        "attempts": _WEBHOOK_MAX_RETRIES,
    }


# ── Event-to-Webhook Builders ────────────────────────────────────────────────


def _build_safe_payload(event: object, fields: list[str]) -> dict:
    """
    Extract only the named fields from a domain event.

    SECURITY: Only whitelisted fields are included — no PAN, GSTIN,
    mnemonic, private key, or other sensitive data leaks.
    """
    data: dict[str, Any] = {}
    for f in fields:
        val = getattr(event, f, None)
        if val is not None:
            data[f] = str(val) if isinstance(val, uuid.UUID) else val
    return data


async def notify_escrow_funded(event: object) -> None:
    """Webhook for EscrowFunded event. No PAN/GSTIN in payload."""
    data = _build_safe_payload(event, [
        "escrow_id", "session_id", "amount_microalgo", "fund_tx_id",
    ])
    payload = WebhookPayload(event_type="EscrowFunded", data=data)
    await deliver_webhook(payload)


async def notify_escrow_released(event: object) -> None:
    """Webhook for EscrowReleased event. No PAN/GSTIN in payload."""
    data = _build_safe_payload(event, [
        "escrow_id", "session_id", "amount_microalgo",
        "release_tx_id", "merkle_root",
    ])
    payload = WebhookPayload(event_type="EscrowReleased", data=data)
    await deliver_webhook(payload)


async def notify_escrow_refunded(event: object) -> None:
    """Webhook for EscrowRefunded event. No PAN/GSTIN in payload."""
    data = _build_safe_payload(event, [
        "escrow_id", "session_id", "amount_microalgo",
        "refund_tx_id", "reason",
    ])
    payload = WebhookPayload(event_type="EscrowRefunded", data=data)
    await deliver_webhook(payload)


async def notify_escrow_frozen(event: object) -> None:
    """Webhook for EscrowFrozen event. No PAN/GSTIN in payload."""
    data = _build_safe_payload(event, [
        "escrow_id", "session_id", "frozen_by",
    ])
    payload = WebhookPayload(event_type="EscrowFrozen", data=data)
    await deliver_webhook(payload)
