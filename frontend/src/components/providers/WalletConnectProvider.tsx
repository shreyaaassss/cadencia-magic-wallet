'use client';

import React, { useEffect, useState } from 'react';
import { WalletProvider, WalletManager, WalletId, NetworkId } from '@txnlab/use-wallet-react';

/**
 * Nuke ALL WalletConnect v2 session data so the next WalletManager
 * starts completely clean — no stale sessions, no "Session currently
 * connected/disconnected" errors.
 *
 * WC v2 stores data in THREE places:
 *   1. localStorage — keys starting with "wc@" or "walletconnect"
 *   2. IndexedDB — database "WALLET_CONNECT_V2_INDEXED_DB"
 *   3. Pera adapter — localStorage keys starting with "pera"
 */
function clearAllWcStorage() {
  if (typeof window === 'undefined') return;

  // 1. localStorage (sync)
  const toDelete: string[] = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (
      key &&
      (/^wc@|^wc_|^walletconnect|^WALLET_CONNECT|^pera/i.test(key) ||
        key === 'wc_storage_version')
    ) {
      toDelete.push(key);
    }
  }
  toDelete.forEach((k) => localStorage.removeItem(k));

  // 2. IndexedDB — the exact database WC v2 SignClient uses
  try {
    indexedDB.deleteDatabase('WALLET_CONNECT_V2_INDEXED_DB');
  } catch {}

  // 3. Any other WC-related IndexedDB databases (best-effort)
  try {
    indexedDB.databases?.().then((dbs) => {
      for (const db of dbs) {
        if (db.name && /wc|walletconnect|CORE/i.test(db.name)) {
          indexedDB.deleteDatabase(db.name);
        }
      }
    });
  } catch {}
}

let _manager: WalletManager | null = null;
let _generation = 0;

function createManager(): WalletManager {
  return new WalletManager({
    wallets: [WalletId.PERA, WalletId.DEFLY, WalletId.LUTE],
    defaultNetwork: NetworkId.TESTNET,
  });
}

/**
 * Call on logout or on auth page mount.
 * Destroys the WalletManager singleton and clears all WC session storage.
 * The next WalletConnectProvider render creates a fresh manager.
 */
export function resetWalletManager() {
  clearAllWcStorage();
  _manager = null;
  _generation++;
}

export function WalletConnectProvider({ children }: { children: React.ReactNode }) {
  const [manager, setManager] = useState<WalletManager | null>(null);
  const [gen, setGen] = useState(_generation);

  useEffect(() => {
    if (!_manager) {
      _manager = createManager();
    }
    setManager(_manager);
  }, [gen]);

  // Detect resetWalletManager() calls from other components
  useEffect(() => {
    const id = setInterval(() => {
      if (_generation !== gen) {
        setGen(_generation);
        _manager = createManager();
        setManager(_manager);
      }
    }, 300);
    return () => clearInterval(id);
  }, [gen]);

  if (!manager) {
    return <>{children}</>;
  }

  return (
    <WalletProvider manager={manager}>
      {children}
    </WalletProvider>
  );
}
