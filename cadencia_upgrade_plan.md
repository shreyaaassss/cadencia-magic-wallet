# Magic Wallet + x402 Protocol Integration for Cadencia

## Overview

This plan integrates **Magic.link Embedded Wallets** (for Algorand) with the **x402 HTTP payment protocol** into the existing Cadencia A2A platform. The goal is to enable buyers to authenticate with a Magic wallet and pay for gated Cadencia API endpoints (e.g., marketplace data, loan origination, settlement services) using ALGO or an Algorand Standard Asset (ASA) — with near-zero transaction fees and no private key management.

---

## ⚠️ Critical Architecture Decision: Algorand vs EVM for x402

> [!IMPORTANT]
> **The x402 protocol as currently documented by Coinbase is EVM-native** — it uses Base/Ethereum chains, EIP-3009 (`transferWithAuthorization`), and viem-based tooling. The Algorand x402 implementation from `dev.algorand.co` uses a **custom Hono resource server + TypeScript client** pattern, not the `@x402/evm` SDK. These two approaches must be reconciled.
>
> **Recommended hybrid path**: Use **Magic + `@magic-ext/algorand`** for user wallet management and ALGO transaction signing. Implement a **custom x402-compatible middleware** on the Python backend (or a lightweight TypeScript side-car) that validates Algorand payment transactions in request headers — mirroring the x402 flow but adapted for Algorand's transaction model.

---

## How x402 Works (Protocol Summary)

```
Buyer Browser                Cadencia Backend (Resource Server)     Algorand Facilitator
─────────────────────────────────────────────────────────────────────────────────────────
1. GET /api/marketplace/listings
      ──────────────────────────────────────────────────▶
                             2. HTTP 402 + Payment Requirements
                             { scheme: "algorand-payment",
                               amount: "0.1 ALGO",
                               recipient: <platform_wallet>,
                               nonce: "abc123",
                               expires: timestamp }
      ◀──────────────────────────────────────────────────
3. Magic SDK signs Algorand payment txn using user's embedded wallet
   (note: pre-authorized, no gas needed by user for network fee
    since Algorand fees are ~0.001 ALGO, paid from user account)
4. Retry GET /api/marketplace/listings
   Header: X-Payment: { signedTxn: <base64>, txId: <pending_txId> }
      ──────────────────────────────────────────────────▶
                             5. Backend submits txn to Algorand network
                                Validates txId confirmed & amount correct
                             6. HTTP 200 + resource data
      ◀──────────────────────────────────────────────────
```

---

## Buyer User Flow (Step-by-Step)

### Step 1 — Landing & Authentication
- Buyer visits Cadencia marketplace (`/marketplace`)
- Clicks "Connect Wallet" → Magic SDK popup appears
- Enters **email address only** (no seed phrases, no MetaMask)
- Magic sends a magic link / OTP → user verifies
- **Result**: User now has a non-custodial Algorand wallet created by Magic, associated with their email

### Step 2 — Wallet Funding
- Dashboard shows user's Magic-generated Algorand public address
- A "Fund Wallet" button opens a fiat on-ramp (MoonPay or Algorand Dispenser for testnet)
- User funds with ALGO (minimum ~1 ALGO for transactions + min balance requirement)

### Step 3 — Browsing the Marketplace
- Buyer browses loan listings at `/marketplace`
- **Free endpoint**: basic listing view (HTTP 200 directly)
- **Gated endpoint**: detailed loan analytics, borrower credit score → triggers x402 flow

### Step 4 — x402 Payment Trigger (Automatic)
- Frontend calls `fetchWithAlgorandPayment('/api/marketplace/loan/:id/details')`
- Backend responds with **HTTP 402** + payment spec:
  ```json
  {
    "scheme": "algorand-payment",
    "amount": 100000,        // 0.1 ALGO in microALGO
    "recipient": "PLATFORM_WALLET_ADDRESS",
    "nonce": "uuid-v4",
    "expires_at": 1718000000
  }
  ```
- **No user action needed at this point** — the payment client handles it automatically

