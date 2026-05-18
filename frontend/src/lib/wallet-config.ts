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

  // Build wallet list imperatively to avoid TS discriminated-union narrowing
  // issues when spreading a conditional WalletConnect entry.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const wallets: any[] = [WalletId.PERA, WalletId.DEFLY];
  if (WC_PROJECT_ID) {
    // WalletConnect v2 generic modal — authenticates the relay so the
    // sign-client doesn't crash on importKey. Only added when a project ID
    // is available (baked in at Docker build time from WALLETCONNECT_PROJECT_ID secret).
    wallets.push({ id: WalletId.WALLETCONNECT, options: { projectId: WC_PROJECT_ID } });
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

// Key used to track which enterprise ID owns the stored wallet session.
const WALLET_OWNER_KEY = 'cadencia:wallet-session-owner';

// Key that remembers which wallet provider the user last connected with.
export const LAST_WALLET_KEY = 'cadencia:last-wallet';

export function setLastWalletId(walletId: string): void {
  if (typeof window !== 'undefined') {
    localStorage.setItem(LAST_WALLET_KEY, walletId);
  }
}

export function getLastWalletId(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(LAST_WALLET_KEY);
}

/**
 * Purge all wallet localStorage keys unconditionally.
 * Used when a different user logs in to prevent session bleed.
 */
function _purgeAllWalletKeys(): void {
  if (typeof window === 'undefined') return;
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
    localStorage.removeItem(WALLET_OWNER_KEY);
  } catch {
    // Non-fatal
  }
}

/**
 * Called after login. If the stored wallet session belongs to a different
 * enterprise, purge it. Same enterprise → keep it so the session auto-resumes.
 */
export function clearForeignWalletSession(enterpriseId: string): void {
  if (typeof window === 'undefined') return;
  const storedOwner = localStorage.getItem(WALLET_OWNER_KEY);
  if (storedOwner && storedOwner !== enterpriseId) {
    // Different user logged in — purge the previous user's wallet session
    _purgeAllWalletKeys();
  }
  // Record the current owner so next login can compare
  localStorage.setItem(WALLET_OWNER_KEY, enterpriseId);
}

/**
 * Disconnect the active wallet and record the owner enterprise ID.
 * Session keys are preserved in localStorage so the same user can
 * auto-reconnect on next login without re-scanning the QR code.
 *
 * Cross-user session bleed is prevented by clearForeignWalletSession()
 * which is called on login and purges keys if a different enterprise logs in.
 */
export async function destroyWalletManager(enterpriseId?: string): Promise<void> {
  // Record current owner before tearing down, so next login can compare
  if (enterpriseId && typeof window !== 'undefined') {
    localStorage.setItem(WALLET_OWNER_KEY, enterpriseId);
  }

  if (_manager) {
    try {
      const active = (_manager as any).activeWallet;
      if (active?.disconnect) await active.disconnect();
    } catch {
      // Non-fatal — wallet may already be disconnected
    }
    _manager = null;
  }

  // Session keys (@txnlab/*, walletconnect, pera, defly) are intentionally
  // kept in localStorage so the same user can auto-reconnect on next login.
  // clearForeignWalletSession() handles the cross-user purge on login.
}
