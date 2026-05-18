/**
 * Magic.link SDK initialisation with Algorand extension.
 *
 * Exports:
 *   magic               — Magic SDK singleton (browser-only, null on SSR)
 *   getMagicWallet      — Returns the Algorand public address for the current session
 *   signAlgoTransaction — Signs a base64-encoded unsigned Algorand transaction
 */

import { Magic } from 'magic-sdk';
import { AlgorandExtension } from '@magic-ext/algorand';

// ── Singleton (browser-only) ──────────────────────────────────────────────────

function createMagicInstance(): InstanceType<typeof Magic> | null {
  if (typeof window === 'undefined') return null;

  const key = process.env.NEXT_PUBLIC_MAGIC_PUBLISHABLE_KEY;
  const rpcUrl =
    process.env.NEXT_PUBLIC_ALGORAND_NODE_URL ?? 'https://testnet-api.algonode.cloud';

  if (!key) {
    console.warn('[magic] NEXT_PUBLIC_MAGIC_PUBLISHABLE_KEY is not set — Magic disabled');
    return null;
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return new Magic(key, {
    extensions: [new AlgorandExtension({ rpcUrl }) as any],
  }) as InstanceType<typeof Magic>;
}

export const magic = createMagicInstance();

// ── Utility helpers ───────────────────────────────────────────────────────────

/**
 * Returns the Algorand public address for the currently authenticated Magic user.
 *
 * Throws if no Magic SDK is available or no session is active.
 */
export async function getMagicWallet(): Promise<string> {
  if (!magic) throw new Error('[magic] Magic SDK unavailable in server context');

  const metadata = await magic.user.getMetadata();
  const address = (metadata as unknown as Record<string, unknown>).publicAddress as string | undefined;

  if (!address) throw new Error('[magic] No Algorand address found in Magic session');
  return address;
}

/**
 * Signs a base64-encoded **unsigned** Algorand transaction using the Magic wallet.
 *
 * @param encodedTxn — Base64 representation of `algosdk.encodeUnsignedTransaction(txn)`
 * @returns           Base64 representation of the signed transaction bytes
 */
export async function signAlgoTransaction(encodedTxn: string): Promise<string> {
  if (!magic) throw new Error('[magic] Magic SDK unavailable in server context');

  const txnBytes = Buffer.from(encodedTxn, 'base64');

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const signedBytes: Uint8Array = await (magic as any).algorand.signTransaction(txnBytes);

  return Buffer.from(signedBytes).toString('base64');
}
