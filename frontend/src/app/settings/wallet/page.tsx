'use client';

import { useEffect, useState } from 'react';
import { Wallet, Link2, Unlink, RefreshCw, Loader2, Copy, ExternalLink, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';

import { AppShell } from '@/components/layout/AppShell';
import { Button } from '@/components/ui/button';
import { useWalletContext } from '@/context/WalletContext';
import { getLastWalletId } from '@/lib/wallet-config';
import { truncateAddress } from '@/lib/utils';

export default function WalletPage() {
  const {
    wallets,
    activeAddress,
    isWalletConnected,
    isReady,
    isConnecting,
    connectWallet,
    disconnectWallet,
    isLinked,
    linkedAddress,
    balance,
    isLoadingBalance,
    linkStatus,
    error,
    linkWallet,
    unlinkWallet,
    refreshBalance,
  } = useWalletContext();

  const [lastWalletId, setLastWalletIdState] = useState<string | null>(null);

  useEffect(() => {
    setLastWalletIdState(getLastWalletId());
  }, []);

  useEffect(() => {
    if (isLinked) refreshBalance();
  }, [isLinked, refreshBalance]);

  const copyAddress = () => {
    if (linkedAddress) {
      navigator.clipboard.writeText(linkedAddress);
      toast.success('Address copied');
    }
  };

  const isLinking = linkStatus === 'signing' || linkStatus === 'submitting';

  // Wallet is linked to this account but the WalletConnect session expired
  const needsReconnect = isLinked && !isWalletConnected;

  return (
    <AppShell>
      <div className="p-6 max-w-2xl">
        <h1 className="text-2xl font-semibold text-foreground">Wallet Management</h1>
        <p className="text-sm text-muted-foreground mt-1">Connect your Algorand wallet to deploy escrow contracts and fund trades</p>

        {error && (
          <div className="mt-4 p-3 bg-red-950 border border-destructive/40 rounded-lg text-sm text-destructive">
            {error}
          </div>
        )}

        <div className="mt-8 space-y-6">

          {/* Step 1: Connect or Reconnect */}
          {!isWalletConnected && (
            <div className="bg-card border border-border rounded-lg p-8 text-center">
              <div className="bg-muted rounded-full p-4 w-16 h-16 mx-auto mb-4 flex items-center justify-center">
                {needsReconnect
                  ? <RotateCcw className="h-8 w-8 text-amber-400" />
                  : <Wallet className="h-8 w-8 text-muted-foreground" />
                }
              </div>

              {needsReconnect ? (
                <>
                  <h2 className="text-lg font-medium text-foreground mb-2">Reconnect Your Wallet</h2>
                  <p className="text-sm text-muted-foreground mb-1 max-w-md mx-auto">
                    Your session expired. Reconnect the same wallet to continue signing escrow transactions.
                  </p>
                  <code className="inline-block text-xs font-mono text-muted-foreground bg-muted px-3 py-1 rounded mb-6">
                    {linkedAddress ? `${linkedAddress.slice(0, 12)}…${linkedAddress.slice(-6)}` : ''}
                  </code>
                </>
              ) : (
                <>
                  <h2 className="text-lg font-medium text-foreground mb-2">Connect Your Wallet</h2>
                  <p className="text-sm text-muted-foreground mb-6 max-w-md mx-auto">
                    Choose a wallet to connect. Your wallet will be used to sign transactions for escrow funding and settlement.
                  </p>
                </>
              )}

              <div className="flex flex-col gap-3 max-w-xs mx-auto">
                {isReady && wallets.map(wallet => {
                  const isLastUsed = wallet.id === lastWalletId;
                  return (
                    <Button
                      key={wallet.id}
                      variant={isLastUsed && needsReconnect ? 'default' : 'outline'}
                      className={`w-full justify-start gap-3 h-12 ${isLastUsed && needsReconnect ? 'ring-2 ring-primary' : ''}`}
                      disabled={isConnecting}
                      onClick={() => connectWallet(wallet.id)}
                    >
                      {isConnecting && isLastUsed ? (
                        <Loader2 className="h-5 w-5 animate-spin" />
                      ) : wallet.metadata.icon ? (
                        <img src={wallet.metadata.icon} alt={wallet.metadata.name} className="w-6 h-6 rounded" />
                      ) : null}
                      <span className="font-medium">
                        {isConnecting && isLastUsed ? 'Connecting...' : wallet.metadata.name}
                      </span>
                      {isLastUsed && needsReconnect && (
                        <span className="ml-auto text-xs opacity-75">Last used</span>
                      )}
                    </Button>
                  );
                })}
                {!isReady && (
                  <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Initializing wallets...
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Step 2: Wallet connected but not linked to Cadencia */}
          {isWalletConnected && !isLinked && (
            <div className="bg-card border border-border rounded-lg p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold text-foreground">Connected Wallet</h3>
                <Button variant="ghost" size="sm" onClick={disconnectWallet} className="text-muted-foreground text-xs">
                  Disconnect
                </Button>
              </div>
              <div className="bg-muted px-3 py-2 rounded text-sm font-mono text-foreground mb-4 truncate">
                {activeAddress}
              </div>
              <p className="text-sm text-muted-foreground mb-4">
                Your wallet is connected. Link it to your Cadencia enterprise to enable escrow funding and on-chain operations.
              </p>
              <Button onClick={linkWallet} disabled={isLinking} className="bg-primary text-primary-foreground w-full">
                {isLinking ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    {linkStatus === 'signing' ? 'Sign in wallet...' : 'Linking...'}
                  </>
                ) : (
                  <>
                    <Link2 className="mr-2 h-4 w-4" />
                    Link to Cadencia
                  </>
                )}
              </Button>
            </div>
          )}

          {/* Step 3: Wallet linked — show address + balance */}
          {isLinked && (
            <>
              {/* Address Card */}
              <div className="bg-card border border-border rounded-lg p-5">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-sm font-semibold text-foreground">Linked Wallet</h3>
                  <span className="inline-flex items-center gap-1 text-xs text-green-500 bg-green-500/10 px-2 py-1 rounded-full">
                    <span className="w-1.5 h-1.5 bg-green-500 rounded-full" />
                    Linked
                  </span>
                </div>

                <div className="flex items-center gap-2 mb-4">
                  <code className="text-sm font-mono text-foreground bg-muted px-3 py-1.5 rounded flex-1 overflow-hidden text-ellipsis">
                    {linkedAddress}
                  </code>
                  <Button variant="ghost" size="sm" onClick={copyAddress} title="Copy address">
                    <Copy className="h-4 w-4" />
                  </Button>
                  <a
                    href={`https://testnet.algoexplorer.io/address/${linkedAddress}`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <Button variant="ghost" size="sm" title="View on explorer">
                      <ExternalLink className="h-4 w-4" />
                    </Button>
                  </a>
                </div>

                <div className="flex gap-2">
                  <Button variant="outline" size="sm" onClick={unlinkWallet} className="text-destructive hover:text-destructive">
                    <Unlink className="mr-2 h-4 w-4" />
                    Unlink Wallet
                  </Button>
                  {isWalletConnected && (
                    <Button variant="ghost" size="sm" onClick={disconnectWallet} className="text-muted-foreground">
                      Disconnect
                    </Button>
                  )}
                </div>
              </div>

              {/* Balance Card */}
              <div className="bg-card border border-border rounded-lg p-5">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-sm font-semibold text-foreground">Balance</h3>
                  <Button variant="ghost" size="sm" onClick={refreshBalance} disabled={isLoadingBalance}>
                    <RefreshCw className={`h-4 w-4 ${isLoadingBalance ? 'animate-spin' : ''}`} />
                  </Button>
                </div>

                {isLoadingBalance ? (
                  <div className="space-y-2">
                    <div className="h-8 w-32 bg-muted animate-pulse rounded" />
                    <div className="h-4 w-48 bg-muted animate-pulse rounded" />
                  </div>
                ) : balance ? (
                  <div className="space-y-3">
                    <div>
                      <p className="text-2xl font-semibold text-foreground">{balance.algo_balance_algo} ALGO</p>
                      <p className="text-xs text-muted-foreground">{balance.algo_balance_microalgo.toLocaleString()} microALGO</p>
                    </div>
                    <div className="grid grid-cols-2 gap-4 text-sm">
                      <div>
                        <p className="text-xs text-muted-foreground">Min Balance</p>
                        <p className="text-foreground">{(balance.min_balance / 1_000_000).toFixed(3)} ALGO</p>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">Available</p>
                        <p className="text-foreground">{(balance.available_balance / 1_000_000).toFixed(3)} ALGO</p>
                      </div>
                    </div>
                    {balance.opted_in_apps.length > 0 && (
                      <div>
                        <p className="text-xs text-muted-foreground mb-1">Opted-in Applications</p>
                        <div className="flex flex-wrap gap-1">
                          {balance.opted_in_apps.map(app => (
                            <span key={app.app_id} className="text-xs bg-muted px-2 py-0.5 rounded font-mono">
                              {app.app_name ?? `App #${app.app_id}`}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">Click refresh to load balance</p>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </AppShell>
  );
}
