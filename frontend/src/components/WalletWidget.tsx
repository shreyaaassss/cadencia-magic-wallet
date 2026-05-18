'use client';

/**
 * WalletWidget — displays the connected Algorand wallet info and x402 payment history.
 *
 * Uses the existing CadenciaWalletContext (Pera / Defly / Lute / etc.) —
 * no second wallet needed.
 *
 * Shows:
 *   - Algorand address (truncated, copy-to-clipboard)
 *   - ALGO balance (from platform balance endpoint)
 *   - "Get TestNet ALGO" button linking to the Algorand faucet
 *   - Last 5 x402 payment records
 */

import React, { useCallback, useEffect, useState } from 'react';
import { Copy, Check, ExternalLink, RefreshCw, Wallet } from 'lucide-react';
import { useWalletContext } from '@/context/WalletContext';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';

// ── Types ─────────────────────────────────────────────────────────────────────

interface X402PaymentRecord {
  id: string;
  tx_id: string;
  amount: number;
  resource_url: string;
  paid_at: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function truncateAddress(address: string): string {
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}

function microAlgoToAlgo(microAlgo: number): string {
  return (microAlgo / 1_000_000).toFixed(4);
}

// ── Copy button ───────────────────────────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard unavailable
    }
  }, [text]);

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="ml-1.5 text-muted-foreground hover:text-foreground transition-colors"
      title="Copy address"
    >
      {copied ? <Check className="h-3.5 w-3.5 text-green-500" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export function WalletWidget() {
  const { activeAddress, balance, isLoadingBalance, refreshBalance } = useWalletContext();
  const [payments, setPayments] = useState<X402PaymentRecord[]>([]);
  const [paymentsLoading, setPaymentsLoading] = useState(false);

  const isTestnet = (process.env.NEXT_PUBLIC_ALGORAND_NODE_URL ?? '').includes('testnet')
    || (process.env.NEXT_PUBLIC_ALGOD_SERVER ?? '').includes('testnet');

  const fetchPayments = useCallback(async () => {
    if (!activeAddress) return;
    setPaymentsLoading(true);
    try {
      const { data } = await api.get('/v1/x402/payment-history', {
        params: { buyer_address: activeAddress, limit: 5 },
      });
      setPayments((data?.data as X402PaymentRecord[]) ?? []);
    } catch {
      setPayments([]);
    } finally {
      setPaymentsLoading(false);
    }
  }, [activeAddress]);

  useEffect(() => {
    fetchPayments();
  }, [fetchPayments]);

  // ── Not connected ──────────────────────────────────────────────────────────

  if (!activeAddress) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground border border-border rounded-lg px-3 py-2">
        <Wallet className="h-4 w-4" />
        <span>No wallet connected</span>
      </div>
    );
  }

  // ── Connected ──────────────────────────────────────────────────────────────

  return (
    <div className="border border-border rounded-lg p-4 space-y-4 bg-card text-sm">
      {/* Address row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 font-mono text-xs text-foreground">
          <Wallet className="h-3.5 w-3.5 text-primary shrink-0" />
          <span title={activeAddress}>{truncateAddress(activeAddress)}</span>
          <CopyButton text={activeAddress} />
        </div>
        <a
          href={`https://${isTestnet ? 'testnet.' : ''}algoexplorer.io/address/${activeAddress}`}
          target="_blank"
          rel="noopener noreferrer"
          className="text-muted-foreground hover:text-primary transition-colors"
          title="View on AlgoExplorer"
        >
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
      </div>

      {/* Balance row */}
      <div className="flex items-center justify-between">
        <span className="text-muted-foreground">ALGO balance</span>
        <div className="flex items-center gap-2">
          {isLoadingBalance ? (
            <RefreshCw className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
          ) : balance ? (
            <span className="font-medium">{balance.algo_balance_algo} ALGO</span>
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
          <button
            type="button"
            onClick={refreshBalance}
            disabled={isLoadingBalance}
            className="text-muted-foreground hover:text-foreground disabled:opacity-40"
            title="Refresh balance"
          >
            <RefreshCw className="h-3 w-3" />
          </button>
        </div>
      </div>

      {/* Faucet button (testnet only) */}
      {isTestnet && (
        <a href="https://bank.testnet.algorand.network/" target="_blank" rel="noopener noreferrer">
          <Button
            variant="outline"
            size="sm"
            className="w-full text-xs h-8 border-primary/30 text-primary hover:bg-primary/10"
          >
            Get TestNet ALGO (Faucet)
            <ExternalLink className="ml-1.5 h-3 w-3" />
          </Button>
        </a>
      )}

      {/* x402 payment history */}
      {process.env.NEXT_PUBLIC_X402_ENABLED === 'true' && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>Recent x402 payments</span>
            <button
              type="button"
              onClick={fetchPayments}
              disabled={paymentsLoading}
              className="hover:text-foreground disabled:opacity-40"
            >
              <RefreshCw className={`h-3 w-3 ${paymentsLoading ? 'animate-spin' : ''}`} />
            </button>
          </div>

          {payments.length === 0 ? (
            <p className="text-xs text-muted-foreground italic">No payments yet</p>
          ) : (
            <ul className="space-y-1">
              {payments.map((p) => (
                <li key={p.id} className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground truncate max-w-[140px]" title={p.resource_url}>
                    {p.resource_url.replace(/^\/v1\//, '')}
                  </span>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <span className="font-medium">{microAlgoToAlgo(p.amount)} ALGO</span>
                    <a
                      href={`https://${isTestnet ? 'testnet.' : ''}algoexplorer.io/tx/${p.tx_id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-muted-foreground hover:text-primary"
                    >
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