### Step 5 — Magic Signs the Transaction
- The x402 client on the frontend:
  1. Calls `magic.algorand.getWallet()` to get the user's public address
  2. Constructs an Algorand payment transaction using `algosdk`
  3. Calls `magic.algorand.signTransaction(encodedTxn)` → Magic SDK shows a **tiny confirmation popup** (or none if amount is below auto-sign threshold)
  4. Gets back a signed transaction blob

### Step 6 — Retry with Payment Header
- Frontend sends the same request with header:
  ```
  X-PAYMENT: base64(signedTxnBlob)
  X-PAYMENT-NONCE: <nonce-from-402>
  ```

### Step 7 — Backend Validates & Broadcasts
- Backend middleware:
  1. Decodes the signed transaction from the header
  2. **Broadcasts** it to Algorand (via algod client)
  3. **Waits for confirmation** (~4 seconds on Algorand)
  4. Verifies: amount ≥ required, recipient = platform wallet, nonce matches (replay protection)
  5. If valid → serves the protected resource
  6. Records payment in Supabase `x402_payments` table

### Step 8 — Success State
- Buyer gets the requested data (loan analytics, credit report, etc.)
- A payment receipt toast appears: "Paid 0.1 ALGO • Tx: ABC...XYZ"
- Payment recorded in user's transaction history

---

## Proposed Changes

### Phase 1 — Magic Wallet Integration (Frontend)

#### [MODIFY] [package.json](file:///c:/Users/Harsh/Desktop/Cadencia-A2A-Platform-production/frontend/package.json)
Add new dependencies:
- `magic-sdk` — Magic authentication SDK
- `@magic-ext/algorand` — Algorand blockchain extension
- `algosdk` — Algorand JS SDK for transaction construction

#### [NEW] `frontend/src/lib/magic.ts`
Initialize Magic instance with Algorand extension. Export `magic` singleton and utility functions (`getMagicWallet`, `signAlgoTransaction`).

#### [NEW] `frontend/src/context/MagicContext.tsx`
React context provider wrapping the app. Stores:
- `user` — Magic auth state
- `walletAddress` — Algorand public address
- `isLoading` — login flow state

Replaces/augments existing auth context.

#### [NEW] `frontend/src/lib/x402-algorand-client.ts`
Custom x402 payment client for Algorand:
```typescript
export async function fetchWithAlgorandPayment(url, options) {
  // 1. Make initial request
  // 2. If 402, extract payment requirements
  // 3. Build + sign Algorand payment txn via Magic
  // 4. Retry with X-PAYMENT header
}
```

#### [MODIFY] `frontend/src/app/(auth)/` — Login Page
Replace existing auth flow with Magic SDK email login. Remove password fields. Add "Connect with Magic" button.

#### [NEW] `frontend/src/components/WalletWidget.tsx`
Shows:
- Magic wallet address (truncated, copyable)
- ALGO balance
- "Top Up" button → MoonPay or faucet link
- Recent x402 payment history

---

### Phase 2 — x402 Backend Middleware (Python)

#### [NEW] `backend/src/shared/middleware/x402_payment.py`
FastAPI middleware / dependency that:
1. Checks for `X-PAYMENT` header
2. If present: decodes base64 signed txn, broadcasts to Algorand, awaits confirmation
3. Validates payment (amount, recipient, nonce, expiry)
4. Rejects replayed nonces (stores used nonces in Redis with TTL = expiry)
5. Returns `402` with payment requirements JSON when payment is missing

```python
class X402PaymentMiddleware:
    PAYMENT_REQUIRED = {
        "scheme": "algorand-payment",
        "version": "1",
        "amount": 100000,  # microALGO
        "recipient": settings.PLATFORM_WALLET,
        "currency": "ALGO"
    }
```

#### [MODIFY] `backend/src/marketplace/api/` — Gated Routes
Apply `x402_required` dependency to premium endpoints:
- `GET /marketplace/loans/{id}/analytics` — detailed loan data
- `GET /marketplace/loans/{id}/credit-report` — borrower credit
- `POST /marketplace/match` — AI-powered loan matching

#### [NEW] `backend/src/wallet/api/x402_routes.py`
New routes:
- `GET /x402/payment-requirements` — returns current payment requirements for any gated resource
- `GET /x402/verify/{txId}` — verify a specific payment transaction

