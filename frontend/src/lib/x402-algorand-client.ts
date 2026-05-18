/**
 * x402 Algorand payment client.
 *
 * Wraps `fetch` with automatic 402 handling for Algorand-native payments.
 *
 * Flow:
 *   1. Make the initial request
 *   2. If 402 → extract payment requirements from response body
 *   3. Build an Algorand payment txn (algosdk) using the requirements
 *   4. Sign the txn via Magic's Algorand extension
 *   5. Retry the request with X-PAYMENT and X-PAYMENT-NONCE headers
 *   6. Return the final response
 */

import algosdk from 'algosdk';
import { magic, getMagicWallet } from '@/lib/magic';

// ── Types ─────────────────────────────────────────────────────────────────────

interface AlgorandPaymentRequirements {
  scheme: string;
  version: string;
  amount: number;       // microALGO
  recipient: string;    // Algorand address
  currency: string;
  nonce: string;        // UUID-v4 for replay protection
  expires_at: number;   // Unix timestamp
}

// ── Helper: get algod suggested params ───────────────────────────────────────

async function getSuggestedParams(): Promise<algosdk.SuggestedParams> {
  const nodeUrl =
    process.env.NEXT_PUBLIC_ALGORAND_NODE_URL ?? 'https://testnet-api.algonode.cloud';
  const client = new algosdk.Algodv2('', nodeUrl, '');
  return client.getTransactionParams().do();
}

// ── Core function ─────────────────────────────────────────────────────────────

/**
 * Fetch wrapper that handles HTTP 402 by automatically paying with Algorand.
 *
 * On 402:
 *   - Parses payment requirements from the response body JSON
 *   - Builds and signs an Algorand payment transaction via Magic wallet
 *   - Retries the original request with payment proof headers
 *
 * @throws If payment fails, Magic is unavailable, or the retry returns 402.
 */
export async function fetchWithAlgorandPayment(
  url: string,
  options?: RequestInit,
): Promise<Response> {
  // ── Step 1: Initial request ─────────────────────────────────────────────────
  const initialResponse = await fetch(url, options);

  if (initialResponse.status !== 402) {
    return initialResponse;
  }

  // ── Step 2: Parse payment requirements ─────────────────────────────────────
  let requirements: AlgorandPaymentRequirements;
  try {
    const body = await initialResponse.json();
    // Backend wraps in ApiResponse envelope; detail contains the requirements object
    requirements = (body.detail ?? body) as AlgorandPaymentRequirements;
  } catch {
    throw new Error('[x402] Failed to parse payment requirements from 402 response');
  }

  if (requirements.scheme !== 'algorand-payment') {
    throw new Error(
      `[x402] Unsupported payment scheme: ${requirements.scheme}. Expected "algorand-payment".`,
    );
  }

  // Check expiry before attempting payment
  if (Date.now() / 1000 > requirements.expires_at) {
    throw new Error('[x402] Payment requirements have expired — please retry the request');
  }

  if (!magic) {
    throw new Error('[x402] Magic SDK not available — cannot sign Algorand payment transaction');
  }

  // ── Step 3: Get sender address ──────────────────────────────────────────────
  let senderAddress: string;
  try {
    senderAddress = await getMagicWallet();
  } catch {
    throw new Error('[x402] No Magic wallet connected — please login with Magic first');
  }

  // ── Step 4: Build Algorand payment transaction ──────────────────────────────
  let signedTxnB64: string;
  try {
    const suggestedParams = await getSuggestedParams();

    // Embed nonce and expiry in the transaction note for backend validation
    const noteData = JSON.stringify({
      nonce: requirements.nonce,
      expires_at: requirements.expires_at,
    });
    const noteBytes = new TextEncoder().encode(noteData);

    const txn = algosdk.makePaymentTxnWithSuggestedParamsFromObject({
      sender: senderAddress,
      receiver: requirements.recipient,
      amount: requirements.amount,
      note: noteBytes,
      suggestedParams,
    });

    // Encode unsigned transaction for Magic to sign
    const encodedTxn = algosdk.encodeUnsignedTransaction(txn);
    const encodedB64 = Buffer.from(encodedTxn).toString('base64');

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const signedBytes: Uint8Array = await (magic as any).algorand.signTransaction(
      Buffer.from(encodedB64, 'base64'),
    );
    signedTxnB64 = Buffer.from(signedBytes).toString('base64');
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    throw new Error(`[x402] Failed to build or sign Algorand payment transaction: ${message}`);
  }

  // ── Step 5: Retry with payment headers ─────────────────────────────────────
  const paymentHeaders = new Headers(options?.headers);
  paymentHeaders.set('X-PAYMENT', signedTxnB64);
  paymentHeaders.set('X-PAYMENT-NONCE', requirements.nonce);

  const retryResponse = await fetch(url, {
    ...options,
    headers: paymentHeaders,
  });

  // ── Step 6: Handle retry result ─────────────────────────────────────────────
  if (retryResponse.status === 402) {
    throw new Error(
      '[x402] Payment was rejected by the server — check ALGO balance and try again',
    );
  }

  return retryResponse;
}
