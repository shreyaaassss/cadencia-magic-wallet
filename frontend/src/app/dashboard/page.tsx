'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  FileText, Landmark, Handshake, BarChart3, ArrowRight,
  ExternalLink, Database, Layers, Link as LinkIcon, Brain,
  BookOpen, CheckCircle2, XCircle, PauseCircle, X,
} from 'lucide-react';

import { AppShell } from '@/components/layout/AppShell';
import { StatCard } from '@/components/shared/StatCard';
import { SectionHeader } from '@/components/shared/SectionHeader';
import { DataTable } from '@/components/shared/DataTable';
import { HealthBadge } from '@/components/shared/HealthBadge';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { useAuth } from '@/hooks/useAuth';
import { useHealthStatus } from '@/hooks/useHealthStatus';
import { api } from '@/lib/api';
import { formatCurrency, formatDate, formatDateTime } from '@/lib/utils';
import { ROUTES } from '@/lib/constants';
import type { RFQ, NegotiationSession, Escrow } from '@/types';

const TRADE_ROLE_LABELS: Record<string, string> = {
  BUYER: 'Buyer',
  SELLER: 'Seller',
  BOTH: 'Buyer & Seller',
};

const SERVICE_META: { key: string; label: string; icon: React.ElementType }[] = [
  { key: 'database', label: 'Database', icon: Database },
  { key: 'redis',    label: 'Redis',    icon: Layers },
  { key: 'algorand', label: 'Algorand', icon: LinkIcon },
  { key: 'llm',      label: 'LLM',      icon: Brain },
];

