'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  Play, CheckCircle2, Pause, List, Handshake,
  FileText, AlertTriangle, StopCircle,
} from 'lucide-react';

import { AppShell } from '@/components/layout/AppShell';
import { StatCard } from '@/components/shared/StatCard';
import { SectionHeader } from '@/components/shared/SectionHeader';
import { FilterChips } from '@/components/shared/FilterChips';
import { DateRangePicker } from '@/components/shared/DateRangePicker';
import { SessionStatusPill } from '@/components/shared/SessionStatusPill';
import { ConfirmDialog } from '@/components/shared/ConfirmDialog';
import { EmptyState } from '@/components/shared/EmptyState';
import { Button } from '@/components/ui/button';

import { useAuth } from '@/hooks/useAuth';
import { api } from '@/lib/api';
import { formatCurrency, formatDate, formatDateTime, cn } from '@/lib/utils';
import { ROUTES } from '@/lib/constants';
import type { NegotiationSession, SessionStatus } from '@/types';

const STATUS_FILTERS: Array<{ value: string; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'ACTIVE', label: 'Active' },
  { value: 'AGREED', label: 'Agreed' },
  { value: 'WALK_AWAY', label: 'Walk Away' },
  { value: 'TIMEOUT', label: 'Timeout' },
  { value: 'POLICY_BREACH', label: 'Policy Breach' },
  { value: 'FAILED', label: 'Failed' },
];

function getDateCutoff(range: string): Date | null {
  const now = new Date();
  switch (range) {
    case 'this-week': {
      const d = new Date(now);
      d.setDate(d.getDate() - 7);
      return d;
    }
    case 'this-month': {
      const d = new Date(now);
      d.setMonth(d.getMonth() - 1);
      return d;
    }
    case 'last-30': {
      const d = new Date(now);
      d.setDate(d.getDate() - 30);
      return d;
    }
    default:
      return null;
  }
}

