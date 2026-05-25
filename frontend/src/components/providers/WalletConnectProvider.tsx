'use client';

import { WalletProvider, WalletManager, WalletId, NetworkId, NetworkConfigBuilder } from '@txnlab/use-wallet-react';

const walletManager = new WalletManager({
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

export function WalletConnectProvider({ children }: { children: React.ReactNode }) {
  return (
    <WalletProvider manager={walletManager}>
      {children}
    </WalletProvider>
  );
}