#### [MODIFY] `backend/src/shared/` — Algorand Client
Add `broadcast_and_confirm(signed_txn_b64)` utility using existing algod client configuration.

---

### Phase 3 — Supabase Schema Extension

```sql
-- New table for x402 payment tracking
CREATE TABLE x402_payments (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  buyer_address TEXT NOT NULL,
  tx_id TEXT NOT NULL UNIQUE,   -- Algorand txId
  amount BIGINT NOT NULL,        -- microALGO
  resource_url TEXT NOT NULL,
  nonce TEXT NOT NULL UNIQUE,    -- replay protection
  confirmed_round BIGINT,
  paid_at TIMESTAMPTZ DEFAULT NOW(),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_x402_payments_buyer ON x402_payments(buyer_address);
CREATE INDEX idx_x402_payments_nonce ON x402_payments(nonce);
```

---

### Phase 4 — Environment Variables

#### [MODIFY] `backend/.env.example`
```
# Magic.link
MAGIC_SECRET_KEY=sk_live_...

# x402 Configuration
X402_PAYMENT_AMOUNT_MICROALGO=100000   # 0.1 ALGO
X402_NONCE_TTL_SECONDS=300             # 5 min payment window
X402_ENABLED_ROUTES=/marketplace/loans/*/analytics,/marketplace/loans/*/credit-report
```

#### [MODIFY] `frontend/.env.example`
```
NEXT_PUBLIC_MAGIC_PUBLISHABLE_KEY=pk_live_...
NEXT_PUBLIC_ALGORAND_NODE_URL=https://testnet-api.algonode.cloud
NEXT_PUBLIC_X402_ENABLED=true
```

---

## Open Questions

> [!IMPORTANT]
> **1. Payment Asset**: Should payments be in native **ALGO** or an **Algorand Stable Token** (e.g., USDC-on-Algorand ASA ID 31566704)?
> - ALGO is simpler but price-volatile
> - USDC-A is stable but requires users to opt-in to the ASA first

> [!IMPORTANT]
> **2. Payment Amount**: What price per gated API call? Current suggestion: 0.1 ALGO (~$0.02). Should this be:
> - Flat rate per call?
> - Tiered by resource type?
> - Subscription-style with a daily/monthly access token?

> [!WARNING]
> **3. Confirmation UX**: Algorand confirms in ~4 seconds. During this wait, should the frontend show:
> - A loading spinner (simple)
> - An animated "processing payment" overlay
> - Optimistic data loading (load data while confirming, rollback on fail)?

> [!NOTE]
> **4. Existing Auth**: Cadencia currently uses session-based auth (from prior conversations). Magic login should **supplement** this, not fully replace it. Should we:
> - Allow both Magic and existing email/password?
> - Require Magic for all wallet-related features, existing auth for non-blockchain features?

> [!NOTE]
> **5. Testnet vs Mainnet**: For the initial build, using Algorand **TestNet** with the Algorand testnet faucet. Mainnet migration would require a production Magic API key with proper network config.

---

## Verification Plan

### Automated Tests
- Unit test: x402 middleware validates payment correctly (mock algod)
- Unit test: nonce replay rejection works
- Integration test: full 402 → sign → retry flow with TestNet

### Manual Verification
1. Login with Magic email on `/marketplace` — wallet address appears
2. Hit a gated endpoint without payment → see 402 JSON response
3. Enable x402 client → request auto-pays → data returns within ~5 seconds
4. Check Supabase `x402_payments` table for record
5. Try replaying the same nonce → backend rejects with 402

### Milestone Summary

| Phase | Effort | Deliverable |
|-------|--------|-------------|
| 1 — Magic Frontend | 2 days | Magic login + Algorand wallet display |
| 2 — x402 Backend | 2 days | Payment middleware on gated routes |
| 3 — Database | 0.5 days | x402_payments table + Supabase migration |
| 4 — Integration | 1 day | End-to-end flow on TestNet |
| 5 — UX Polish | 1 day | Payment receipt toasts, wallet widget |
| **Total** | **~6.5 days** | **Full MVP** |
