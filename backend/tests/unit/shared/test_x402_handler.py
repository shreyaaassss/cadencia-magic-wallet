"""Tests for x402 payment handler — Issue #10.

Covers:
  - PaymentRequirement defaults and custom values
  - 402 response header and body building
  - SIM- token rejection
  - Payment header verification (format, session, amount, expiry, signature)
"""

from __future__ import annotations

import os
import time
from unittest.mock import patch

import pytest

from src.shared.api.x402_handler import (
    PaymentRequirement,
    build_402_response_body,
    build_402_response_headers,
    reject_sim_tokens,
    verify_payment_header,
    _is_simulation_mode_allowed,
    enforce_no_simulation_mode_at_startup,
)
from src.shared.domain.exceptions import PolicyViolation, ValidationError


# ── PaymentRequirement ───────────────────────────────────────────────────────


@pytest.mark.unit
class TestPaymentRequirement:
    def test_default_values(self):
        req = PaymentRequirement(
            amount_microalgo=100_000,
            recipient_address="TESTADDR123456789012345678901234567890123456789012345678",
            session_id="sess-001",
        )
        assert req.currency == "ALGO"
        assert req.network == "algorand-testnet"
        assert req.expiry_seconds == 300
        assert req.description == "Payment required to access this resource"

    def test_custom_description(self):
        req = PaymentRequirement(
            amount_microalgo=50_000,
            recipient_address="TESTADDR",
            session_id="sess-002",
            description="Pay for premium analytics",
        )
        assert req.description == "Pay for premium analytics"

    def test_frozen_dataclass(self):
        req = PaymentRequirement(
            amount_microalgo=100_000,
            recipient_address="TESTADDR",
            session_id="sess-001",
        )
        with pytest.raises(AttributeError):
            req.amount_microalgo = 200_000  # type: ignore[misc]


# ── build_402_response_headers ───────────────────────────────────────────────


@pytest.mark.unit
class TestBuild402ResponseHeaders:
    def test_contains_required_headers(self):
        req = PaymentRequirement(
            amount_microalgo=100_000,
            recipient_address="TESTADDR",
            session_id="sess-001",
        )
        headers = build_402_response_headers(req)
        assert headers["X-Payment-Required"] == "true"
        assert headers["X-Payment-Amount"] == "100000"
        assert headers["X-Payment-Currency"] == "ALGO"
        assert headers["X-Payment-Network"] == "algorand-testnet"
        assert headers["X-Payment-Recipient"] == "TESTADDR"
        assert headers["X-Payment-Session"] == "sess-001"

    def test_expiry_is_in_future(self):
        req = PaymentRequirement(
            amount_microalgo=100_000,
            recipient_address="TESTADDR",
            session_id="sess-001",
            expiry_seconds=600,
        )
        headers = build_402_response_headers(req)
        expiry = int(headers["X-Payment-Expires"])
        now = int(time.time())
        assert expiry > now
        assert expiry <= now + 601  # within 1s tolerance


# ── build_402_response_body ──────────────────────────────────────────────────


@pytest.mark.unit
class TestBuild402ResponseBody:
    def test_body_structure(self):
        req = PaymentRequirement(
            amount_microalgo=100_000,
            recipient_address="TESTADDR",
            session_id="sess-001",
        )
        body = build_402_response_body(req)
        assert body["success"] is False
        assert body["data"] is None
        assert body["meta"]["payment_required"] is True
        assert body["meta"]["amount"] == 100_000
        assert body["meta"]["currency"] == "ALGO"
        assert body["meta"]["recipient"] == "TESTADDR"
        assert body["meta"]["session_id"] == "sess-001"
        assert body["error"]["code"] == "PAYMENT_REQUIRED"


# ── reject_sim_tokens ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestRejectSimTokens:
    @patch.dict(os.environ, {"X402_SIMULATION_MODE": "false"})
    def test_rejects_sim_prefixed_token(self):
        with pytest.raises(PolicyViolation, match="Simulated"):
            reject_sim_tokens("SIM-abc123", "tx_id")

    @patch.dict(os.environ, {"X402_SIMULATION_MODE": "false"})
    def test_accepts_real_token(self):
        # Should not raise
        reject_sim_tokens("REAL_TX_ABC123", "tx_id")

    @patch.dict(os.environ, {"X402_SIMULATION_MODE": "true"})
    def test_accepts_sim_in_simulation_mode(self):
        # Should not raise when simulation mode is on
        reject_sim_tokens("SIM-abc123", "tx_id")

    @patch.dict(os.environ, {"X402_SIMULATION_MODE": "false"})
    def test_accepts_empty_token(self):
        # Empty string should pass (no-op)
        reject_sim_tokens("", "tx_id")

    @patch.dict(os.environ, {"X402_SIMULATION_MODE": "false"})
    def test_accepts_none_like_empty(self):
        # None-like should be handled
        reject_sim_tokens("", "tx_id")


# ── enforce_no_simulation_mode_at_startup ────────────────────────────────────


