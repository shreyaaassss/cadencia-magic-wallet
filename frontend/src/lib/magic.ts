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
  const signedBytes: Uint8Array = await algExt.signTransaction(txnBytes);
  let signedBinary = '';
  for (let i = 0; i < signedBytes.length; i++) signedBinary += String.fromCharCode(signedBytes[i]);
  return btoa(signedBinary);
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
    const signedBytes: Uint8Array = await algExt.signTransaction(txnBytes);
    results.push(uint8ArrayToB64(signedBytes));
  }
  return results;
}
