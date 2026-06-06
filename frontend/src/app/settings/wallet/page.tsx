'use client';

import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Wallet, RefreshCw, Copy, ExternalLink, Sparkles, ArrowUpRight, ArrowDownRight, Clock } from 'lucide-react';
import { toast } from 'sonner';
import { api } from '@/lib/api';
import { formatDate } from '@/lib/utils';

import { AppShell } from '@/components/layout/AppShell';
import { Button } from '@/components/ui/button';
import { useWalletContext } from '@/context/WalletContext';

export default function WalletPage() {
  const {
    activeAddress,
    isLinked,
    linkedAddress,
    balance,
    isLoadingBalance,
    refreshBalance,
  } = useWalletContext();

  useEffect(() => {
    if (isLinked) refreshBalance();
  }, [isLinked, refreshBalance]);

  const copyAddress = () => {
    if (linkedAddress) {
      navigator.clipboard.writeText(linkedAddress);
      toast.success('Address copied');
    }
  };

  return (
    <AppShell>
      <div className="p-6 max-w-2xl">
        <h1 className="text-2xl font-semibold text-foreground">Wallet</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Your Algorand wallet is managed automatically via Magic — no app or seed phrase needed.
        </p>

        <div className="mt-8 space-y-6">

          {/* Magic wallet info banner */}
          <div className="bg-primary/5 border border-primary/20 rounded-lg p-4 flex items-start gap-3">
            <Sparkles className="h-5 w-5 text-primary mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-medium text-foreground">Embedded wallet — always ready</p>
              <p className="text-xs text-muted-foreground mt-1">
                Magic creates a non-custodial Algorand wallet tied to your email.
                It&apos;s automatically linked to your enterprise and ready for all transactions.
                No QR codes, no Pera app, no reconnects ever.
              </p>
            </div>
          </div>

          {/* No wallet yet — shouldn't happen but handle gracefully */}
          {!activeAddress && !linkedAddress && (
            <div className="bg-card border border-border rounded-lg p-8 text-center">
              <div className="bg-muted rounded-full p-4 w-16 h-16 mx-auto mb-4 flex items-center justify-center">
                <Wallet className="h-8 w-8 text-muted-foreground" />
              </div>
              <h2 className="text-lg font-medium text-foreground mb-2">Wallet Initializing</h2>
              <p className="text-sm text-muted-foreground">
                Your wallet is being set up. If this persists, try logging out and back in.
              </p>
            </div>
          )}

          {/* Linked wallet card */}
          {(activeAddress || linkedAddress) && (
            <div className="bg-card border border-border rounded-lg p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold text-foreground">Linked Wallet</h3>
                <span className="inline-flex items-center gap-1 text-xs text-green-600 bg-green-50 px-2 py-1 rounded-full">
                  <span className="w-1.5 h-1.5 bg-green-500 rounded-full" />
                  {isLinked ? 'Linked' : 'Pending link'}
                </span>
              </div>

              <div className="flex items-center gap-2 mb-2">
                <code className="text-sm font-mono text-foreground bg-muted px-3 py-1.5 rounded flex-1 overflow-hidden text-ellipsis">
                  {linkedAddress ?? activeAddress}
                </code>
                <Button variant="ghost" size="sm" onClick={copyAddress} title="Copy address">
                  <Copy className="h-4 w-4" />
                </Button>
                <a
                  href={`https://testnet.algoexplorer.io/address/${linkedAddress ?? activeAddress}`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Button variant="ghost" size="sm" title="View on explorer">
                    <ExternalLink className="h-4 w-4" />
                  </Button>
                </a>
              </div>
              <p className="text-xs text-muted-foreground">
                This address is cryptographically tied to your email and never changes.
              </p>
            </div>
          )}

          {/* Balance Card */}
          {isLinked && (
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
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
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

              <div className="pt-4 border-t border-border">
                <p className="text-xs text-muted-foreground mb-2">
                  Add ALGO by sending to your address above, or use the TestNet faucet for development.
                </p>
                <a
                  href="https://bank.testnet.algorand.network/"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Button variant="outline" size="sm" type="button">
                    <ExternalLink className="h-4 w-4 mr-2" />
                    Open TestNet Faucet
                  </Button>
                </a>
              </div>
            </div>
          )}
        </div>

        {/* Wallet Transaction History */}
        {isLinked && <WalletTransactionHistory />}
      </div>
    </AppShell>
  );
}


function WalletTransactionHistory() {
  const { data: transactions = [], isLoading } = useQuery<any[]>({
    queryKey: ['wallet-transactions-settings'],
    queryFn: () => api.get('/v1/wallet/transactions?limit=30').then(r => r.data?.data || []),
  });

  return (
    <div className="space-y-3">
      <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
        <Clock className="h-4 w-4 text-muted-foreground" />
        Transaction History
      </h2>
      <p className="text-xs text-muted-foreground">All ALGO movements linked to your wallet — escrow funding, releases, refunds, and payments.</p>

      {isLoading ? (
        <p className="text-sm text-muted-foreground py-4 text-center">Loading transactions...</p>
      ) : transactions.length === 0 ? (
        <div className="border border-dashed border-border rounded-lg py-8 text-center">
          <Wallet className="h-8 w-8 mx-auto text-muted-foreground mb-2" />
          <p className="text-sm text-muted-foreground">No transactions yet</p>
          <p className="text-xs text-muted-foreground">Transactions will appear here after escrow funding or release.</p>
        </div>
      ) : (
        <div className="border border-border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="text-left px-4 py-2 font-medium text-muted-foreground">Event</th>
                <th className="text-left px-4 py-2 font-medium text-muted-foreground">Direction</th>
                <th className="text-right px-4 py-2 font-medium text-muted-foreground">Amount</th>
                <th className="text-left px-4 py-2 font-medium text-muted-foreground">TX ID</th>
                <th className="text-left px-4 py-2 font-medium text-muted-foreground">Date</th>
              </tr>
            </thead>
            <tbody>
              {transactions.map((tx: any) => (
                <tr key={tx.id} className="border-t border-border hover:bg-muted/30">
                  <td className="px-4 py-2 text-foreground text-xs font-medium">{tx.event_type?.replace(/_/g, ' ')}</td>
                  <td className="px-4 py-2">
                    <span className={tx.direction === 'CREDIT' ? 'text-green-600 text-xs' : 'text-red-600 text-xs'}>
                      {tx.direction === 'CREDIT' ? <ArrowDownRight className="inline h-3 w-3 mr-0.5" /> : <ArrowUpRight className="inline h-3 w-3 mr-0.5" />}
                      {tx.direction}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right text-foreground font-mono text-xs">{tx.amount_algo} ALGO</td>
                  <td className="px-4 py-2 text-xs">
                    {tx.tx_id ? (
                      <a href={`https://testnet.explorer.perawallet.app/tx/${tx.tx_id}`} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline font-mono">
                        {tx.tx_id.slice(0, 10)}...
                      </a>
                    ) : <span className="text-muted-foreground">—</span>}
                  </td>
                  <td className="px-4 py-2 text-muted-foreground text-xs">{tx.created_at ? formatDate(tx.created_at) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
