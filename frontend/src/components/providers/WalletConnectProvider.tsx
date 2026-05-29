'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { WalletProvider, WalletManager, WalletId, NetworkId } from '@txnlab/use-wallet-react';

/**
 * Clear all WalletConnect v2 data from localStorage (sync)
 * and IndexedDB (async, best-effort).
 */
function clearWcStorage() {
  if (typeof window === 'undefined') return;

  // 1. localStorage — synchronous, runs before WalletManager init
  const toDelete: string[] = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key && /^wc@|^walletconnect|^WALLET_CONNECT|^pera/i.test(key)) {
      toDelete.push(key);
    }
  }
  toDelete.forEach((k) => localStorage.removeItem(k));

  // 2. IndexedDB — async, best-effort (catches errors silently)
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
// Increment to force React re-render after reset
let _managerGeneration = 0;

function getWalletManager(): WalletManager {
  if (!_manager) {
    _manager = new WalletManager({
      wallets: [WalletId.PERA, WalletId.DEFLY, WalletId.LUTE],
      defaultNetwork: NetworkId.TESTNET,
    });
  }
  return _manager;
}

/**
 * Call on logout — destroys the singleton WalletManager and clears
 * all WalletConnect session data (localStorage + IndexedDB).
 * The next page that renders WalletConnectProvider will create a
 * fresh manager with zero stale sessions.
 */
export function resetWalletManager() {
  clearWcStorage();
  _manager = null;
  _managerGeneration++;
}

export function WalletConnectProvider({ children }: { children: React.ReactNode }) {
  const [manager, setManager] = useState<WalletManager | null>(null);
  const [gen, setGen] = useState(_managerGeneration);

  useEffect(() => {
    // If generation changed (logout happened), recreate
    if (gen !== _managerGeneration) {
      setGen(_managerGeneration);
    }
    setManager(getWalletManager());
  }, [gen]);

  // Listen for generation changes (logout from another component)
  useEffect(() => {
    const id = setInterval(() => {
      if (_managerGeneration !== gen) {
        setGen(_managerGeneration);
        setManager(getWalletManager());
      }
    }, 200);
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
