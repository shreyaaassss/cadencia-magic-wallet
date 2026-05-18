'use client';

/**
 * WalletWidget — displays Magic wallet info, ALGO balance, and x402 payment history.
 *
 * Shows:
 *   - Algorand address (truncated, copy-to-clipboard)
 *   - Live ALGO balance (fetched from Algorand node)
 *   - "Top Up" button linking to the Algorand testnet faucet
 *   - Last 5 x402 payment records
 */

import React, { useCallback, useEffect, useState } from 'react';
import { Copy, Check, ExternalLink, RefreshCw, Wallet } from 'lucide-react';
import { useMagic } from '@/context/MagicContext';
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
  if (address.length <= 12) return address;
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}

function microAlgoToAlgo(microAlgo: number): string {
  return (microAlgo / 1_000_000).toFixed(6);
}

// ── Sub-components ────────────────────────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard API not available
    }
  }, [text]);

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="ml-1.5 text-muted-foreground hover:text-foreground transition-colors"
      title="Copy address"
    >
      {copied ? (
        <Check className="h-3.5 w-3.5 text-green-500" />
      ) : (
        <Copy className="h-3.5 w-3.5" />
      )}
    </button>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export function WalletWidget() {
  const { walletAddress } = useMagic();
  const [balance, setBalance] = useState<number | null>(null);
  const [balanceLoading, setBalanceLoading] = useState(false);
  const [payments, setPayments] = useState<X402PaymentRecord[]>([]);
  const [paymentsLoading, setPaymentsLoading] = useState(false);

  const nodeUrl =
    process.env.NEXT_PUBLIC_ALGORAND_NODE_URL ?? 'https://testnet-api.algonode.cloud';

  const isTestnet = nodeUrl.includes('testnet');
  const faucetUrl = 'https://bank.testnet.algorand.network/';
  const topUpUrl = faucetUrl;

  // ── Fetch ALGO balance ──────────────────────────────────────────────────────

  const fetchBalance = useCallback(async () => {
    if (!walletAddress) return;
    setBalanceLoading(true);
    try {
      const response = await fetch(`${nodeUrl}/v2/accounts/${walletAddress}`, {
        headers: { Accept: 'application/json' },
      });
      if (response.ok) {
        const data = await response.json();
        setBalance(data.account?.amount ?? data.amount ?? null);
      }
    } catch {
      setBalance(null);
    } finally {
      setBalanceLoading(false);
    }
  }, [walletAddress, nodeUrl]);

  // ── Fetch payment history ───────────────────────────────────────────────────

  const fetchPayments = useCallback(async () => {
    if (!walletAddress) return;
    setPaymentsLoading(true);
    try {
      const { data } = await api.get('/x402/payment-history', {
        params: { buyer_address: walletAddress, limit: 5 },
      });
      setPayments((data?.data as X402PaymentRecord[]) ?? []);
    } catch {
      // Endpoint may not be available — silently skip
      setPayments([]);
    } finally {
      setPaymentsLoading(false);
    }
  }, [walletAddress]);

  useEffect(() => {
    fetchBalance();
    fetchPayments();
  }, [fetchBalance, fetchPayments]);

  // ── Not connected ──────────────────────────────────────────────────────────

  if (!walletAddress) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground border border-border rounded-lg px-3 py-2">
        <Wallet className="h-4 w-4" />
        <span>No Magic wallet connected</span>
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
          <span title={walletAddress}>{truncateAddress(walletAddress)}</span>
          <CopyButton text={walletAddress} />
        </div>
        <a
          href={`https://${isTestnet ? 'testnet.' : ''}algoexplorer.io/address/${walletAddress}`}
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
        <div className="text-muted-foreground">ALGO balance</div>
        <div className="flex items-center gap-2">
          {balanceLoading ? (
            <RefreshCw className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
          ) : balance !== null ? (
            <span className="font-medium">{microAlgoToAlgo(balance)} ALGO</span>
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
          <button
            type="button"
            onClick={fetchBalance}
            disabled={balanceLoading}
            className="text-muted-foreground hover:text-foreground disabled:opacity-40"
            title="Refresh balance"
          >
            <RefreshCw className="h-3 w-3" />
          </button>
        </div>
      </div>

      {/* Top Up button */}
      <a
        href={topUpUrl}
        target="_blank"
        rel="noopener noreferrer"
      >
        <Button
          variant="outline"
          size="sm"
          className="w-full text-xs h-8 border-primary/30 text-primary hover:bg-primary/10"
        >
          Get TestNet ALGO (Faucet)
          <ExternalLink className="ml-1.5 h-3 w-3" />
        </Button>
      </a>

      {/* Payment history */}
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
