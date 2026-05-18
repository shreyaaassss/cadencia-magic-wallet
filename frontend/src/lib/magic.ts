'use client';

import { Magic } from 'magic-sdk';
import { AlgorandExtension } from '@magic-ext/algorand';

function createMagicInstance() {
  if (typeof window === 'undefined') return null;

  const key = process.env.NEXT_PUBLIC_MAGIC_PUBLISHABLE_KEY;
  const rpcUrl =
    process.env.NEXT_PUBLIC_ALGORAND_NODE_URL ?? 'https://testnet-api.algonode.cloud';

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
  // user.getInfo() is the non-deprecated replacement for user.getMetadata()
  const info = await (magic.user as any).getInfo();
  const address = (info as any).publicAddress as string;
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
