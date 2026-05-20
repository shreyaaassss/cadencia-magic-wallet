# Magic Wallet Integration — Cadencia A2A Platform

## Overview

This document specifies the complete replacement of the current email/password + Pera wallet
architecture with **Magic.link embedded wallets**. The result is a single-credential system
where a user's email address is their login, their identity, and their Algorand wallet — with
no seed phrases, no WalletConnect sessions, and no manual reconnects.

The x402 payment protocol remains entirely unchanged on the backend. Only the auth layer
and the signing mechanism change on the frontend.

---

## What Changes vs What Stays

### Removed entirely
- Email + password registration and login forms
- JWT session management (`AuthContext` login/register/refresh flow)
- `WalletProviderWrapper`, `AlgorandWalletProvider`, `WalletContext`
- `@txnlab/use-wallet-react`, `@perawallet/connect`, `@blockshake/defly-connect`, `lute-connect`
- Wallet challenge-response linking flow (`/v1/wallet/challenge`, `/v1/wallet/link`)
- WalletConnect session persistence logic (`wallet-config.ts`, `destroyWalletManager`)

### Replaced with Magic
- Login/register → `magic.auth.loginWithEmailOTP({ email })`
- Session check → `magic.user.isLoggedIn()` + `magic.user.getMetadata()`
- Algorand address → `metadata.publicAddress` (Magic-managed, non-custodial)
- Transaction signing → `magic.algorand.signTransaction(encodedTxn)`
- x402 payment client → uses Magic signing instead of `useWallet().signTransactions`

