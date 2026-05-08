import { NetworkId, WalletId, WalletManager } from '@txnlab/use-wallet-react';

const ALGOD_BASE = process.env.NEXT_PUBLIC_ALGOD_SERVER || 'https://testnet-api.4160.nodely.dev';
const ALGOD_PORT = process.env.NEXT_PUBLIC_ALGOD_PORT || '';
const ALGOD_TOKEN = process.env.NEXT_PUBLIC_ALGOD_TOKEN || '';
const NETWORK = (process.env.NEXT_PUBLIC_ALGORAND_NETWORK || 'testnet') as NetworkId;
// WalletConnect v2 project ID — required for the WalletConnect v2 relay.
// Pera and Defly use WalletConnect v1 internally (no projectId needed).
// WalletId.WALLETCONNECT (generic WC v2 modal) requires this explicitly.
const WC_PROJECT_ID = process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID || '';

let _manager: WalletManager | null = null;

export function getWalletManager(): WalletManager {
  if (_manager) return _manager;

  const wallets: Parameters<typeof WalletManager>[0]['wallets'] = [
    WalletId.PERA,
    WalletId.DEFLY,
  ];

  // Add generic WalletConnect v2 support when a project ID is available.
  // This covers wallets that connect via the WalletConnect QR/deep-link flow
  // and properly authenticates the WC v2 relay to prevent importKey errors.
  if (WC_PROJECT_ID) {
    wallets.push({
      id: WalletId.WALLETCONNECT,
      options: { projectId: WC_PROJECT_ID },
    });
  }

  _manager = new WalletManager({
    wallets,
    defaultNetwork: NETWORK,
    networks: {
      [NETWORK]: {
        algod: {
          baseServer: ALGOD_BASE,
          port: ALGOD_PORT,
          token: ALGOD_TOKEN,
        },
      },
    },
  });

  return _manager;
}

/**
 * Destroy the WalletManager singleton and purge all WalletConnect localStorage
 * keys for this origin. Must be called on logout to prevent wallet session bleed
 * when multiple users share the same browser.
 */
export async function destroyWalletManager(): Promise<void> {
  if (_manager) {
    try {
      const active = (_manager as any).activeWallet;
      if (active?.disconnect) await active.disconnect();
    } catch {
      // Non-fatal — wallet may already be disconnected
    }
    _manager = null;
  }

  // Purge all WalletConnect / Pera / use-wallet localStorage keys
  if (typeof window !== 'undefined') {
    try {
      const keysToRemove: string[] = [];
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key && (
          key.startsWith('wc@') ||
          key.startsWith('walletconnect') ||
          key.startsWith('@txnlab') ||
          key.startsWith('pera') ||
          key.startsWith('defly')
        )) {
          keysToRemove.push(key);
        }
      }
      keysToRemove.forEach(k => localStorage.removeItem(k));
    } catch {
      // Non-fatal
    }
  }
}
