'use client';

import React, { useEffect, useState } from 'react';
import { WalletProvider, WalletManager, WalletId, NetworkId } from '@txnlab/use-wallet-react';

/**
 * Clear all WalletConnect v2 session data from localStorage.
 * Must run SYNCHRONOUSLY before WalletManager is constructed,
 * otherwise the WC SignClient auto-restores stale sessions.
 */
function clearWcStorage() {
  if (typeof window === 'undefined') return;
  const toDelete: string[] = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key && /^wc@|^walletconnect|^WALLET_CONNECT/i.test(key)) {
      toDelete.push(key);
    }
  }
  toDelete.forEach((k) => localStorage.removeItem(k));
}

let _manager: WalletManager | null = null;

function getWalletManager(): WalletManager {
  if (!_manager) {
    // Nuke stale WC sessions BEFORE manager init — prevents
    // "Session currently connected/disconnected" errors on auth pages
    clearWcStorage();
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
