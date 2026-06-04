'use client';

import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Receipt, Hash, Globe, Calendar, ExternalLink } from 'lucide-react';

import { AppShell } from '@/components/layout/AppShell';
import { AuthGuard } from '@/components/shared/AuthGuard';
import { SectionHeader } from '@/components/shared/SectionHeader';
import { StatCard } from '@/components/shared/StatCard';
import { DataTable } from '@/components/shared/DataTable';
import { Input } from '@/components/ui/input';
import { api } from '@/lib/api';
import { formatDate } from '@/lib/utils';

// ─── Types ──────────────────────────────────────────────────────────────────
interface X402PaymentRecord {
  id: string;
  tx_id: string;
  amount: number;
  resource_url: string;
  paid_at: string;
}

// ─── Page ───────────────────────────────────────────────────────────────────
export default function PaymentHistoryPage() {
  const [fromDate, setFromDate] = React.useState('');
  const [toDate, setToDate] = React.useState('');

  // Build query params for date range filtering
  const queryParams = React.useMemo(() => {
    const params = new URLSearchParams();
    if (fromDate) params.set('from', fromDate);
    if (toDate) params.set('to', toDate);
    const qs = params.toString();
    return qs ? `?${qs}` : '';
  }, [fromDate, toDate]);

  const {
    data: payments = [],
    isLoading,
  } = useQuery<X402PaymentRecord[]>({
    queryKey: ['x402-payment-history', fromDate, toDate],
    queryFn: () =>
      api
        .get(`/v1/x402/payment-history${queryParams}`)
        .then((r) => r.data.data as X402PaymentRecord[]),
  });

  // ─── Summary stats ──────────────────────────────────────────────────────
  const totalTransactions = payments.length;
  const totalSpendMicro = payments.reduce((sum, p) => sum + p.amount, 0);
  const totalSpendAlgo = totalSpendMicro / 1_000_000;

  return (
    <AppShell>
      <AuthGuard>
        <div className="p-6">

          {/* Page Header */}
          <div className="mb-8">
            <h1 className="text-2xl font-semibold text-foreground">
              x402 Payment History
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              On-chain payment records for HTTP 402 metered API access.
            </p>
          </div>

          {/* Summary Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
            <StatCard
              label="Total Transactions"
              value={totalTransactions}
              icon={Hash}
              trend={{ value: 'all time', direction: 'neutral' }}
              isLoading={isLoading}
            />
            <StatCard
              label="Total Spend (ALGO)"
              value={totalSpendAlgo.toFixed(6)}
              icon={Receipt}
              trend={{ value: 'converted', direction: 'neutral' }}
              isLoading={isLoading}
            />
            <StatCard
              label="Total Spend (uALGO)"
              value={totalSpendMicro.toLocaleString()}
              icon={Receipt}
              trend={{ value: 'microALGO', direction: 'neutral' }}
              isLoading={isLoading}
            />
          </div>

          {/* Date Range Filter */}
          <div className="bg-card border border-border rounded-lg p-4 mb-6">
            <div className="flex flex-col sm:flex-row sm:items-end gap-4">
              <div className="flex items-center gap-2 text-sm text-muted-foreground shrink-0">
                <Calendar className="h-4 w-4" />
                <span className="font-medium text-foreground">Filter by date</span>
              </div>
              <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1 block">
                    From
                  </label>
                  <Input
                    type="date"
                    value={fromDate}
                    onChange={(e) => setFromDate(e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1 block">
                    To
                  </label>
                  <Input
                    type="date"
                    value={toDate}
                    onChange={(e) => setToDate(e.target.value)}
                  />
                </div>
              </div>
              {(fromDate || toDate) && (
                <button
                  onClick={() => {
                    setFromDate('');
                    setToDate('');
                  }}
                  className="text-xs text-primary hover:underline shrink-0"
                >
                  Clear
                </button>
              )}
            </div>
          </div>

          {/* Transaction Table */}
          <div>
            <SectionHeader title="Transactions" />
            <DataTable<X402PaymentRecord>
              columns={[
                {
                  key: 'paid_at',
                  label: 'Date',
                  sortable: true,
                  render: (v) => (
                    <span className="text-muted-foreground text-xs">
                      {formatDate(String(v))}
                    </span>
                  ),
                },
                {
                  key: 'tx_id',
                  label: 'Transaction ID',
                  render: (v) => {
                    const txId = String(v);
                    return (
                      <a
                        href={`https://testnet.algoexplorer.io/tx/${txId}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 font-mono text-xs text-primary hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {txId.length > 16
                          ? `${txId.slice(0, 8)}...${txId.slice(-8)}`
                          : txId}
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    );
                  },
                },
                {
                  key: 'resource_url',
                  label: 'Resource URL',
                  render: (v) => {
                    const url = String(v);
                    return (
                      <span
                        className="font-mono text-xs text-muted-foreground truncate block max-w-[260px]"
                        title={url}
                      >
                        {url}
                      </span>
                    );
                  },
                },
                {
                  key: 'amount',
                  label: 'Amount (uALGO)',
                  sortable: true,
                  render: (v) => (
                    <span className="font-medium text-foreground tabular-nums">
                      {Number(v).toLocaleString()}
                    </span>
                  ),
                },
              ]}
              data={payments}
              isLoading={isLoading}
              keyExtractor={(row) => row.id}
              emptyState={{
                icon: Globe,
                title: 'No payments yet',
                description:
                  'x402 payment records will appear here once your services process metered API requests.',
              }}
            />
          </div>
        </div>
      </AuthGuard>
    </AppShell>
  );
}
