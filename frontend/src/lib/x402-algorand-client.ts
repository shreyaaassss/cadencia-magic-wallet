'use client';

/**
 * x402 Algorand payment hook.
 *
 * Returns `fetchWithAlgorandPayment` — a fetch wrapper that handles HTTP 402
 * automatically using the user's already-connected Pera/Defly/Lute wallet
 * (via @txnlab/use-wallet-react). No second wallet needed.
 *
 * Flow:
 *   1. Make the initial request
 *   2. If 402 → parse payment requirements from response body
 *   3. Build an Algorand payment txn using algosdk
 *   4. Sign via the active wallet (Pera/Defly/etc.)
 *   5. Retry with X-PAYMENT and X-PAYMENT-NONCE headers
 */

import { useCallback } from 'react';
import algosdk from 'algosdk';
import { useWallet } from '@txnlab/use-wallet-react';

// ── Types ─────────────────────────────────────────────────────────────────────

interface AlgorandPaymentRequirements {
  scheme: string;
  version: string;
  amount: number;       // microALGO
  recipient: string;    // Algorand address
  currency: string;
  nonce: string;
  expires_at: number;   // Unix timestamp
}

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * Returns a `fetchWithAlgorandPayment(url, options?)` function that
 * intercepts HTTP 402 responses and pays automatically using the currently
 * connected Algorand wallet.
 *
 * Must be called inside a component tree that has WalletProviderWrapper above it.
 */
export function useFetchWithAlgorandPayment() {
  const { signTransactions, activeAddress } = useWallet();

  return useCallback(
    async (url: string, options?: RequestInit): Promise<Response> => {
      // ── Step 1: Initial request ───────────────────────────────────────────
      const initial = await fetch(url, options);
      if (initial.status !== 402) return initial;

      // ── Step 2: Parse payment requirements ───────────────────────────────
      let requirements: AlgorandPaymentRequirements;
      try {
        const body = await initial.json();
        requirements = (body.detail ?? body) as AlgorandPaymentRequirements;
      } catch {
        throw new Error('[x402] Failed to parse payment requirements from 402 response');
      }

      if (requirements.scheme !== 'algorand-payment') {
        throw new Error(`[x402] Unsupported payment scheme: ${requirements.scheme}`);
      }

      if (Date.now() / 1000 > requirements.expires_at) {
        throw new Error('[x402] Payment requirements expired — retry the request');
      }

      if (!activeAddress) {
        throw new Error('[x402] No wallet connected — connect your Algorand wallet first');
      }

      // ── Step 3: Get suggested params from Algorand node ───────────────────
      const nodeUrl =
        process.env.NEXT_PUBLIC_ALGORAND_NODE_URL ?? 'https://testnet-api.algonode.cloud';
      const algodClient = new algosdk.Algodv2('', nodeUrl, '');
      const suggestedParams = await algodClient.getTransactionParams().do();

      // ── Step 4: Build payment transaction ────────────────────────────────
      const noteData = JSON.stringify({
        nonce: requirements.nonce,
        expires_at: requirements.expires_at,
      });

      const txn = algosdk.makePaymentTxnWithSuggestedParamsFromObject({
        sender: activeAddress,
        receiver: requirements.recipient,
        amount: requirements.amount,
        note: new TextEncoder().encode(noteData),
        suggestedParams,
      });

      // ── Step 5: Sign via existing wallet (Pera / Defly / Lute / etc.) ────
      let signedB64: string;
      try {
        const signedTxns = await signTransactions([txn]);
        const signedBytes = signedTxns[0];
        if (!signedBytes) throw new Error('Wallet returned empty signature');
        signedB64 = Buffer.from(signedBytes).toString('base64');
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        throw new Error(`[x402] Transaction signing failed: ${msg}`);
      }

      // ── Step 6: Retry with payment headers ───────────────────────────────
      const headers = new Headers(options?.headers);
      headers.set('X-PAYMENT', signedB64);
      headers.set('X-PAYMENT-NONCE', requirements.nonce);

      const retryResponse = await fetch(url, { ...options, headers });

      if (retryResponse.status === 402) {
        throw new Error('[x402] Payment rejected by server — check ALGO balance and try again');
      }

      return retryResponse;
    },
    [signTransactions, activeAddress],
  );
}