### Unchanged
- All FastAPI backend routes and middleware
- x402 payment middleware (`require_x402_payment`)
- Escrow smart contract deployment and release
- Negotiation engine, marketplace, compliance, treasury
- Supabase schema (except: `enterprise.algorand_wallet` is now populated automatically
  from Magic's public address on first login, no challenge flow needed)
- All environment variables except those listed in Phase 4

---

## Architecture After Migration

```
User opens Cadencia
        ↓
  Enters email → Magic sends OTP
        ↓
  Enters OTP → Magic authenticates
        ↓
  magic.user.getMetadata()
  → { publicAddress: "ALGO_ADDRESS...", email: "user@example.com" }
        ↓
  Frontend calls POST /v1/auth/magic-login
  with { email, magic_did_token }
        ↓
  Backend verifies DID token with Magic Admin SDK
  Issues JWT (same RS256 system as before)
  Auto-links ALGO address to enterprise if not already linked
        ↓
  User is authenticated + wallet is ready
  No QR scan. No Pera app. No reconnect ever.
```

---

## Phase 1 — Backend Auth Changes

### 1.1 Add Magic Admin SDK

```bash
pip install magic-admin
```

Add to `pyproject.toml` dependencies:
```
magic-admin>=0.2.0
```

### 1.2 New endpoint: POST /v1/auth/magic-login

Create `backend/src/identity/api/magic_auth.py`:

```python
"""
Magic.link authentication endpoint.
Verifies the DID token issued by Magic SDK on the frontend,
creates or retrieves the user, and returns a Cadencia JWT.
"""

from __future__ import annotations

import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.shared.api.responses import ApiResponse, success_response
from src.shared.infrastructure.logging import get_logger
from src.identity.application.services import IdentityService

log = get_logger(__name__)
router = APIRouter(prefix="/v1/auth", tags=["auth"])


class MagicLoginRequest(BaseModel):
    did_token: str          # DID token from magic.user.getIdToken()
    email: str              # User's email (for enterprise lookup/creation)
    algo_address: str       # magic metadata.publicAddress


class MagicLoginResponse(BaseModel):
    access_token: str
    user_id: str
    enterprise_id: str | None


@router.post("/magic-login", response_model=ApiResponse[MagicLoginResponse])
async def magic_login(body: MagicLoginRequest):
    """
    1. Verify Magic DID token with Magic Admin SDK
    2. Find or create user by email
    3. Auto-link their Magic Algorand address to their enterprise
    4. Return Cadencia JWT (same RS256 system as existing /v1/auth/login)
    """
    from magic import Magic  # magic-admin SDK

    magic_secret = os.environ.get("MAGIC_SECRET_KEY")
    if not magic_secret:
        raise HTTPException(500, "MAGIC_SECRET_KEY not configured")

    # Verify DID token — raises if invalid/expired
    try:
        magic_client = Magic(secret_key=magic_secret)
        magic_client.Token.validate(body.did_token)
        issuer = magic_client.Token.get_issuer(body.did_token)
    except Exception as exc:
        log.warning("magic_did_token_invalid", error=str(exc))
        raise HTTPException(401, "Invalid or expired Magic token")

    # Find or create user + enterprise, auto-link wallet address
    # (reuse existing IdentityService — just skip the password hash step)
    # ... wire to your existing user creation / JWT issuance logic

    log.info("magic_login_success", email=body.email, algo_address=body.algo_address[:8])
    # Return JWT using the same token factory as /v1/auth/login
    ...
```

Register this router in `main.py` alongside the existing `identity_router`.

### 1.3 Auto-link wallet on first Magic login

Inside the `magic_login` handler, after creating/finding the user:

```python
# If enterprise has no linked wallet yet, link it automatically.
# Magic's publicAddress is cryptographically tied to the user's email —
# no challenge-response needed.
if enterprise and not enterprise.algorand_wallet:
    enterprise.algorand_wallet = body.algo_address
    await session.commit()
    log.info("magic_wallet_auto_linked", address=body.algo_address[:8])
```

This eliminates the entire `/v1/wallet/challenge` + `/v1/wallet/link` flow for Magic users.

### 1.4 Keep existing /v1/auth/login (optional)

If you want to support both auth methods during a transition period, keep
the existing email/password login untouched. Magic login is purely additive.
For a clean Magic-only repo, remove the password-based endpoints.

---

## Phase 2 — Frontend Package Changes

### 2.1 Remove Pera/WalletConnect packages

```bash
npm uninstall @txnlab/use-wallet-react @perawallet/connect \
  @blockshake/defly-connect lute-connect @walletconnect/modal \
  @walletconnect/sign-client @agoralabs-sh/avm-web-provider
```

### 2.2 Install Magic packages

```bash
npm install magic-sdk @magic-ext/algorand
```

**Critical version constraint** (validated in this codebase):
```
magic-sdk@28.6.0          ← do NOT go above 28.6.x
@magic-ext/algorand@24.4.2  ← zero dependencies, no peer conflicts
```

`@magic-ext/algorand@28.x` imports `MultichainExtension` from `@magic-sdk/provider`
which was removed in `magic-sdk@28.7+`. Use `24.4.2` — it has zero dependencies,
exports `AlgorandExtension`, and is compatible with any `magic-sdk@28.x`.

### 2.3 Dockerfile — add build args

```dockerfile
ARG NEXT_PUBLIC_MAGIC_PUBLISHABLE_KEY
ARG NEXT_PUBLIC_ALGORAND_NODE_URL=https://testnet-api.algonode.cloud
ARG NEXT_PUBLIC_X402_ENABLED=true

ENV NEXT_PUBLIC_MAGIC_PUBLISHABLE_KEY=${NEXT_PUBLIC_MAGIC_PUBLISHABLE_KEY}
ENV NEXT_PUBLIC_ALGORAND_NODE_URL=${NEXT_PUBLIC_ALGORAND_NODE_URL}
ENV NEXT_PUBLIC_X402_ENABLED=${NEXT_PUBLIC_X402_ENABLED}
```

Also change `npm ci --ignore-scripts` to `npm ci --ignore-scripts --legacy-peer-deps`
in the Dockerfile `deps` stage.

### 2.4 GitHub Actions — add build-arg

```yaml
build-args: |
  NEXT_PUBLIC_MAGIC_PUBLISHABLE_KEY=${{ secrets.NEXT_PUBLIC_MAGIC_PUBLISHABLE_KEY }}
  NEXT_PUBLIC_ALGORAND_NODE_URL=https://testnet-api.algonode.cloud
  NEXT_PUBLIC_X402_ENABLED=true
```

Add `NEXT_PUBLIC_MAGIC_PUBLISHABLE_KEY` as a GitHub repository secret.

---

## Phase 3 — Frontend File Changes

### 3.1 Create `src/lib/magic.ts`

```typescript
'use client';

import { Magic } from 'magic-sdk';
import { AlgorandExtension } from '@magic-ext/algorand';

function createMagicInstance() {
  if (typeof window === 'undefined') return null;

  const key = process.env.NEXT_PUBLIC_MAGIC_PUBLISHABLE_KEY;
  const rpcUrl = process.env.NEXT_PUBLIC_ALGORAND_NODE_URL
    ?? 'https://testnet-api.algonode.cloud';

  if (!key) {
    console.warn('[magic] NEXT_PUBLIC_MAGIC_PUBLISHABLE_KEY not set');
    return null;
  }

  return new Magic(key, {
    extensions: [new AlgorandExtension({ rpcUrl }) as any],
  });
}

export const magic = createMagicInstance();

/** Returns the Magic-managed Algorand address for the current session. */
export async function getMagicAddress(): Promise<string> {
  if (!magic) throw new Error('Magic SDK not available');
  const metadata = await magic.user.getMetadata();
  const address = (metadata as any).publicAddress as string;
  if (!address) throw new Error('No Algorand address in Magic session');
  return address;
}

/**
 * Signs a base64-encoded unsigned Algorand transaction.
 * Returns base64-encoded signed transaction bytes.
 */
export async function signAlgoTxn(encodedTxnB64: string): Promise<string> {
  if (!magic) throw new Error('Magic SDK not available');
  const txnBytes = Buffer.from(encodedTxnB64, 'base64');
  const signedBytes: Uint8Array = await (magic as any).algorand.signTransaction(txnBytes);
  return Buffer.from(signedBytes).toString('base64');
}
```

### 3.2 Replace `AuthContext.tsx`

Remove the existing `AuthContext` entirely. Replace with a Magic-based context:

```typescript
'use client';

import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { magic, getMagicAddress } from '@/lib/magic';
import { api, setAccessToken } from '@/lib/api';

interface AuthContextValue {
  user: Record<string, unknown> | null;
  walletAddress: string | null;
  isLoading: boolean;
  login: (email: string) => Promise<void>;   // ← email only, no password
  logout: () => Promise<void>;
  isAdmin: boolean;
  isBuyer: boolean;
  isSeller: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<Record<string, unknown> | null>(null);
  const [walletAddress, setWalletAddress] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Restore session on mount
  useEffect(() => {
    const restore = async () => {
      if (!magic) { setIsLoading(false); return; }
      try {
        const isLoggedIn = await magic.user.isLoggedIn();
        if (isLoggedIn) {
          await _hydrate();
        }
      } catch {
        // No active session
      } finally {
        setIsLoading(false);
      }
    };
    restore();
  }, []);

  const _hydrate = async () => {
    const metadata = await magic!.user.getMetadata();
    const address = await getMagicAddress();
    const didToken = await magic!.user.getIdToken();

    // Exchange Magic DID token for Cadencia JWT
    const { data } = await api.post('/v1/auth/magic-login', {
      did_token: didToken,
      email: metadata.email,
      algo_address: address,
    });
    setAccessToken(data.data.access_token);

    // Fetch Cadencia user profile
    const { data: meRes } = await api.get('/v1/auth/me');
    setUser(meRes.data);
    setWalletAddress(address);
  };

  const login = useCallback(async (email: string) => {
    if (!magic) throw new Error('Magic SDK not available');
    setIsLoading(true);
    try {
      await magic.auth.loginWithEmailOTP({ email });
      await _hydrate();
      router.push('/dashboard');
    } finally {
      setIsLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    if (magic) await magic.user.logout();
    setAccessToken(null);
    setUser(null);
    setWalletAddress(null);
    try { await api.post('/v1/auth/logout'); } catch {}
    router.push('/login');
  }, []);

  return (
    <AuthContext.Provider value={{
      user, walletAddress, isLoading,
      login, logout,
      isAdmin: (user as any)?.role === 'ADMIN',
      isBuyer: (user as any)?.enterprise?.trade_role === 'BUYER',
      isSeller: (user as any)?.enterprise?.trade_role === 'SELLER',
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
```

### 3.3 Replace `login/page.tsx`

Remove the password field entirely. Single email input that calls `login(email)`:

```tsx
export default function LoginPage() {
  const { login, isLoading } = useAuth();
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await login(email);
      // AuthContext redirects to /dashboard on success
    } catch (err: any) {
      setError(err.message ?? 'Login failed');
    }
  };

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="bg-card border border-border rounded-lg p-8 w-full max-w-sm">
        <h1 className="text-xl font-semibold mb-6">Sign in to Cadencia</h1>
        {error && <p className="text-destructive text-sm mb-4">{error}</p>}
        <form onSubmit={handleSubmit} className="space-y-4">
          <Input
            type="email"
            placeholder="your@email.com"
            value={email}
            onChange={e => setEmail(e.target.value)}
            required
          />
          <Button type="submit" className="w-full" disabled={isLoading}>
            {isLoading ? 'Sending magic link…' : 'Continue with Email'}
          </Button>
        </form>
        {/* Magic handles OTP in its own modal — no extra UI needed */}
      </div>
    </div>
  );
}
```

### 3.4 Simplify `register/page.tsx`

Remove the email/password step entirely. Keep all other steps (enterprise details, role, etc.).
On final submit, call `login(email)` instead of `api.post('/v1/auth/register', {...})`.

The Magic login + backend `magic-login` endpoint handles user creation automatically.

### 3.5 Remove wallet provider files

Delete:
- `src/lib/wallet-config.ts`
- `src/context/WalletContext.tsx`
- `src/components/providers/AlgorandWalletProvider.tsx`
- `src/components/providers/WalletProviderWrapper.tsx`

### 3.6 Update `layout.tsx`

Remove `WalletProviderWrapper` and `CadenciaWalletProvider` from the provider tree.
Only keep `AuthProvider` (which now also manages the wallet address):

```tsx
<AuthProvider>
  {children}
  <Toaster />
</AuthProvider>
```

### 3.7 Rewrite x402 payment client

Replace `useFetchWithAlgorandPayment` (which used `useWallet().signTransactions`)
with a standalone function that uses Magic directly:

```typescript
// src/lib/x402-algorand-client.ts

import algosdk from 'algosdk';
import { magic, getMagicAddress, signAlgoTxn } from '@/lib/magic';

export async function fetchWithAlgorandPayment(
  url: string,
  options?: RequestInit,
): Promise<Response> {
  const initial = await fetch(url, options);
  if (initial.status !== 402) return initial;

  const body = await initial.json();
  const req = (body.detail ?? body) as {
    scheme: string; amount: number; recipient: string;
    nonce: string; expires_at: number;
  };

  if (req.scheme !== 'algorand-payment') {
    throw new Error(`Unsupported payment scheme: ${req.scheme}`);
  }
  if (Date.now() / 1000 > req.expires_at) {
    throw new Error('Payment requirements expired');
  }
  if (!magic) throw new Error('Magic SDK not available');

  const senderAddress = await getMagicAddress();

  const nodeUrl = process.env.NEXT_PUBLIC_ALGORAND_NODE_URL
    ?? 'https://testnet-api.algonode.cloud';
  const algodClient = new algosdk.Algodv2('', nodeUrl, '');
  const suggestedParams = await algodClient.getTransactionParams().do();

  const txn = algosdk.makePaymentTxnWithSuggestedParamsFromObject({
    sender: senderAddress,
    receiver: req.recipient,
    amount: req.amount,
    note: new TextEncoder().encode(JSON.stringify({
      nonce: req.nonce,
      expires_at: req.expires_at,
    })),
    suggestedParams,
  });

  const encodedB64 = Buffer.from(algosdk.encodeUnsignedTransaction(txn)).toString('base64');
  const signedB64 = await signAlgoTxn(encodedB64);

  const headers = new Headers(options?.headers);
  headers.set('X-PAYMENT', signedB64);
  headers.set('X-PAYMENT-NONCE', req.nonce);

  const retry = await fetch(url, { ...options, headers });
  if (retry.status === 402) throw new Error('Payment rejected — check ALGO balance');
  return retry;
}
```

Note: this is now a plain `async function`, not a React hook. It can be called anywhere
in the codebase — no `useWallet()` provider needed.

### 3.8 Update escrow signing

The escrow funding/release currently calls `signAndSubmitFundTxn` from `WalletContext`,
which uses `@txnlab/use-wallet-react`. Replace with Magic signing:

```typescript
// New helper used by the escrow page instead of signAndSubmitFundTxn
async function signAndSubmitViaMagic(
  encodedTxnB64: string,
  algodClient: algosdk.Algodv2,
): Promise<{ txid: string; confirmed_round: number }> {
  const signedB64 = await signAlgoTxn(encodedTxnB64);
  const signedBytes = Buffer.from(signedB64, 'base64');
  const txid = await algodClient.sendRawTransaction(signedBytes).do();
  const result = await algosdk.waitForConfirmation(algodClient, txid, 10);
  return { txid, confirmed_round: result['confirmed-round'] };
}
```

The escrow page fetches the transaction to sign from the backend
(`/v1/escrow/{id}/fund-txn` or similar), then uses this helper.
The backend escrow endpoints remain unchanged — they only care that the
transaction was signed and broadcast.

---

## Phase 4 — Environment Variables

### Backend `.env` additions

```bash
# Magic Admin SDK secret key
MAGIC_SECRET_KEY=sk_live_YOUR_SECRET_KEY
```

All other backend variables remain the same (Algorand node, JWT keys, etc.).

### Frontend `.env` additions

```bash
NEXT_PUBLIC_MAGIC_PUBLISHABLE_KEY=pk_live_YOUR_PUBLISHABLE_KEY
NEXT_PUBLIC_ALGORAND_NODE_URL=https://testnet-api.algonode.cloud
NEXT_PUBLIC_X402_ENABLED=true
```

### Magic dashboard settings

1. Go to `dashboard.magic.link`
2. Create a new app (or reuse existing)
3. Under **Blockchain** → enable **Algorand**
4. Set network to **TestNet** for development, **MainNet** for production
5. Copy the publishable key (`pk_live_...`) to frontend env
6. Copy the secret key (`sk_live_...`) to backend env

---

## Phase 5 — What You Do NOT Need to Change

The following are completely unaffected by the Magic wallet migration:

| Component | Status |
|---|---|
| x402 middleware (`x402_payment.py`) | No change — validates any valid Algorand txn |
| `broadcast_and_confirm` | No change |
| x402 routes (`/v1/x402/*`) | No change |
| Escrow smart contract | No change |
| Negotiation engine | No change |
| Marketplace routes | No change |
| Supabase schema | No change (except `algorand_wallet` auto-populated) |
| Redis nonce storage | No change |
| JWT RS256 system | No change — Magic token exchanges for a Cadencia JWT |
| CORS, rate limiting, compliance | No change |
| CI/CD pipeline | Minor change — add Magic build arg (Phase 2.4) |

---

## User Experience After Migration

### Before (current)
```
Register → email + password + enterprise details
Login → email + password
Link wallet → go to Settings → open Pera on phone → scan QR → sign challenge
Fund escrow → go to Settings → reconnect Pera → come back → sign txn
x402 payment → connect Pera → approve signing → wait ~4s
```

### After (Magic)
```
Register → email + enterprise details (no password)
Login → email → check inbox → click OTP link (or enter 6 digits)
Wallet → created automatically, linked automatically, no setup required
Fund escrow → click Fund → Magic shows confirmation → approve → done
x402 payment → happens silently (Magic auto-signs small amounts) → done
```

---

## Session Management

Magic sessions last **7 days** by default and renew silently when the user is active.
There is no WalletConnect relay — the session lives entirely in the browser
(HttpOnly cookie + localStorage). Users never see "wallet disconnected" again.

To check/refresh on page load:
```typescript
const isLoggedIn = await magic.user.isLoggedIn();
if (isLoggedIn) {
  // session is still valid — hydrate user state
}
```

Magic handles token refresh automatically. If the session truly expires (7 days
of inactivity), the user sees the email OTP screen again — one field, 30 seconds.

---

## Key Implementation Notes

1. **Magic signs, not the user.** For amounts below Magic's auto-sign threshold,
   x402 payments complete with zero user interaction. For larger amounts, Magic shows
   a small confirmation popup. This is configurable in the Magic dashboard.

2. **Non-custodial.** Magic uses Delegated Key Management (DKM) — the private key
   is split between the user's device and Magic's HSM. Neither party alone can sign.
   Magic cannot move funds without user authentication.

3. **Same Algorand address across sessions.** Unlike Pera (where the session expires),
   `magic.user.getMetadata().publicAddress` always returns the same address as long as
   the user authenticates with the same email. No address rotation, no migration needed.

4. **The `did_token` expires in 15 minutes.** Only use it once, immediately, to exchange
   for a Cadencia JWT. Do not store it.

5. **TestNet vs MainNet.** Magic's `AlgorandExtension` uses the `rpcUrl` you pass at
   init time. Switching to MainNet is a single env var change:
   `NEXT_PUBLIC_ALGORAND_NODE_URL=https://mainnet-api.algonode.cloud`

---

## Summary Checklist

### Backend
- [ ] Install `magic-admin` Python package
- [ ] Create `POST /v1/auth/magic-login` endpoint with DID token verification
- [ ] Auto-link Magic `publicAddress` to enterprise on first login
- [ ] Add `MAGIC_SECRET_KEY` to backend env and GitHub `BACKEND_ENV` secret
- [ ] (Optional) Remove `/v1/auth/register` and `/v1/auth/login` password endpoints

### Frontend
- [ ] Uninstall Pera/WalletConnect packages
- [ ] Install `magic-sdk@28.6.0` and `@magic-ext/algorand@24.4.2`
- [ ] Create `src/lib/magic.ts` (singleton + `getMagicAddress` + `signAlgoTxn`)
- [ ] Replace `AuthContext.tsx` with Magic-based auth
- [ ] Rewrite `login/page.tsx` — email only, no password
- [ ] Simplify `register/page.tsx` — remove password step
- [ ] Delete `WalletContext.tsx`, `wallet-config.ts`, `AlgorandWalletProvider.tsx`, `WalletProviderWrapper.tsx`
- [ ] Remove `WalletProviderWrapper` and `CadenciaWalletProvider` from `layout.tsx`
- [ ] Rewrite `x402-algorand-client.ts` — plain async function using `signAlgoTxn`
- [ ] Update escrow page signing to use Magic instead of `signAndSubmitFundTxn`
- [ ] Add `NEXT_PUBLIC_MAGIC_PUBLISHABLE_KEY` to frontend env and GitHub secrets
- [ ] Update `Dockerfile` — add Magic build args, add `--legacy-peer-deps`
- [ ] Update GitHub Actions workflow — add Magic build-arg

### Magic Dashboard
- [ ] Create app at `dashboard.magic.link`
- [ ] Enable Algorand blockchain, set network to TestNet
- [ ] Copy publishable key and secret key to respective envs
