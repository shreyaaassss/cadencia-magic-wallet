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

/**
 * Signs a base64-encoded unsigned Algorand transaction.
 * Returns base64-encoded signed transaction bytes.
 *
 * Uses the stored AlgorandExtension instance directly — this works even when
 * magic.algorand is undefined due to CJS/ESM build aliasing issues.
 */
export async function signAlgoTxn(encodedTxnB64: string): Promise<string> {
  if (!magic) throw new Error('Magic SDK not available');

  // Extension name is 'algod' (not 'algorand') in @magic-ext/algorand@24.4.2
  // Fall back to stored extension reference when the property isn't registered
  const algExt = (magic as any).algod ?? (magic as any).algorand ?? _algorandExt;
  if (!algExt) throw new Error('Algorand extension not initialised — check @magic-ext/algorand is loaded');

  console.log('[magic] signAlgoTxn — ext:', algExt?.name);
  const binary = atob(encodedTxnB64);
  const txnBytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) txnBytes[i] = binary.charCodeAt(i);
  const signedResult: any = await algExt.signTransaction(txnBytes);

  // Magic SDK may return Uint8Array, string, or { txID, blob } — handle all
  function uint8ToB64(bytes: Uint8Array): string {
    let bin = '';
    for (let j = 0; j < bytes.length; j++) bin += String.fromCharCode(bytes[j]);
    return btoa(bin);
  }

  // Magic SDK runs in an iframe — cross-realm objects fail instanceof checks.
  // Use Array.from() and duck typing instead.
  console.log('[magic] signAlgoTxn result keys:', signedResult ? Object.keys(signedResult) : 'null');

  // Helper: convert any array-like (including cross-realm Uint8Array) to base64
  function anyBytesToB64(src: any): string {
    // Array.from works on cross-realm typed arrays via Symbol.iterator
    const arr = Array.from(src) as number[];
    if (arr.length === 0) return '';
    return uint8ToB64(new Uint8Array(arr));
  }

  if (typeof signedResult === 'string') return signedResult;

  // Direct typed array (same realm)
  if (signedResult instanceof Uint8Array) return uint8ToB64(signedResult);

  // Cross-realm typed array: has .length and numeric [0]
  if (signedResult?.length > 0 && typeof signedResult[0] === 'number') {
    return anyBytesToB64(signedResult);
  }

  if (signedResult && typeof signedResult === 'object') {
    // { txID, blob } format from Magic relay
    if ('blob' in signedResult) {
      const blob = signedResult.blob;
      if (typeof blob === 'string') return blob;
      if (blob?.length > 0) return anyBytesToB64(blob);
      // blob as plain object { 0: n, 1: n, ... }
      const vals = Object.values(blob) as number[];
      if (vals.length > 0) return uint8ToB64(new Uint8Array(vals));
    }
    if ('signedTransaction' in signedResult) return signedResult.signedTransaction;
    if ('txn' in signedResult) return signedResult.txn;
  }

  console.error('[magic] signAlgoTxn: unexpected result:', JSON.stringify(signedResult));
  throw new Error('Magic signTransaction returned unexpected format');
}

/**
 * Signs a group of transactions together.
 * Use this for atomic groups (e.g. fund = [payTxn + appCallTxn]).
 * Returns array of base64-encoded signed transaction bytes.
 */
export async function signAlgoTxnGroup(encodedTxnsB64: string[]): Promise<string[]> {
  if (!magic) throw new Error('Magic SDK not available');

  const algExt = (magic as any).algod ?? (magic as any).algorand ?? _algorandExt;
  if (!algExt) throw new Error('Algorand extension not initialised — check @magic-ext/algorand is loaded');

  console.log('[magic] signAlgoTxnGroup — ext name:', algExt.name, 'txn count:', encodedTxnsB64.length);

  // Use atob() (native browser API) instead of Buffer.from() to avoid the Buffer polyfill
  // failing with "received type object" in browser environments.
  function b64ToUint8Array(b64: string): Uint8Array {
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let j = 0; j < binary.length; j++) {
      bytes[j] = binary.charCodeAt(j);
    }
    return bytes;
  }

  function uint8ArrayToB64(bytes: Uint8Array): string {
    let binary = '';
    for (let j = 0; j < bytes.length; j++) {
      binary += String.fromCharCode(bytes[j]);
    }
    return btoa(binary);
  }

  const results: string[] = [];
  for (let i = 0; i < encodedTxnsB64.length; i++) {
    console.log(`[magic] signing txn ${i + 1}/${encodedTxnsB64.length}, type:`, typeof encodedTxnsB64[i]);
    const txnBytes = b64ToUint8Array(encodedTxnsB64[i]);
    const signedResult: any = await algExt.signTransaction(txnBytes);

    // Log the FULL structure so we can see exactly what Magic returns
    console.log('[magic] signedResult FULL:', JSON.stringify(signedResult));
    console.log('[magic] signedResult keys:', Object.keys(signedResult ?? {}));

    let signedB64: string;
    if (typeof signedResult === 'string') {
      signedB64 = signedResult;
    } else if (signedResult instanceof Uint8Array) {
      signedB64 = uint8ArrayToB64(signedResult);
    } else if (signedResult?.buffer instanceof ArrayBuffer) {
      signedB64 = uint8ArrayToB64(new Uint8Array(signedResult.buffer));
    } else if (signedResult && typeof signedResult === 'object') {
      // Magic relay returns a plain object — check common keys
      const keys = Object.keys(signedResult);
      console.log('[magic] object keys:', keys);
      if ('blob' in signedResult) {
        // Magic returns { txID: "...", blob: Uint8Array }
        // blob is a Uint8Array in memory (JSON.stringify shows it as {"0":n,"1":n,...})
        const blob = (signedResult as any).blob;
        if (typeof blob === 'string') {
          signedB64 = blob;
        } else {
          // blob is Uint8Array or Uint8Array-like object with numeric keys
          const bytes = (blob instanceof Uint8Array || blob?.buffer instanceof ArrayBuffer)
            ? blob
            : new Uint8Array(Object.values(blob) as number[]);
          signedB64 = uint8ArrayToB64(bytes);
        }
      } else if ('signedTransaction' in signedResult) {
        signedB64 = (signedResult as any).signedTransaction;
      } else if ('txn' in signedResult) {
        signedB64 = (signedResult as any).txn;
      } else {
        // Might be a Uint8Array-like {0: byte, 1: byte, ...}
        const vals = Object.values(signedResult) as number[];
        if (vals.length > 0 && typeof vals[0] === 'number') {
          signedB64 = uint8ArrayToB64(new Uint8Array(vals));
        } else {
          console.error('[magic] Unknown signedResult structure:', signedResult);
          signedB64 = '';
        }
      }
    } else {
      signedB64 = '';
    }

    console.log('[magic] signedB64 length:', signedB64.length, 'preview:', signedB64.slice(0, 30));
    results.push(signedB64);
  }
  return results;
}
