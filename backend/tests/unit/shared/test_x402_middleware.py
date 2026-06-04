"""Tests for x402 payment middleware — Issue #10.

Covers:
  - Nonce generation uniqueness
  - Payment requirements building
  - Missing headers → 402
  - Used nonce → replay rejection
  - Expired nonce → rejection
  - Configuration helpers
"""

from __future__ import annotations

import json
import os
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.shared.middleware.x402_payment import (
    X402PaymentRequirements,
    _build_requirements,
    _nonce_ttl,
    _required_amount,
)


# ── Configuration helpers ────────────────────────────────────────────────────


@pytest.mark.unit
class TestConfigHelpers:
    @patch.dict(os.environ, {"X402_PAYMENT_AMOUNT_MICROALGO": "200000"})
    def test_required_amount_from_env(self):
        assert _required_amount() == 200_000

    @patch.dict(os.environ, {}, clear=False)
    def test_required_amount_default(self):
        # If env var is missing, default is 100000
        if "X402_PAYMENT_AMOUNT_MICROALGO" not in os.environ:
            assert _required_amount() == 100_000

    @patch.dict(os.environ, {"X402_NONCE_TTL_SECONDS": "600"})
    def test_nonce_ttl_from_env(self):
        assert _nonce_ttl() == 600

    @patch.dict(os.environ, {}, clear=False)
    def test_nonce_ttl_default(self):
        if "X402_NONCE_TTL_SECONDS" not in os.environ:
            assert _nonce_ttl() == 300


# ── PaymentRequirements model ────────────────────────────────────────────────


@pytest.mark.unit
class TestPaymentRequirements:
    def test_model_defaults(self):
        req = X402PaymentRequirements(
            amount=100_000,
            recipient="TESTADDR",
            nonce="test-nonce",
            expires_at=int(time.time()) + 300,
        )
        assert req.scheme == "algorand-payment"
        assert req.version == "1"
        assert req.currency == "ALGO"

    def test_model_serialization(self):
        req = X402PaymentRequirements(
            amount=100_000,
            recipient="TESTADDR",
            nonce="test-nonce",
            expires_at=1700000000,
        )
        data = req.model_dump()
        assert data["amount"] == 100_000
        assert data["recipient"] == "TESTADDR"
        assert data["nonce"] == "test-nonce"
        assert "scheme" in data


# ── Nonce uniqueness ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestNonceUniqueness:
    @patch.dict(os.environ, {"PLATFORM_WALLET": "TESTADDR"})
    def test_nonces_are_unique(self):
        """Generated nonces should be unique across multiple calls."""
        nonces = set()
        for _ in range(50):
            req = _build_requirements()
            assert req.nonce not in nonces
            nonces.add(req.nonce)

    @patch.dict(os.environ, {"PLATFORM_WALLET": "TESTADDR"})
    def test_nonce_is_valid_uuid(self):
        """Nonce should be a valid UUID string."""
        req = _build_requirements()
        parsed = uuid.UUID(req.nonce)
        assert str(parsed) == req.nonce


# ── Build requirements ───────────────────────────────────────────────────────


@pytest.mark.unit
class TestBuildRequirements:
    @patch.dict(os.environ, {
        "PLATFORM_WALLET": "TESTWALLETADDR",
        "X402_PAYMENT_AMOUNT_MICROALGO": "150000",
        "X402_NONCE_TTL_SECONDS": "600",
    })
    def test_builds_with_env_config(self):
        req = _build_requirements()
        assert req.amount == 150_000
        assert req.recipient == "TESTWALLETADDR"
        assert req.expires_at > int(time.time())
        # Expiry should be ~600s in the future
        assert req.expires_at <= int(time.time()) + 601

    @patch.dict(os.environ, {"PLATFORM_WALLET": ""}, clear=False)
    def test_raises_without_platform_wallet(self):
        """Missing PLATFORM_WALLET should raise RuntimeError."""
        with pytest.raises(RuntimeError, match="PLATFORM_WALLET"):
            _build_requirements()


# ── require_x402_payment dependency (unit-level logic tests) ─────────────────


@pytest.mark.unit
class TestRequireX402PaymentLogic:
    """
    These test the logical flow of the dependency without running a full
    FastAPI app. We test that:
    - Missing headers trigger a 402
    - Used nonces are rejected
    - Expired nonces are rejected
    """

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"PLATFORM_WALLET": "TESTADDR"})
    async def test_missing_headers_raises_402(self):
        """When no payment headers are provided, a 402 should be raised."""
        from fastapi import HTTPException
        from src.shared.middleware.x402_payment import require_x402_payment

        mock_request = MagicMock()
        mock_session = AsyncMock()
        mock_redis = AsyncMock()
        # Redis setex for nonce storage
        mock_redis.setex = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await require_x402_payment(
                request=mock_request,
                x_payment=None,
                x_payment_nonce=None,
                session=mock_session,
                redis=mock_redis,
            )
        assert exc_info.value.status_code == 402

    @pytest.mark.asyncio
    async def test_used_nonce_rejected(self):
        """A nonce that has already been used should be rejected."""
        from fastapi import HTTPException
        from src.shared.middleware.x402_payment import _validate_payment

        mock_request = MagicMock()
        mock_request.url.path = "/test"
        mock_session = AsyncMock()
        mock_redis = AsyncMock()
        # Simulate: used nonce exists in Redis
        mock_redis.get = AsyncMock(side_effect=lambda key: b"1" if "used:" in key else None)

        with pytest.raises(HTTPException) as exc_info:
            await _validate_payment(
                x_payment="fake-signed-txn",
                x_payment_nonce="already-used-nonce",
                request=mock_request,
                session=mock_session,
                redis=mock_redis,
            )
        assert exc_info.value.status_code == 402
        assert "replay" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_unknown_nonce_rejected(self):
        """A nonce not found in pending storage should be rejected."""
        from fastapi import HTTPException
        from src.shared.middleware.x402_payment import _validate_payment

        mock_request = MagicMock()
        mock_request.url.path = "/test"
        mock_session = AsyncMock()
        mock_redis = AsyncMock()
        # No used marker, no pending marker
        mock_redis.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await _validate_payment(
                x_payment="fake-signed-txn",
                x_payment_nonce="unknown-nonce",
                request=mock_request,
                session=mock_session,
                redis=mock_redis,
            )
        assert exc_info.value.status_code == 402
        assert "unknown" in str(exc_info.value.detail).lower() or "expired" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_expired_nonce_rejected(self):
        """A nonce whose expiry has passed should be rejected."""
        from fastapi import HTTPException
        from src.shared.middleware.x402_payment import _validate_payment

        mock_request = MagicMock()
        mock_request.url.path = "/test"
        mock_session = AsyncMock()
        mock_redis = AsyncMock()

        # Build pending data with past expiry
        expired_data = json.dumps({
            "amount": 100_000,
            "recipient": "TESTADDR",
            "expires_at": int(time.time()) - 100,  # Expired 100s ago
        })

        # Return None for used-key, expired data for pending-key
        async def mock_get(key):
            if "used:" in key:
                return None
            if "pending:" in key:
                return expired_data.encode()
            return None

        mock_redis.get = AsyncMock(side_effect=mock_get)
        mock_redis.delete = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await _validate_payment(
                x_payment="fake-signed-txn",
                x_payment_nonce="expired-nonce",
                request=mock_request,
                session=mock_session,
                redis=mock_redis,
            )
        assert exc_info.value.status_code == 402
        assert "expired" in str(exc_info.value.detail).lower()
