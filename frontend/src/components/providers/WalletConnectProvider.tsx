'use client';

import React, { useEffect, useState } from 'react';
import { WalletProvider, WalletManager, WalletId, NetworkId, NetworkConfigBuilder } from '@txnlab/use-wallet-react';

let _manager: WalletManager | null = null;

function getWalletManager(): WalletManager {
  if (!_manager) {
    _manager = new WalletManager({
      wallets: [
        WalletId.PERA,
        WalletId.DEFLY,
        WalletId.LUTE,
      ],
      networks: new NetworkConfigBuilder()
        .addNetwork(NetworkId.TESTNET, {
          algod: {
            baseServer: 'https://testnet-api.4160.nodely.dev',
            port: '',
            token: '',
          },
        })
        .build(),
      defaultNetwork: NetworkId.TESTNET,
    });
  }
  return _manager;
}

export function WalletConnectProvider({ children }: { children: React.ReactNode }) {
  const [manager, setManager] = useState<WalletManager | null>(null);

  useEffect(() => {
    // Only create manager on the client side
    setManager(getWalletManager());
  }, []);

  if (!manager) {
    // Server-side or initial render — render children without wallet context
    return <>{children}</>;
  }

  return (
    <WalletProvider manager={manager}>
      {children}
    </WalletProvider>
  );
}
