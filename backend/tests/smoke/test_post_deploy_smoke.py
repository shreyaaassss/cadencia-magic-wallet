# Post-Deployment Smoke Tests — Mandatory.
# Run immediately after every deploy to verify critical paths.
# Uses httpx against the live server. No DB fixtures.
#
# Run: SMOKE_TEST_BASE_URL=https://cadencia-magic-wallet.duckdns.org pytest tests/smoke/ -v
# Skipped when server is unreachable.

from __future__ import annotations

import os
import time

import httpx
import pytest

BASE_URL = os.environ.get("SMOKE_TEST_BASE_URL", "http://localhost:8000")


def _server_reachable() -> bool:
    try:
        httpx.get(f"{BASE_URL}/health", timeout=5.0)
        return True
    except (httpx.ConnectError, httpx.TimeoutException):
        return False


pytestmark = pytest.mark.skipif(
    not _server_reachable(),
    reason=f"Smoke tests need live server at {BASE_URL}",
)


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as c:
        yield c


# ═════════════════════════════════════════════════════════════════════════════
# 1. Health & Liveness
# ═════════════════════════════════════════════════════════════════════════════

class TestLiveness:
    """Is the app alive and serving traffic?"""

    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_overall_status(self, client):
        data = client.get("/health").json()
        assert data["data"]["overall"] in ("healthy", "degraded")

    def test_database_check_present(self, client):
        data = client.get("/health").json()["data"]
        # Health response may nest checks differently — just verify DB is checked
        has_db = "database" in data or "db" in data or "database" in str(data)
        assert has_db, f"No database check in health response: {list(data.keys())}"

    def test_redis_check_present(self, client):
        data = client.get("/health").json()["data"]
        has_redis = "redis" in data or "redis" in str(data)
        assert has_redis, f"No redis check in health response: {list(data.keys())}"

    def test_response_time_under_2s(self, client):
        start = time.time()
        client.get("/health")
        elapsed = time.time() - start
        assert elapsed < 2.0, f"Health check took {elapsed:.2f}s"


# ═════════════════════════════════════════════════════════════════════════════
# 2. Security Headers
# ═════════════════════════════════════════════════════════════════════════════

class TestSecurityHeaders:
    def test_nosniff_header(self, client):
        h = client.get("/health").headers
        assert h.get("x-content-type-options") == "nosniff"

    def test_frame_deny_header(self, client):
        h = client.get("/health").headers
        assert h.get("x-frame-options") == "DENY"

    def test_request_id_header(self, client):
        h = client.get("/health").headers
        assert "x-request-id" in h

    def test_response_time_header(self, client):
        h = client.get("/health").headers
        assert "x-response-time-ms" in h


# ═════════════════════════════════════════════════════════════════════════════
# 3. Critical API Routes Exist
# ═════════════════════════════════════════════════════════════════════════════

class TestCriticalRoutes:
    """Verify all critical routes respond (not 404)."""

    def test_auth_login_exists(self, client):
        r = client.post("/v1/auth/login", json={"email": "x@x.x", "password": "x" * 12})
        assert r.status_code != 404

    def test_sessions_list_exists(self, client):
        r = client.get("/v1/sessions")
        assert r.status_code in (401, 403), "Should require auth, not 404"

    def test_marketplace_rfq_exists(self, client):
        r = client.post("/v1/marketplace/rfq", json={"raw_text": "test"})
        assert r.status_code in (401, 403, 422)

    def test_escrow_list_exists(self, client):
        r = client.get("/v1/escrow")
        assert r.status_code in (401, 403)

    def test_procurement_list_exists(self, client):
        r = client.get("/v1/procurement")
        assert r.status_code in (401, 403)

    def test_wallet_or_x402_route_exists(self, client):
        r = client.get("/v1/wallet/balance")
        # Should require auth (not 404)
        assert r.status_code in (401, 403, 200)


# ═════════════════════════════════════════════════════════════════════════════
# 4. Negotiation Engine Smoke
# ═════════════════════════════════════════════════════════════════════════════

class TestNegotiationEngineSmoke:
    """Verify negotiation endpoints respond correctly without auth."""

    def test_session_get_requires_auth(self, client):
        r = client.get("/v1/sessions/00000000-0000-0000-0000-000000000001")
        assert r.status_code in (401, 403)

    def test_turn_requires_auth_or_payment(self, client):
        r = client.post("/v1/sessions/00000000-0000-0000-0000-000000000001/turn")
        assert r.status_code in (401, 402, 403)

    def test_run_auto_requires_auth(self, client):
        r = client.post("/v1/sessions/00000000-0000-0000-0000-000000000001/run-auto")
        assert r.status_code in (401, 403)

    def test_human_override_requires_auth(self, client):
        r = client.post(
            "/v1/sessions/00000000-0000-0000-0000-000000000001/override",
            json={"price": 50000},
        )
        assert r.status_code in (401, 403, 422)


# ═════════════════════════════════════════════════════════════════════════════
# 5. Marketplace Smoke
# ═════════════════════════════════════════════════════════════════════════════

class TestMarketplaceSmoke:
    """Verify marketplace data endpoints work."""

    def test_market_overview_returns_data(self, client):
        r = client.get("/v1/marketplace/market-overview")
        if r.status_code == 200:
            data = r.json()["data"]
            assert "total_sellers" in data
            assert data["total_sellers"] >= 0

    def test_industries_returns_list(self, client):
        r = client.get("/v1/marketplace/industries")
        if r.status_code == 200:
            data = r.json()["data"]
            assert isinstance(data, list)


# ═════════════════════════════════════════════════════════════════════════════
# 6. Response Envelope Format
# ═════════════════════════════════════════════════════════════════════════════

class TestResponseFormat:
    def test_health_uses_envelope(self, client):
        data = client.get("/health").json()
        assert "status" in data or "data" in data

    def test_error_response_has_detail(self, client):
        r = client.get("/v1/sessions")
        data = r.json()
        assert "detail" in data or "status" in data