export default function NegotiationsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { enterprise, isAdmin } = useAuth();
  const enterpriseId = enterprise?.id;

  const [statusFilter, setStatusFilter] = React.useState('all');
  const [dateRange, setDateRange] = React.useState('all');
  const [terminateTarget, setTerminateTarget] = React.useState<NegotiationSession | null>(null);

  // ─── Fetch all sessions (poll every 3s while any are ACTIVE) ─────────────────
  const { data: sessions = [], isLoading } = useQuery<NegotiationSession[]>({
    queryKey: ['sessions'],
    queryFn: () => api.get('/v1/sessions').then(r => r.data.data),
    refetchInterval: 3000,
  });

  // ─── Filter ─────────────────────────────────────────────────────────────────
  const filtered = React.useMemo(() => {
    let result = sessions;

    if (statusFilter !== 'all') {
      result = result.filter(s => s.status === statusFilter);
    }

    const cutoff = getDateCutoff(dateRange);
    if (cutoff) {
      result = result.filter(s => new Date(s.created_at) >= cutoff);
    }

    return result;
  }, [sessions, statusFilter, dateRange]);

  // ─── Group sessions by RFQ ───────────────────────────────────────────────────
  const groupedByRfq = React.useMemo(() => {
    const groups = new Map<string, { sessions: typeof filtered; earliest: string }>();
    for (const s of filtered) {
      const key = s.rfq_id;
      if (!groups.has(key)) {
        groups.set(key, { sessions: [], earliest: s.created_at });
      }
      const g = groups.get(key)!;
      g.sessions.push(s);
      if (new Date(s.created_at) < new Date(g.earliest)) g.earliest = s.created_at;
    }
    // Sort groups newest-first
    return Array.from(groups.entries()).sort(
      ([, a], [, b]) => new Date(b.earliest).getTime() - new Date(a.earliest).getTime()
    );
  }, [filtered]);

  // ─── Pagination (10 RFQ groups per page) ────────────────────────────────────
  const PAGE_SIZE = 10;
  const [page, setPage] = React.useState(1);
  const totalGroups = groupedByRfq.length;
  const totalPages = Math.max(1, Math.ceil(totalGroups / PAGE_SIZE));
  const pagedGroups = groupedByRfq.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  // Reset to page 1 when filters change
  React.useEffect(() => { setPage(1); }, [statusFilter, dateRange]);

  // ─── Stats ──────────────────────────────────────────────────────────────────
  const counts = React.useMemo(() => {
    const c: Record<string, number> = { ACTIVE: 0, AGREED: 0, WALK_AWAY: 0, TIMEOUT: 0, POLICY_BREACH: 0, FAILED: 0 };
    sessions.forEach(s => { c[s.status] = (c[s.status] || 0) + 1; });
    return c;
  }, [sessions]);

  const chipOptions = STATUS_FILTERS.map(f => ({
    ...f,
    count: f.value === 'all' ? sessions.length : counts[f.value] ?? 0,
  }));

  // ─── Terminate mutation ─────────────────────────────────────────────────────
  const terminateMutation = useMutation({
    mutationFn: (sessionId: string) => api.post(`/v1/sessions/${sessionId}/terminate`),
    onSuccess: () => {
      toast.success('Session terminated');
      setTerminateTarget(null);
      queryClient.invalidateQueries({ queryKey: ['sessions'] });
    },
    onError: () => {
      toast.error('Failed to terminate session');
    },
  });

  // ─── Party display ──────────────────────────────────────────────────────────
  const formatParties = (s: NegotiationSession) => {
    const isYouBuyer = s.buyer_enterprise_id === enterpriseId;
    const isYouSeller = s.seller_enterprise_id === enterpriseId;
    const left = isYouBuyer ? 'You' : (s.buyer_name ?? s.buyer_enterprise_id.slice(0, 8));
    const right = isYouSeller ? 'You' : (s.seller_name ?? s.seller_enterprise_id.slice(0, 8));
    return { left, right };
  };

  // ─── Row highlight class (works in light + dark) ───────────────────────────
  const getRowClass = (status: SessionStatus) => {
    switch (status) {
      case 'ACTIVE':    return 'border-l-[3px] border-l-green-500';
      case 'WALK_AWAY': return 'border-l-[3px] border-l-amber-500';
      case 'AGREED':    return 'border-l-[3px] border-l-green-400';
      default:          return 'border-l-[3px] border-l-transparent';
    }
  };

  // ─── Clear filters ──────────────────────────────────────────────────────────
  const clearFilters = () => {
    setStatusFilter('all');
    setDateRange('all');
  };

  const hasActiveFilters = statusFilter !== 'all' || dateRange !== 'all';

  // ─── Skeleton rows ──────────────────────────────────────────────────────────
  const skeletonWidths = ['w-20', 'w-40', 'w-24', 'w-16', 'w-20', 'w-16', 'w-20'];

  return (
    <AppShell>
      <div className="p-6">

        {/* Section 1: Stats */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <StatCard
            label="Active Sessions"
            value={counts.ACTIVE}
            icon={Play}
            isLoading={isLoading}
          />
          <StatCard
            label="Agreed Sessions"
            value={counts.AGREED}
            icon={CheckCircle2}
            isLoading={isLoading}
          />
          <StatCard
            label="Failed Sessions"
            value={counts.FAILED}
            icon={Pause}
            isLoading={isLoading}
          />
          <StatCard
            label="Total Sessions"
            value={sessions.length}
            icon={List}
            isLoading={isLoading}
          />
        </div>

        {/* Section 2: Filters */}
        <div className="bg-card border border-border rounded-lg p-6 mb-8">
          <SectionHeader title="Filters" />
          <div className="space-y-4">
            <FilterChips options={chipOptions} selected={statusFilter} onChange={setStatusFilter} />
            <div className="flex flex-wrap items-center gap-3">
              <DateRangePicker value={dateRange} onChange={setDateRange} />
              {hasActiveFilters && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={clearFilters}
                  className="text-muted-foreground hover:text-foreground hover:bg-accent"
                >
                  Clear Filters
                </Button>
              )}
            </div>
          </div>
        </div>

        {/* Section 3: Sessions Table */}
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-border flex items-center justify-between">
            <h3 className="text-base font-medium text-foreground">Sessions</h3>
            <span className="text-xs text-muted-foreground">{filtered.length} result{filtered.length !== 1 ? 's' : ''}</span>
          </div>

          <div className="w-full overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border">
                <th className="text-xs font-semibold text-foreground uppercase tracking-wider px-4 py-3 text-left bg-muted" style={{ width: '11%' }}>Session ID</th>
                <th className="text-xs font-semibold text-foreground uppercase tracking-wider px-4 py-3 text-left bg-muted" style={{ width: '32%' }}>Parties &amp; Product</th>
                <th className="text-xs font-semibold text-foreground uppercase tracking-wider px-4 py-3 text-left bg-muted" style={{ width: '15%' }}>Status</th>
                <th className="text-xs font-semibold text-foreground uppercase tracking-wider px-4 py-3 text-left bg-muted" style={{ width: '9%' }}>Rounds</th>
                <th className="text-xs font-semibold text-foreground uppercase tracking-wider px-4 py-3 text-left bg-muted" style={{ width: '13%' }}>Agreed Price</th>
                <th className="text-xs font-semibold text-foreground uppercase tracking-wider px-4 py-3 text-left bg-muted" style={{ width: '12%' }}>Created</th>
                <th className="text-xs font-semibold text-foreground uppercase tracking-wider px-4 py-3 text-right bg-muted" style={{ width: '8%' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i} className="border-b border-border last:border-0">
                    {skeletonWidths.map((w, j) => (
                      <td key={j} className="px-4 py-3">
                        <div className={cn('bg-muted animate-pulse rounded h-4', w)} />
                      </td>
                    ))}
                  </tr>
                ))
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={7}>
                    <EmptyState icon={Handshake} title="No negotiation sessions" description={hasActiveFilters ? 'Try adjusting your filters' : 'Sessions will appear here when negotiations start'} />
                  </td>
                </tr>
              ) : (
                pagedGroups.map(([rfqId, group], groupIndex) => {
                  const agreedCount = group.sessions.filter(s => s.status === 'AGREED').length;
                  const totalAgreed = group.sessions.reduce((sum, s) => sum + (s.agreed_price ?? 0), 0);
                  return (
                    <React.Fragment key={rfqId}>
                      {/* ── RFQ Group Header ── */}
                      <tr className={cn(groupIndex > 0 ? 'border-t-2 border-primary/20' : '')}>
                        <td colSpan={7} className="px-4 py-2.5 bg-muted/60">
                          <div className="flex items-center justify-between flex-wrap gap-2">
                            <div className="flex items-center gap-3">
                              <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">RFQ</span>
                              <span className="font-mono text-xs font-medium text-foreground">{rfqId.slice(0, 16)}…</span>
                              <span className="text-[10px] text-muted-foreground">Started {formatDateTime(group.earliest)}</span>
                            </div>
                            <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
                              <span>{group.sessions.length} session{group.sessions.length !== 1 ? 's' : ''}</span>
                              {agreedCount > 0 && (
                                <span className="text-green-600 dark:text-green-400 font-medium">
                                  {agreedCount} agreed · {formatCurrency(totalAgreed)}
                                </span>
                              )}
                            </div>
                          </div>
                        </td>
                      </tr>
                      {/* ── Sessions in this RFQ ── */}
                      {group.sessions.map((session) => {
                        const parties = formatParties(session);
                        return (
                          <tr
                            key={session.session_id}
                            className={cn(
                              'border-b border-border last:border-0 hover:bg-accent transition-colors cursor-pointer',
                              getRowClass(session.status)
                            )}
                            onClick={() => router.push(`${ROUTES.NEGOTIATIONS}/${session.session_id}`)}
                          >
                            <td className="px-4 py-3">
                              <span className="text-muted-foreground font-mono text-xs">{session.session_id.slice(0, 12)}</span>
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex flex-col gap-1.5">
                                <span className="text-sm font-medium text-foreground">
                                  {parties.left}
                                  <span className="text-muted-foreground mx-1">&harr;</span>
                                  {parties.right}
                                </span>
                                {session.product_context?.product && (
                                  <span
                                    className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium bg-primary/10 text-primary border border-primary/20 w-fit max-w-[240px]"
                                    title={session.product_context.product}
                                  >
                                    {session.product_context.product.length > 30
                                      ? session.product_context.product.slice(0, 30) + '…'
                                      : session.product_context.product}
                                  </span>
                                )}
                              </div>
                            </td>
                            <td className="px-4 py-3">
                              <SessionStatusPill
                                status={session.status}
                                currentRound={session.round_count}
                                maxRounds={20}
                              />
                            </td>
                            <td className="px-4 py-3">
                              <span className="text-xs font-medium text-foreground">{session.round_count}</span>
                            </td>
                            <td className="px-4 py-3">
                              <span className={cn('text-sm font-semibold', session.agreed_price ? 'text-foreground' : 'text-muted-foreground')}>
                                {session.agreed_price ? formatCurrency(session.agreed_price) : '\u2014'}
                              </span>
                            </td>
                            <td className="px-4 py-3">
                              <span className="text-muted-foreground text-xs">{formatDateTime(session.created_at)}</span>
                            </td>
                            <td className="px-4 py-3 text-right">
                              <div className="flex items-center justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                                {session.status === 'ACTIVE' && (
                                  <Button variant="ghost" size="sm" onClick={() => router.push(`${ROUTES.NEGOTIATIONS}/${session.session_id}`)} className="h-8 w-8 p-0 text-green-600 hover:bg-green-50 hover:text-green-600" title="Live Room">
                                    <Play className="h-4 w-4" />
                                  </Button>
                                )}
                                {(session.status === 'AGREED' || session.status === 'FAILED' || session.status === 'TIMEOUT') && (
                                  <Button variant="ghost" size="sm" onClick={() => router.push(`${ROUTES.NEGOTIATIONS}/${session.session_id}`)} className="h-8 w-8 p-0 text-muted-foreground hover:bg-accent hover:text-foreground" title="Details">
                                    <FileText className="h-4 w-4" />
                                  </Button>
                                )}
                                {session.status === 'WALK_AWAY' && (
                                  <Button variant="ghost" size="sm" onClick={() => router.push(`${ROUTES.NEGOTIATIONS}/${session.session_id}`)} className="h-8 w-8 p-0 text-amber-600 hover:bg-amber-50 hover:text-amber-600" title="Walk Away - Review">
                                    <AlertTriangle className="h-4 w-4" />
                                  </Button>
                                )}
                                {isAdmin && session.status === 'ACTIVE' && (
                                  <Button variant="ghost" size="sm" onClick={() => setTerminateTarget(session)} className="h-8 w-8 p-0 text-muted-foreground hover:bg-red-50 hover:text-destructive" title="Terminate">
                                    <StopCircle className="h-4 w-4" />
                                  </Button>
                                )}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </React.Fragment>
                  );
                })
              )}
            </tbody>
          </table>
          </div>

          {/* ── Pagination controls ─────────────────────────────────────── */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-2 py-3 border-t border-border">
              <span className="text-xs text-muted-foreground">
                Page {page} of {totalPages} · {totalGroups} RFQ{totalGroups !== 1 ? 's' : ''}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                >
                  ← Prev
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                >
                  Next →
                </Button>
              </div>
            </div>
          )}
        </div>

        {/* Terminate Confirm Dialog */}
        <ConfirmDialog
          open={!!terminateTarget}
          onOpenChange={(open) => { if (!open) setTerminateTarget(null); }}
          title="Terminate Session"
          description={`Terminate session ${terminateTarget?.session_id}? This will end the negotiation permanently. This action cannot be undone.`}
          confirmLabel="Terminate"
          variant="destructive"
          onConfirm={() => {
            if (terminateTarget) terminateMutation.mutate(terminateTarget.session_id);
          }}
          isLoading={terminateMutation.isPending}
        />
      </div>
    </AppShell>
  );
}