@pytest.mark.unit
class TestEnforceNoSimulationAtStartup:
    @patch.dict(os.environ, {"X402_SIMULATION_MODE": "true", "APP_ENV": "production"})
    def test_raises_in_production(self):
        with pytest.raises(RuntimeError, match="PROHIBITED in production"):
            enforce_no_simulation_mode_at_startup()

    @patch.dict(os.environ, {"X402_SIMULATION_MODE": "true", "APP_ENV": "development"})
    def test_allows_in_development(self):
        # Should NOT raise in dev
        enforce_no_simulation_mode_at_startup()

    @patch.dict(os.environ, {"X402_SIMULATION_MODE": "false", "APP_ENV": "production"})
    def test_allows_disabled_in_production(self):
        # Should NOT raise when sim mode is off
        enforce_no_simulation_mode_at_startup()


# ── verify_payment_header ────────────────────────────────────────────────────


@pytest.mark.unit
class TestVerifyPaymentHeader:
    def test_rejects_none_header(self):
        with pytest.raises(ValidationError, match="required"):
            verify_payment_header(None, "sess-001", 100_000)

    def test_rejects_too_few_parts(self):
        with pytest.raises(ValidationError, match="5 pipe-separated"):
            verify_payment_header("only|three|parts", "sess-001", 100_000)

    def test_rejects_too_many_parts(self):
        with pytest.raises(ValidationError, match="5 pipe-separated"):
            verify_payment_header("a|b|c|d|e|f", "sess-001", 100_000)

    @patch.dict(os.environ, {"X402_SIMULATION_MODE": "false"})
    def test_rejects_sim_tx_id(self):
        ts = str(int(time.time()))
        header = f"SIM-tx123|sess-001|100000|{ts}|fakesig"
        with pytest.raises(PolicyViolation, match="Simulated"):
            verify_payment_header(header, "sess-001", 100_000)

    def test_rejects_wrong_session_id(self):
        ts = str(int(time.time()))
        header = f"tx123|session-A|100000|{ts}|fakesig"
        with pytest.raises(ValidationError, match="mismatch"):
            verify_payment_header(header, "session-B", 100_000)

    def test_rejects_insufficient_amount(self):
        ts = str(int(time.time()))
        header = f"tx123|sess-001|50000|{ts}|fakesig"
        with pytest.raises(PolicyViolation, match="insufficient"):
            verify_payment_header(header, "sess-001", 100_000)

    def test_rejects_non_integer_amount(self):
        ts = str(int(time.time()))
        header = f"tx123|sess-001|abc|{ts}|fakesig"
        with pytest.raises(ValidationError, match="integer"):
            verify_payment_header(header, "sess-001", 100_000)

    def test_rejects_expired_payment(self):
        old_ts = str(int(time.time()) - 400)  # 6+ minutes ago
        header = f"tx123|sess-001|100000|{old_ts}|fakesig"
        with pytest.raises(ValidationError, match="expired"):
            verify_payment_header(header, "sess-001", 100_000)

    def test_rejects_non_integer_timestamp(self):
        header = "tx123|sess-001|100000|not-a-number|fakesig"
        with pytest.raises(ValidationError, match="integer"):
            verify_payment_header(header, "sess-001", 100_000)

    @patch.dict(os.environ, {"X402_PAYMENT_SECRET": "", "X402_SIMULATION_MODE": "false"})
    def test_valid_payment_without_hmac(self):
        """With no HMAC secret, a valid header should pass."""
        ts = str(int(time.time()))
        header = f"realtx123|sess-001|100000|{ts}|nosig"
        result = verify_payment_header(header, "sess-001", 100_000)
        assert result["tx_id"] == "realtx123"
        assert result["session_id"] == "sess-001"
        assert result["amount"] == 100_000

    @patch.dict(os.environ, {"X402_PAYMENT_SECRET": "test-secret", "X402_SIMULATION_MODE": "false"})
    def test_rejects_invalid_hmac(self):
        ts = str(int(time.time()))
        header = f"realtx123|sess-001|100000|{ts}|badsignature"
        with pytest.raises(ValidationError, match="signature"):
            verify_payment_header(header, "sess-001", 100_000)

    @patch.dict(os.environ, {"X402_PAYMENT_SECRET": "test-secret", "X402_SIMULATION_MODE": "false"})
    def test_accepts_valid_hmac(self):
        import hashlib
        import hmac as hmac_mod

        ts = str(int(time.time()))
        payload = f"realtx123|sess-001|100000|{ts}"
        sig = hmac_mod.new(
            b"test-secret", payload.encode(), hashlib.sha256
        ).hexdigest()
        header = f"{payload}|{sig}"

        result = verify_payment_header(header, "sess-001", 100_000)
        assert result["tx_id"] == "realtx123"
        assert result["amount"] == 100_000

    @patch.dict(os.environ, {"X402_PAYMENT_SECRET": "", "X402_SIMULATION_MODE": "false"})
    def test_accepts_exact_amount(self):
        """Payment amount exactly equal to required should pass."""
        ts = str(int(time.time()))
        header = f"realtx123|sess-001|100000|{ts}|nosig"
        result = verify_payment_header(header, "sess-001", 100_000)
        assert result["amount"] == 100_000

    @patch.dict(os.environ, {"X402_PAYMENT_SECRET": "", "X402_SIMULATION_MODE": "false"})
    def test_accepts_overpayment(self):
        """Payment amount above required should pass."""
        ts = str(int(time.time()))
        header = f"realtx123|sess-001|200000|{ts}|nosig"
        result = verify_payment_header(header, "sess-001", 100_000)
        assert result["amount"] == 200_000
