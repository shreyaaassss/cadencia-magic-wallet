# Cadencia Platform — Testing Guide

## Prerequisites

```bash
# Backend
cd backend/
pip install -e ".[dev]"   # or: pip install pytest pytest-asyncio aiosqlite

# Frontend
cd frontend/
npm ci --legacy-peer-deps
npm install --no-save ts-node
```

---

## 1. Unit Tests

> First line of defense. Tests individual functions/components in complete isolation. Fast feedback loop.

### Backend — Negotiation Engine (`28 tests`)

```bash
cd backend/

APP_ENV=test \
DATABASE_URL=sqlite+aiosqlite:///test.db \
REDIS_URL=redis://localhost:6379/0 \
LLM_PROVIDER=stub \
python -m pytest tests/unit/negotiation/test_negotiation_engine.py -v
```

**What it tests:**
| Test Class | Tests | Covers |
|---|---|---|
| `TestSessionLifecycleCompleteness` | 6 | Full DANP FSM: INIT → AGREED, walk-away, timeout, policy breach, stall → human review → resume, CLOSED_BY_BUYER terminal state |
| `TestTurnExecutionGuards` | 6 | Cannot add offers to terminal sessions, max rounds enforced, mismatched session ID rejected, round counter increments |
| `TestConvergenceDetection` | 4 | 2% tolerance convergence, 10% gap no convergence, exact match, requires both buyer + seller offers |
| `TestStallDetection` | 4 | Stall counter increments, triggers at threshold 3, concession resets counter, schema failure → policy breach |
| `TestStrategyEngineIntegration` | 4 | Opening anchor is STRONG_ANCHOR, cooperative → TIT_FOR_TAT, last round → ULTIMATUM, price never exceeds reservation |
| `TestValuationConsistency` | 4 | Buyer reservation > seller reservation creates viable zone, target/reservation differ, high risk → lower reservation |
| `TestMultiRoundSimulation` | 3 | 10-round alternating offers, natural convergence → agreement, no agreement when far apart |
| `TestEventPublisherIsolation` | 2 | Publisher swallows handler errors, calls all handlers even after failure |

### Backend — X402 Payment Middleware (`11 tests`)

```bash
cd backend/

APP_ENV=test \
python -m pytest tests/unit/shared/test_x402_middleware.py -v
```

**What it tests:** Nonce generation uniqueness, payment requirements building, missing headers → 402, used nonce replay rejection, expired nonce rejection, configuration helpers.

### Backend — Escrow State Machine (`14 tests`)

```bash
cd backend/

APP_ENV=test \
python -m pytest tests/unit/settlement/test_escrow.py -v
```

**What it tests:** PENDING_APPROVAL → APPROVED → DEPLOYED → FUNDED → RELEASED full lifecycle, double-deploy rejection, freeze/unfreeze, fund-when-frozen policy violation, refund path.

### Frontend — Utility Functions (`16 tests`)

```bash
cd frontend/

npx jest src/__tests__/utils.test.ts --verbose
```

**What it tests:** `formatCurrency` (INR grouping), `formatDate` / `formatDateTime` (IST timezone), `truncateAddress` (Algorand addresses), `cn` (Tailwind class merge, deduplication).

---

## 2. Integration Tests

> Tests how modules/services interact with real dependencies (API layer).

```bash
cd backend/

APP_ENV=testing \
DATABASE_URL=sqlite+aiosqlite:///test_integration.db \
X402_SIMULATION_MODE=true \
python -m pytest tests/integration/test_api_flows.py -v
```

**What it tests:**
| Test Class | Covers |
|---|---|
| `TestHealthEndpoint` | /health returns 200 with structured data (db, redis, algorand checks) |
| `TestAuthEndpoints` | Bad credentials → 401, protected routes without token → 401/403 |
| `TestMarketplaceEndpoints` | RFQ submit requires auth, catalogue upload requires auth |
| `TestNegotiationEndpoints` | Session not found → 404/401, turn endpoint requires auth |
| `TestEscrowEndpoints` | Escrow list requires auth, select-deal requires auth |

> **Note:** Integration tests require the FastAPI app to be importable. They use `ASGITransport` with the test client — no running server needed, but DB/Redis connections may cause skips if unavailable.

---

## 3. End-to-End (E2E) Tests

