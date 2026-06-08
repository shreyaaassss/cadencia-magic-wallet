'use client';

import { Magic } from 'magic-sdk';
import { AlgorandExtension } from '@magic-ext/algorand';

// Keep a direct reference to the extension instance so we can call
// signTransaction even when magic.algorand is undefined (which happens
// when the CJS webpack aliases break the extension property registration).
let _algorandExt: AlgorandExtension | null = null;

function createMagicInstance() {
  if (typeof window === 'undefined') return null;

  const key = process.env.NEXT_PUBLIC_MAGIC_PUBLISHABLE_KEY;
  const rpcUrl =
    process.env.NEXT_PUBLIC_ALGORAND_NODE_URL ?? 'https://testnet-api.algonode.cloud';

  if (!key) {
    console.warn('[magic] NEXT_PUBLIC_MAGIC_PUBLISHABLE_KEY not set');
    return null;
  }

  const ext = new AlgorandExtension({ rpcUrl });
  _algorandExt = ext;

  return new Magic(key, {
    extensions: [ext as any],
  });
}

export const magic = createMagicInstance();

/** Returns the Magic-managed Algorand address for the current session. */
export async function getMagicAddress(): Promise<string> {
  if (!magic) throw new Error('Magic SDK not available');
  const info = await (magic.user as any).getInfo();
  const address = (info as any).publicAddress as string;
  if (!address) throw new Error('No Algorand address in Magic session');
  return address;
}

// ── Shared helpers ──────────────────────────────────────────────────────────

function uint8ToB64(bytes: Uint8Array): string {
  let bin = '';
  for (let j = 0; j < bytes.length; j++) bin += String.fromCharCode(bytes[j]);
  return btoa(bin);
}

function b64ToUint8(b64: string): Uint8Array {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let j = 0; j < bin.length; j++) bytes[j] = bin.charCodeAt(j);
  return bytes;
}

/**
 * Extract base64-encoded signed bytes from whatever Magic's relay returns.
 *
 * signTransaction returns { txID: string, blob: Uint8Array } — a thin
 * JSON-RPC shim over algosdk's signing output. The relay transports it
 * via postMessage structured clone, so blob is a genuine same-realm
 * Uint8Array and instanceof works normally.
 */
function extractSignedB64(result: any): string {
  if (typeof result === 'string') return result;
  if (result instanceof Uint8Array) return uint8ToB64(result);

  if (result && typeof result === 'object') {
    // { txID, blob } — standard Magic Algorand return shape
    if ('blob' in result) {
      const blob = result.blob;
      if (typeof blob === 'string') return blob;
      if (blob instanceof Uint8Array) return uint8ToB64(blob);
      // Fallback: blob as plain object with numeric keys
      const vals = Object.values(blob) as number[];
      if (vals.length > 0) return uint8ToB64(new Uint8Array(vals));
    }
    if ('signedTransaction' in result) return result.signedTransaction;
    if ('txn' in result) return result.txn;
  }

  console.error('[magic] extractSignedB64: unexpected format, keys:', Object.keys(result ?? {}), 'value:', JSON.stringify(result));
  throw new Error('Magic signTransaction returned unexpected format');
}

// ── Public API ──────────────────────────────────────────────────────────────

/**
 * Signs a base64-encoded unsigned Algorand transaction.
 * Returns base64-encoded signed transaction bytes.
 */
export async function signAlgoTxn(encodedTxnB64: string): Promise<string> {
  if (!magic) throw new Error('Magic SDK not available');

  const algExt = (magic as any).algod ?? (magic as any).algorand ?? _algorandExt;
  if (!algExt) throw new Error('Algorand extension not initialised — check @magic-ext/algorand is loaded');

  console.log('[magic] signAlgoTxn — ext:', algExt?.name);
  const txnBytes = b64ToUint8(encodedTxnB64);
  const signedResult: any = await algExt.signTransaction(txnBytes);

  console.log('[magic] signAlgoTxn result keys:', Object.keys(signedResult ?? {}));
  const b64 = extractSignedB64(signedResult);
  console.log('[magic] signAlgoTxn b64 length:', b64.length);
  if (!b64) throw new Error('Magic signTransaction produced empty signed bytes');
  return b64;
}

/**
 * Signs a group of transactions together.
 * Returns array of base64-encoded signed transaction bytes.
 */
export async function signAlgoTxnGroup(encodedTxnsB64: string[]): Promise<string[]> {
  if (!magic) throw new Error('Magic SDK not available');

  const algExt = (magic as any).algod ?? (magic as any).algorand ?? _algorandExt;
  if (!algExt) throw new Error('Algorand extension not initialised — check @magic-ext/algorand is loaded');

  console.log('[magic] signAlgoTxnGroup — ext name:', algExt.name, 'txn count:', encodedTxnsB64.length);

  const results: string[] = [];
  for (let i = 0; i < encodedTxnsB64.length; i++) {
    console.log(`[magic] signing txn ${i + 1}/${encodedTxnsB64.length}`);
    const txnBytes = b64ToUint8(encodedTxnsB64[i]);
    const signedResult: any = await algExt.signTransaction(txnBytes);

    console.log('[magic] signedResult keys:', Object.keys(signedResult ?? {}));
    const signedB64 = extractSignedB64(signedResult);
    console.log('[magic] signedB64 length:', signedB64.length);
    results.push(signedB64);
  }
  return results;
}
