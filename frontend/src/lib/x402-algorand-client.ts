'use client';

/**
 * x402 Algorand payment client — Magic.link edition.
 *
 * Plain async function (not a React hook) that handles HTTP 402 automatically
 * using the user's Magic-managed embedded Algorand wallet.
 *
 * Flow:
 *   1. Make the initial request
 *   2. If 402 → parse payment requirements from response body
 *   3. Get the Magic-managed Algorand address (getMagicAddress)
 *   4. Build an Algorand payment txn using algosdk
 *   5. Sign via Magic (signAlgoTxn)
 *   6. Retry with X-PAYMENT and X-PAYMENT-NONCE headers
 */

import algosdk from 'algosdk';
import { magic, getMagicAddress, signAlgoTxn } from '@/lib/magic';

// ── Types ──────────────────────────────────────────────────────────────────────

interface AlgorandPaymentRequirements {
  scheme: string;
  version?: string;
  amount: number;       // microALGO
  recipient: string;    // Algorand address
  currency?: string;
  nonce: string;
  expires_at: number;   // Unix timestamp
}

// ── Plain async function ───────────────────────────────────────────────────────

/**
 * Fetch wrapper that intercepts HTTP 402 responses and pays automatically
 * using the user's Magic-managed embedded Algorand wallet.
 *
 * Can be called anywhere in the codebase — no React hook, no provider needed.
 */
export async function fetchWithAlgorandPayment(
  url: string,
  options?: RequestInit,
): Promise<Response> {
  // ── Step 1: Initial request ─────────────────────────────────────────────────
  const initial = await fetch(url, options);
  if (initial.status !== 402) return initial;

  // ── Step 2: Parse payment requirements ─────────────────────────────────────
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

  if (!magic) {
    throw new Error('[x402] Magic SDK not available');
  }

  // ── Step 3: Get Magic-managed address ──────────────────────────────────────
  const senderAddress = await getMagicAddress();

  // ── Step 4: Get suggested params from Algorand node ────────────────────────
  const nodeUrl =
    process.env.NEXT_PUBLIC_ALGORAND_NODE_URL ?? 'https://testnet-api.algonode.cloud';
  const algodClient = new algosdk.Algodv2('', nodeUrl, '');
  const suggestedParams = await algodClient.getTransactionParams().do();

  // ── Step 5: Build payment transaction ──────────────────────────────────────
  const txn = algosdk.makePaymentTxnWithSuggestedParamsFromObject({
    sender: senderAddress,
    receiver: requirements.recipient,
    amount: requirements.amount,
    note: new TextEncoder().encode(
      JSON.stringify({ nonce: requirements.nonce, expires_at: requirements.expires_at }),
    ),
    suggestedParams,
  });

  // ── Step 6: Sign via Magic ──────────────────────────────────────────────────
  let signedB64: string;
  try {
    const encodedB64 = Buffer.from(algosdk.encodeUnsignedTransaction(txn)).toString('base64');
    signedB64 = await signAlgoTxn(encodedB64);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    throw new Error(`[x402] Transaction signing failed: ${msg}`);
  }

  // ── Step 7: Retry with payment headers ─────────────────────────────────────
  const headers = new Headers(options?.headers);
  headers.set('X-PAYMENT', signedB64);
  headers.set('X-PAYMENT-NONCE', requirements.nonce);

  const retryResponse = await fetch(url, { ...options, headers });

  if (retryResponse.status === 402) {
    throw new Error('[x402] Payment rejected by server — check ALGO balance and try again');
  }

  return retryResponse;
}

/**
 * React hook wrapper kept for backwards compatibility.
 * Returns the same fetchWithAlgorandPayment function — no wallet provider needed.
 */
export function useFetchWithAlgorandPayment() {
  return fetchWithAlgorandPayment;
}
