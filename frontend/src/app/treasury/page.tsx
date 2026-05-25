'use client';

import { useQuery } from '@tanstack/react-query';
import {
  Banknote, TrendingUp, TrendingDown, AlertTriangle,
  RefreshCw, ArrowUpRight, ArrowDownRight, Minus,
} from 'lucide-react';

import { AppShell } from '@/components/layout/AppShell';
import { StatCard } from '@/components/shared/StatCard';
import { SectionHeader } from '@/components/shared/SectionHeader';
import { DataTable } from '@/components/shared/DataTable';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { EmptyState } from '@/components/shared/EmptyState';
import { api } from '@/lib/api';
import { formatDate } from '@/lib/utils';
import type {
  TreasuryDashboard, FXExposure, FXPositionItem, LiquidityForecast,
} from '@/types';

export default function TreasuryPage() {
  const { data: dashboard, isLoading: dashLoading } = useQuery({
    queryKey: ['treasury-dashboard'],
    queryFn: () => api.get('/v1/treasury/dashboard').then(r => r.data.data as TreasuryDashboard),
    refetchInterval: 60_000,
  });

  const { data: fxExposure, isLoading: fxLoading } = useQuery({
    queryKey: ['treasury-fx-exposure'],
    queryFn: () => api.get('/v1/treasury/fx-exposure').then(r => r.data.data as FXExposure),
  });

  const { data: forecast, isLoading: forecastLoading } = useQuery({
    queryKey: ['treasury-liquidity-forecast'],
    queryFn: () => api.get('/v1/treasury/liquidity-forecast').then(r => r.data.data as LiquidityForecast),
  });

  return (
    <AppShell>
      <div className="p-6">
        <div className="flex items-start justify-between mb-8">
          <div>
            <h1 className="text-2xl font-semibold text-foreground">Treasury Dashboard</h1>
            <p className="text-sm text-muted-foreground mt-1">
              Pool balances, FX exposure, and liquidity forecast
              {dashboard?.current_fx_rate?.updated_at && (
                <> &middot; FX updated: {formatDate(dashboard.current_fx_rate.updated_at)}</>
              )}
            </p>
          </div>
        </div>

        {/* Pool Balances */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            label="INR Pool"
            value={dashboard ? `₹${Number(dashboard.inr_pool_balance).toLocaleString('en-IN')}` : '—'}
            icon={Banknote}
            isLoading={dashLoading}
          />
          <StatCard
            label="USDC Pool"
            value={dashboard ? `$${Number(dashboard.usdc_pool_balance).toLocaleString()}` : '—'}
            icon={Banknote}
            isLoading={dashLoading}
          />
          <StatCard
            label="ALGO Pool"
            value={dashboard ? `${dashboard.algo_pool_balance_algo} ALGO` : '—'}
            icon={Banknote}
            isLoading={dashLoading}
          />
          <StatCard
            label="Total Value (INR)"
            value={dashboard ? `₹${Number(dashboard.total_value_inr).toLocaleString('en-IN')}` : '—'}
            icon={TrendingUp}
            isLoading={dashLoading}
          />
        </div>

        {/* FX Exposure */}
        <div className="mt-8">
          <SectionHeader
            title="Open FX Positions"
            description={fxExposure ? `${fxExposure.position_count} position(s) · PnL: ${fxExposure.total_unrealized_pnl}` : undefined}
          />
          {fxLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map(i => <div key={i} className="h-12 bg-muted animate-pulse rounded" />)}
            </div>
          ) : fxExposure && fxExposure.open_positions.length > 0 ? (
            <DataTable<FXPositionItem>
              columns={[
                { key: 'pair', label: 'Pair', render: (v) => <span className="font-mono text-sm text-foreground">{String(v)}</span> },
                { key: 'direction', label: 'Direction', render: (v) => <StatusBadge status={String(v)} /> },
                { key: 'notional', label: 'Notional', render: (v) => <span className="text-foreground">{String(v)}</span> },
                { key: 'entry_rate', label: 'Entry Rate', render: (v) => <span className="text-muted-foreground">{String(v)}</span> },
                { key: 'current_rate', label: 'Current Rate', render: (v) => <span className="text-foreground">{String(v)}</span> },
                {
                  key: 'unrealized_pnl', label: 'Unrealized PnL',
                  render: (v) => {
                    const pnl = Number(v);
                    const color = pnl > 0 ? 'text-green-600' : pnl < 0 ? 'text-red-500' : 'text-muted-foreground';
                    const Icon = pnl > 0 ? ArrowUpRight : pnl < 0 ? ArrowDownRight : Minus;
                    return (
                      <span className={`inline-flex items-center gap-1 ${color}`}>
                        <Icon className="h-3 w-3" />{String(v)}
                      </span>
                    );
                  },
                },
              ]}
              data={fxExposure.open_positions}
              keyExtractor={(row) => row.position_id}
              emptyState={{ icon: TrendingUp, title: 'No open FX positions' }}
            />
          ) : (
            <EmptyState icon={TrendingUp} title="No open FX positions" description="FX positions will appear when trades involve cross-currency settlement" />
          )}
        </div>

        {/* Liquidity Forecast */}
        <div className="mt-8">
          <SectionHeader
            title="30-Day Liquidity Forecast"
            description={forecast ? `Runway: ${forecast.runway_days} days · Daily burn: ₹${Number(forecast.estimated_daily_burn_inr).toLocaleString('en-IN')}` : undefined}
          />

          {forecast?.alert && (
            <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-600 mb-4">
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
              <span>{forecast.alert}</span>
            </div>
          )}

          {forecastLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map(i => <div key={i} className="h-8 bg-muted animate-pulse rounded" />)}
            </div>
          ) : forecast && forecast.forecast.length > 0 ? (
            <div className="bg-card border border-border rounded-lg overflow-hidden">
              <div className="grid grid-cols-3 px-4 py-2 border-b border-border text-xs font-medium text-muted-foreground uppercase tracking-wide">
                <span>Date</span>
                <span className="text-right">INR Balance</span>
                <span className="text-right">USDC Balance</span>
              </div>
              {forecast.forecast.slice(0, 14).map((day, i) => (
                <div key={day.date} className={`grid grid-cols-3 px-4 py-2 text-sm ${i < forecast.forecast.length - 1 ? 'border-b border-border' : ''}`}>
                  <span className="text-foreground">{formatDate(day.date)}</span>
                  <span className="text-right text-foreground">₹{Number(day.projected_inr_balance).toLocaleString('en-IN')}</span>
                  <span className="text-right text-foreground">${Number(day.projected_usdc_balance).toLocaleString()}</span>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState icon={Banknote} title="No forecast data" description="Liquidity forecast requires at least 7 days of transaction history" />
          )}
        </div>
      </div>
    </AppShell>
  );
}