> Proves the negotiation engine works as a complete system. Simulates a full buyer-vs-seller AI negotiation.

```bash
cd backend/

APP_ENV=test \
DATABASE_URL=sqlite+aiosqlite:///test.db \
LLM_PROVIDER=stub \
python -m pytest tests/e2e/test_negotiation_e2e.py -v
```

**What it tests:**
| Test | Covers |
|---|---|
| `test_viable_deal_reaches_agreement` | When buyer budget > seller cost, agents converge to AGREED |
| `test_agreed_price_is_between_valuations` | Final price is within the bargaining zone |
| `test_negotiation_completes_within_max_rounds` | Terminates within 15 rounds |
| `test_multiple_rounds_executed` | At least 2 rounds (no instant agreement) |
| `test_narrow_margin_still_converges` | 10K gap with 10% margin still finds deal |
| `test_no_deal_when_impossible` | Seller min > buyer max → no agreement |
| `test_all_offers_have_valid_prices` | Every offer has price > 0 |
| `test_alternating_proposer_roles` | Buyer/seller strictly alternate |
| `test_buyer_prices_trend_upward` | Buyer concedes upward over rounds |
| `test_seller_prices_trend_downward` | Seller concedes downward over rounds |

**How it works:** Creates a `NegotiationSession`, computes buyer/seller valuations, runs `StrategyEngine` + `BayesianOpponentModel` for each turn, checks convergence, and verifies the agreed price is sensible. Uses all 4 negotiation engine layers (valuation, strategy, opponent model, guardrails).

---

## 4. Smoke Tests

> Run immediately post-deployment to verify the live server is alive and serving traffic.

```bash
# Against local server
cd backend/
SMOKE_TEST_BASE_URL=http://localhost:8000 \
python -m pytest tests/smoke/test_post_deploy_smoke.py -v

# Against production
SMOKE_TEST_BASE_URL=https://cadencia-magic-wallet.duckdns.org \
python -m pytest tests/smoke/test_post_deploy_smoke.py -v
```

**What it tests:**
| Test Class | Covers |
|---|---|
| `TestLiveness` | Health returns 200, overall status healthy/degraded, DB connected, Redis connected, response < 2s |
| `TestSecurityHeaders` | x-content-type-options: nosniff, x-frame-options: DENY, x-request-id, x-response-time-ms |
| `TestCriticalRoutes` | Auth login exists (not 404), sessions/escrow/procurement/x402 routes all respond |
| `TestNegotiationEngineSmoke` | Session GET, turn POST, run-auto POST, human override POST all require auth (not 404/500) |
| `TestMarketplaceSmoke` | Market overview returns seller count, industries returns list |
| `TestResponseFormat` | Health uses API envelope, error responses have detail field |

> **Note:** Smoke tests auto-skip if the server is unreachable. They only verify routes exist and respond — no data mutation.

---

## Run All Tests at Once

```bash
# Backend — all suites
cd backend/
APP_ENV=test DATABASE_URL=sqlite+aiosqlite:///test.db LLM_PROVIDER=stub \
python -m pytest \
  tests/unit/negotiation/test_negotiation_engine.py \
  tests/unit/shared/test_x402_middleware.py \
  tests/unit/settlement/test_escrow.py \
  tests/e2e/test_negotiation_e2e.py \
  -v --tb=short

# Frontend — all suites
cd frontend/
npx jest --verbose

# Smoke (requires running server)
cd backend/
SMOKE_TEST_BASE_URL=http://localhost:8000 \
python -m pytest tests/smoke/ -v
```

---

## Test File Locations

```
backend/
  tests/
    unit/
      negotiation/
        test_negotiation_engine.py   # 28 tests — FSM, convergence, stall, strategy
      shared/
        test_x402_middleware.py       # 11 tests — payment protocol
      settlement/
        test_escrow.py               # 14 tests — escrow state machine
    integration/
      test_api_flows.py              # 8 tests  — API auth enforcement
    e2e/
      test_negotiation_e2e.py        # 10 tests — full agent-vs-agent simulation
    smoke/
      test_post_deploy_smoke.py      # 18 tests — live server verification

frontend/
  src/__tests__/
    utils.test.ts                    # 16 tests — utility functions
```

**Total: 105 tests across 7 files, 4 test layers.**
