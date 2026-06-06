'use client';

import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Clock, TrendingUp, Zap, CheckCircle2 } from 'lucide-react';

import { AppShell } from '@/components/layout/AppShell';
import { SectionHeader } from '@/components/shared/SectionHeader';
import { StatCard } from '@/components/shared/StatCard';
import { EmptyState } from '@/components/shared/EmptyState';
import { api } from '@/lib/api';

export default function SLADashboardPage() {
  const { data: stats } = useQuery({
    queryKey: ['marketplace-stats'],
    queryFn: () => api.get('/v1/marketplace/stats').then(r => r.data?.data),
  });

  const { data: sessions = [] } = useQuery({
    queryKey: ['sla-sessions'],
    queryFn: () => api.get('/v1/sessions?limit=50').then(r => r.data?.data || []),
  });

  // Compute SLA metrics from session data
  const agreedSessions = sessions.filter((s: any) => s.status === 'AGREED');
  const avgRounds = agreedSessions.length > 0
    ? agreedSessions.reduce((sum: number, s: any) => sum + (s.round_count || 0), 0) / agreedSessions.length
    : 0;

  return (
    <AppShell>
      <div className="space-y-6">
        <SectionHeader
          title="SLA Tracking Dashboard"
          description="Monitor platform performance — RFQ to match, match to deal, deal to settlement timelines."
        />

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <StatCard icon={Zap} label="Active RFQs" value={stats?.total_buyers || 0} />
          <StatCard icon={TrendingUp} label="Deals Completed" value={stats?.negotiations_completed || 0} />
          <StatCard icon={Clock} label="Avg Rounds to Close" value={avgRounds.toFixed(1)} />
          <StatCard icon={CheckCircle2} label="Escrows Released" value={stats?.escrows_released || 0} />
        </div>

        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-foreground">Recent Deal Timelines</h3>
          {agreedSessions.length === 0 ? (
            <EmptyState icon={Clock} title="No completed deals yet" description="SLA timelines will appear here after negotiations complete." />
          ) : (
            <div className="border border-border rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-muted/50">
                  <tr>
                    <th className="text-left px-4 py-2 font-medium text-muted-foreground">Session</th>
                    <th className="text-right px-4 py-2 font-medium text-muted-foreground">Rounds</th>
                    <th className="text-right px-4 py-2 font-medium text-muted-foreground">Status</th>
                    <th className="text-right px-4 py-2 font-medium text-muted-foreground">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {agreedSessions.slice(0, 20).map((s: any) => (
                    <tr key={s.session_id || s.id} className="border-t border-border">
                      <td className="px-4 py-2 text-foreground font-mono text-xs">{(s.session_id || s.id || '').slice(0, 12)}...</td>
                      <td className="px-4 py-2 text-right text-foreground">{s.round_count || '—'}</td>
                      <td className="px-4 py-2 text-right">
                        <span className="text-xs bg-green-50 text-green-600 px-2 py-0.5 rounded-full">{s.status}</span>
                      </td>
                      <td className="px-4 py-2 text-right text-muted-foreground text-xs">{s.created_at ? new Date(s.created_at).toLocaleDateString() : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
