'use client';

import React, { useEffect, useState } from 'react';
import { WalletProvider, WalletManager, WalletId, NetworkId } from '@txnlab/use-wallet-react';

let _manager: WalletManager | null = null;

function getWalletManager(): WalletManager {
  if (!_manager) {
    _manager = new WalletManager({
      wallets: [
        WalletId.PERA,
        WalletId.DEFLY,
        WalletId.LUTE,
      ],
      defaultNetwork: NetworkId.TESTNET,
    });
  }
  return _manager;
}

/**
 * Create a fresh WalletManager with no cached sessions.
 * Clears WalletConnect v2 localStorage keys first so the
 * SignClient doesn't auto-restore a stale session.
 */
export function createFreshWalletManager(): WalletManager {
  // Clear WC v2 session keys from localStorage (synchronous — runs before manager init)
  if (typeof window !== 'undefined') {
    const keysToDelete: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && /^wc@|^walletconnect|^WALLET_CONNECT/i.test(key)) {
        keysToDelete.push(key);
      }
    }
    keysToDelete.forEach((k) => localStorage.removeItem(k));
  }
  return new WalletManager({
    wallets: [WalletId.PERA, WalletId.DEFLY, WalletId.LUTE],
    defaultNetwork: NetworkId.TESTNET,
  });
}

export function WalletConnectProvider({ children }: { children: React.ReactNode }) {
  const [manager, setManager] = useState<WalletManager | null>(null);

  useEffect(() => {
    setManager(getWalletManager());
  }, []);

  if (!manager) {
    return <>{children}</>;
  }

  return (
    <WalletProvider manager={manager}>
      {children}
    </WalletProvider>
  );
}