export default function DashboardPage() {
  const router = useRouter();
  const { user, enterprise } = useAuth();
  const [vaultOpen, setVaultOpen] = useState(false);
  const { status: healthOverall } = useHealthStatus();

  // Health detail
  const { data: healthData } = useQuery({
    queryKey: ['health'],
    queryFn: () => api.get('/health').then(r => r.data.data),
    refetchInterval: 30_000,
    staleTime: 25_000,
  });

  // RFQs — fetch from list endpoint (buyer-only — skip for sellers)
  const { isBuyer } = useAuth();
  const { data: rfqs = [], isLoading: rfqsLoading } = useQuery({
    queryKey: ['rfqs'],
    queryFn: () => api.get('/v1/marketplace/rfqs?limit=5').then(r => r.data.data as RFQ[]),
    enabled: isBuyer,
  });

  // Sessions — fetch from list endpoint
  const { data: sessions = [], isLoading: sessionsLoading } = useQuery({
    queryKey: ['sessions'],
    queryFn: () => api.get('/v1/sessions?limit=5').then(r => r.data.data as NegotiationSession[]),
  });

  // Escrows — fetch from list endpoint
  const { data: escrows = [], isLoading: escrowsLoading } = useQuery({
    queryKey: ['escrows'],
    queryFn: () => api.get('/v1/escrow?limit=5').then(r => r.data.data as Escrow[]),
  });

  // Negotiation vault stats
  const { data: vaultStats, isLoading: vaultLoading } = useQuery({
    queryKey: ['vault-stats', enterprise?.id],
    queryFn: () =>
      api.get(`/v1/negotiation-insights/${enterprise?.id}/stats`).then(r => r.data.data),
    enabled: !!enterprise?.id,
    staleTime: 30_000,
  });

  // Admin stats (if admin)
  const { data: adminStats } = useQuery({
    queryKey: ['admin-stats'],
    queryFn: () => api.get('/v1/admin/stats').then(r => r.data.data),
    enabled: user?.role === 'ADMIN',
  });

  // Stats
  const anyLoading = rfqsLoading || sessionsLoading || escrowsLoading;
  const activeRfqs = rfqs.filter(r => r.status === 'MATCHED' || r.status === 'PARSED').length;
  const pendingEscrows = escrows.filter(e => e.status === 'DEPLOYED' || e.status === 'FUNDED').length;
  const agreedSessions = sessions.filter(s => s.status === 'AGREED').length;
  const totalTrades = adminStats?.total_escrow_value ?? escrows.length;

  // Activity feed
  type ActivityItem = { type: 'rfq' | 'session' | 'escrow'; id: string; label: string; desc: string; status: string; date: string };
  const activityItems: ActivityItem[] = [
    ...rfqs.map(r => ({ type: 'rfq' as const, id: r.id, label: `RFQ ${r.id.slice(0, 8)}`, desc: r.raw_text.length > 40 ? r.raw_text.slice(0, 40) + '...' : r.raw_text, status: r.status, date: r.created_at })),
    ...sessions.map(s => ({ type: 'session' as const, id: s.session_id, label: `Session ${s.session_id.slice(0, 8)}`, desc: `${s.buyer_name ?? s.buyer_enterprise_id.slice(0, 8)} vs ${s.seller_name ?? s.seller_enterprise_id.slice(0, 8)}`, status: s.status, date: s.created_at })),
    ...escrows.map(e => ({ type: 'escrow' as const, id: e.escrow_id, label: `Escrow ${e.escrow_id.slice(0, 8)}`, desc: `${e.amount_algo} ALGO`, status: e.status, date: e.created_at })),
  ].sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime()).slice(0, 5);

  const activityIcons: Record<string, React.ElementType> = {
    rfq: FileText,
    session: Handshake,
    escrow: Landmark,
  };

  return (
    <AppShell>
      <div className="p-6">
        {/* Section 1: Page Header */}
        <div className="flex items-start justify-between flex-col sm:flex-row gap-4 mb-8">
          <div>
            <p className="text-sm text-muted-foreground">Welcome back,</p>
            <h1 className="text-2xl font-semibold text-foreground">
              {user?.full_name ?? 'Welcome back'}
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              {enterprise?.legal_name}
              {enterprise?.trade_role && (
                <>
                  {' \u00B7 '}
                  {TRADE_ROLE_LABELS[enterprise.trade_role] ?? enterprise.trade_role}
                </>
              )}
              {' \u00B7 '}
              {formatDate(new Date().toISOString())}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {isBuyer && (
              <a
                href="https://3.111.151.59.nip.io"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground shadow-sm hover:bg-primary/90 transition-colors"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                Buy Credits
              </a>
            )}
            <HealthBadge status={healthOverall} size="md" />
          </div>
        </div>

        {/* Section 2: Stat Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
          <StatCard
            label="Active RFQs"
            value={activeRfqs}
            icon={FileText}
            trend={{ value: 'current', direction: 'neutral' }}
            isLoading={anyLoading}
            onClick={() => router.push(ROUTES.MARKETPLACE)}
          />
          <StatCard
            label="Pending Escrows"
            value={pendingEscrows}
            icon={Landmark}
            trend={{ value: 'current', direction: 'neutral' }}
            isLoading={anyLoading}
            onClick={() => router.push(ROUTES.ESCROW)}
          />
          <StatCard
            label="Agreed Sessions"
            value={agreedSessions}
            icon={Handshake}
            trend={{ value: 'current', direction: 'neutral' }}
            isLoading={anyLoading}
            onClick={() => router.push(ROUTES.NEGOTIATIONS)}
          />
          <StatCard
            label="Total Trades"
            value={totalTrades}
            icon={BarChart3}
            trend={{ value: 'current', direction: 'neutral' }}
            isLoading={anyLoading}
          />
          <StatCard
            label="Negotiation Vault"
            value={vaultStats?.total_in_vault ?? 0}
            icon={BookOpen}
            trend={{ value: 'deals stored', direction: 'neutral' }}
            isLoading={vaultLoading}
            onClick={() => setVaultOpen(true)}
          />
        </div>

        {/* Vault modal */}
        {vaultOpen && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
            onClick={() => setVaultOpen(false)}
          >
            <div
              className="relative bg-background border border-border rounded-xl shadow-2xl w-full max-w-md mx-4 p-6"
              onClick={e => e.stopPropagation()}
            >
              <button
                onClick={() => setVaultOpen(false)}
                className="absolute top-4 right-4 text-muted-foreground hover:text-foreground transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
              <div className="flex items-center gap-2 mb-1">
                <BookOpen className="h-5 w-5 text-primary" />
                <h2 className="text-base font-semibold text-foreground">Negotiation Memory Vault</h2>
              </div>
              <p className="text-xs text-muted-foreground mb-5">
                Every completed negotiation is privately stored in your vault.
                Your AI agent reads this history to personalise each new deal.
              </p>

              <div className="grid grid-cols-2 gap-3 mb-5">
                {/* As Buyer */}
                <div className="rounded-lg border border-border bg-muted/30 p-4">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-3">As Buyer</p>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5 text-sm text-foreground">
                        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" /> Agreed
                      </span>
                      <span className="text-sm font-semibold text-foreground">
                        {vaultStats?.as_buyer?.agreed ?? 0}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5 text-sm text-foreground">
                        <XCircle className="h-3.5 w-3.5 text-red-400" /> Rejected
                      </span>
                      <span className="text-sm font-semibold text-foreground">
                        {vaultStats?.as_buyer?.rejected ?? 0}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5 text-sm text-foreground">
                        <PauseCircle className="h-3.5 w-3.5 text-amber-400" /> Stalled
                      </span>
                      <span className="text-sm font-semibold text-foreground">
                        {vaultStats?.as_buyer?.stalled ?? 0}
                      </span>
                    </div>
                    <div className="border-t border-border pt-2 flex items-center justify-between">
                      <span className="text-xs text-muted-foreground">Total</span>
                      <span className="text-xs font-semibold text-foreground">
                        {vaultStats?.as_buyer?.total ?? 0}
                      </span>
                    </div>
                  </div>
                </div>

                {/* As Seller */}
                <div className="rounded-lg border border-border bg-muted/30 p-4">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-3">As Seller</p>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5 text-sm text-foreground">
                        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" /> Agreed
                      </span>
                      <span className="text-sm font-semibold text-foreground">
                        {vaultStats?.as_seller?.agreed ?? 0}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5 text-sm text-foreground">
                        <XCircle className="h-3.5 w-3.5 text-red-400" /> Rejected
                      </span>
                      <span className="text-sm font-semibold text-foreground">
                        {vaultStats?.as_seller?.rejected ?? 0}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5 text-sm text-foreground">
                        <PauseCircle className="h-3.5 w-3.5 text-amber-400" /> Stalled
                      </span>
                      <span className="text-sm font-semibold text-foreground">
                        {vaultStats?.as_seller?.stalled ?? 0}
                      </span>
                    </div>
                    <div className="border-t border-border pt-2 flex items-center justify-between">
                      <span className="text-xs text-muted-foreground">Total</span>
                      <span className="text-xs font-semibold text-foreground">
                        {vaultStats?.as_seller?.total ?? 0}
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              <div className="rounded-lg bg-primary/5 border border-primary/20 px-4 py-3 text-xs text-muted-foreground">
                🔒 Records are stored privately per enterprise — never shared with counterparties.
                Your AI agent uses this history to anchor prices and calibrate concessions.
              </div>
            </div>
          </div>
        )}

        {/* Section 3: Recent RFQs + Active Sessions */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-8">
          {/* Recent RFQs */}
          <div>
            <SectionHeader
              title="Recent RFQs"
              action={{ label: 'View all', icon: ArrowRight, onClick: () => router.push(ROUTES.MARKETPLACE) }}
            />
            <DataTable<RFQ>
              columns={[
                { key: 'id', label: 'RFQ ID', render: (v) => <span className="text-primary font-mono text-xs">{String(v).slice(0, 8)}</span> },
                { key: 'raw_text', label: 'Description', render: (v) => { const s = String(v); return <span className="text-foreground">{s.length > 40 ? s.slice(0, 40) + '...' : s}</span>; } },
                { key: 'status', label: 'Status', render: (v) => <StatusBadge status={String(v)} /> },
                { key: 'created_at', label: 'Date', sortable: true, render: (v) => <span className="text-muted-foreground text-xs">{formatDate(String(v))}</span> },
              ]}
              data={rfqs}
              isLoading={rfqsLoading}
              keyExtractor={(row) => row.id}
              onRowClick={() => router.push(ROUTES.MARKETPLACE)}
              emptyState={{ icon: FileText, title: 'No RFQs yet', description: 'Create your first RFQ in the Marketplace' }}
            />
          </div>

          {/* Active Sessions */}
          <div>
            <SectionHeader
              title="Negotiation Sessions"
              action={{ label: 'View all', icon: ArrowRight, onClick: () => router.push(ROUTES.NEGOTIATIONS) }}
            />
            <DataTable<NegotiationSession>
              columns={[
                { key: 'session_id', label: 'Session', render: (v) => <span className="text-primary font-mono text-xs">{String(v).slice(0, 8)}</span> },
                { key: 'buyer_enterprise_id', label: 'Parties', render: (_v, row) => <span className="text-sm text-foreground">{row.buyer_name ?? row.buyer_enterprise_id.slice(0, 8)} &rarr; {row.seller_name ?? row.seller_enterprise_id.slice(0, 8)}</span> },
                { key: 'status', label: 'Status', render: (v) => <StatusBadge status={String(v)} /> },
                { key: 'round_count', label: 'Round', render: (_v, row) => <span className="text-muted-foreground">{row.round_count}</span> },
                { key: 'created_at', label: 'Date', sortable: true, render: (v) => <span className="text-muted-foreground text-xs">{formatDate(String(v))}</span> },
              ]}
              data={sessions}
              isLoading={sessionsLoading}
              keyExtractor={(row) => row.session_id}
              onRowClick={(row) => router.push(`${ROUTES.NEGOTIATIONS}/${row.session_id}`)}
              emptyState={{ icon: Handshake, title: 'No sessions yet' }}
            />
          </div>
        </div>

        {/* Section 4: Escrow Activity */}
        <div className="mt-6">
          <SectionHeader
            title="Escrow Activity"
            action={{ label: 'View all', icon: ArrowRight, onClick: () => router.push(ROUTES.ESCROW) }}
          />
          <DataTable<Escrow>
            columns={[
              { key: 'escrow_id', label: 'Escrow ID', render: (v) => <span className="text-primary font-mono text-xs">{String(v).slice(0, 8)}</span> },
              { key: 'buyer_name', label: 'Parties', render: (_v, row) => <span className="text-sm text-foreground">{row.buyer_name ?? '—'} &rarr; {row.seller_name ?? '—'}</span> },
              { key: 'amount_algo', label: 'Amount', render: (v) => <span className="font-medium">{Number(v)} ALGO</span> },
              { key: 'status', label: 'Status', render: (v) => <StatusBadge status={String(v)} /> },
              {
                key: 'deploy_tx_id', label: 'Blockchain TX',
                render: (v) => {
                  if (!v) return <span className="text-muted-foreground">{'\u2014'}</span>;
                  const txId = String(v);
                  return (
                    <a
                      href={`https://testnet.algoexplorer.io/tx/${txId}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 font-mono text-xs text-muted-foreground hover:text-foreground transition-colors"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {txId.length > 12 ? txId.slice(0, 12) + '...' : txId}
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  );
                },
              },
              { key: 'created_at', label: 'Date', sortable: true, render: (v) => <span className="text-muted-foreground text-xs">{formatDate(String(v))}</span> },
            ]}
            data={escrows}
            isLoading={escrowsLoading}
            keyExtractor={(row) => row.escrow_id}
            emptyState={{ icon: Landmark, title: 'No escrow activity' }}
          />
        </div>

        {/* Section 5: Recent Activity Feed */}
        {!anyLoading && activityItems.length > 0 && (
          <div className="mt-6">
            <SectionHeader title="Recent Activity" />
            <div className="bg-card border border-border rounded-lg overflow-hidden">
              {activityItems.map((item, idx) => {
                const AIcon = activityIcons[item.type];
                return (
                  <div
                    key={item.id}
                    className={`flex items-center gap-4 px-4 py-3 ${idx < activityItems.length - 1 ? 'border-b border-border' : ''}`}
                  >
                    <div className="bg-muted rounded-md p-2 shrink-0">
                      <AIcon className="h-4 w-4 text-primary" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-foreground truncate">
                        {item.label}
                        <span className="text-muted-foreground"> — {item.desc}</span>
                      </p>
                      <p className="text-xs text-muted-foreground">{formatDate(item.date)}</p>
                    </div>
                    <StatusBadge status={item.status} />
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Section 6: System Health Detail */}
        {healthData && (
          <div className="mt-6">
            <SectionHeader
              title="System Health"
              description={`Last checked: ${formatDateTime(healthData.timestamp)}`}
            />
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
              {SERVICE_META.map(({ key, label, icon: SIcon }) => {
                const svcStatus = healthData.services?.[key] ?? 'unknown';
                return (
                  <div key={key} className="bg-card border border-border rounded-lg p-4">
                    <SIcon className="h-5 w-5 text-muted-foreground mb-2" />
                    <p className="text-sm font-medium text-foreground mb-1">{label}</p>
                    <HealthBadge
                      status={svcStatus as 'healthy' | 'degraded' | 'down' | 'unknown'}
                      size="sm"
                    />
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
