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
