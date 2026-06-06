'use client';

import * as React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { MessageSquare, Lock, Plus } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { AppShell } from '@/components/layout/AppShell';
import { SectionHeader } from '@/components/shared/SectionHeader';
import { EmptyState } from '@/components/shared/EmptyState';
import { api } from '@/lib/api';
import { cn, formatDate } from '@/lib/utils';

interface Thread {
  id: string;
  subject: string | null;
  thread_type: string;
  status: string;
  session_id: string | null;
  escrow_id: string | null;
  is_read_only: boolean;
  created_at: string;
}

interface AgreedSession {
  session_id: string;
  rfq_id: string;
  buyer_enterprise_id: string;
  seller_enterprise_id: string;
  seller_name?: string;
  agreed_price: number | null;
  status: string;
}

export default function MessagesPage() {
  const router = useRouter();
  const queryClient = useQueryClient();

  const { data: threads = [], isLoading } = useQuery<Thread[]>({
    queryKey: ['threads'],
    queryFn: () => api.get('/v1/threads').then(r => r.data?.data || []),
  });

  // Fetch agreed sessions that don't have threads yet
  const { data: sessions = [] } = useQuery<AgreedSession[]>({
    queryKey: ['sessions-for-threads'],
    queryFn: () => api.get('/v1/sessions?status=AGREED&limit=50').then(r => {
      const items = r.data?.data || [];
      return Array.isArray(items) ? items : [];
    }),
  });

  const existingSessionIds = new Set(threads.map(t => t.session_id).filter(Boolean));
  const sessionsWithoutThreads = sessions.filter(
    s => s.status === 'AGREED' && s.session_id && !existingSessionIds.has(s.session_id)
  );

  const createThreadMutation = useMutation({
    mutationFn: async (session: AgreedSession) => {
      const res = await api.post('/v1/threads', {
        buyer_enterprise_id: session.buyer_enterprise_id,
        seller_enterprise_id: session.seller_enterprise_id,
        thread_type: 'DEAL',
        subject: `Deal agreed — coordinate delivery & logistics`,
        session_id: session.session_id,
        rfq_id: session.rfq_id,
      });
      return res.data?.data;
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['threads'] });
      queryClient.invalidateQueries({ queryKey: ['sessions-for-threads'] });
      if (data?.id) router.push(`/messages/${data.id}`);
    },
  });

  return (
    <AppShell>
      <div className="space-y-6">
        <SectionHeader title="Messages" description="Conversations with your trading partners, scoped by deal." />

        {/* Show "Start Conversation" for agreed deals without threads */}
        {sessionsWithoutThreads.length > 0 && (
          <div className="border border-dashed border-border rounded-lg p-4 space-y-2">
            <p className="text-sm font-medium text-foreground">Start a conversation with your deal partner</p>
            {sessionsWithoutThreads.map(s => (
              <button
                key={s.session_id}
                onClick={() => createThreadMutation.mutate(s)}
                disabled={createThreadMutation.isPending}
                className="flex items-center gap-2 w-full border border-border rounded-lg p-3 hover:bg-accent/50 transition-colors text-left"
              >
                <Plus className="h-4 w-4 text-primary" />
                <span className="text-sm text-foreground">
                  {s.seller_name || `Session ${s.session_id.slice(0, 8)}...`}
                  {s.agreed_price ? ` — Agreed at ${new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(s.agreed_price)}` : ''}
                </span>
              </button>
            ))}
          </div>
        )}

        {isLoading ? (
          <p className="text-sm text-muted-foreground py-8 text-center">Loading threads...</p>
        ) : threads.length === 0 && sessionsWithoutThreads.length === 0 ? (
          <EmptyState icon={MessageSquare} title="No conversations yet" description="Conversations are created automatically when a deal is agreed." />
        ) : threads.length === 0 ? null : (
          <div className="space-y-2">
            {threads.map(thread => (
              <Link
                key={thread.id}
                href={`/messages/${thread.id}`}
                className={cn(
                  'block border border-border rounded-lg p-4 hover:shadow-sm transition-shadow bg-card',
                  thread.is_read_only && 'opacity-70'
                )}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <MessageSquare className="h-4 w-4 text-muted-foreground" />
                    <span className="text-sm font-medium text-foreground">
                      {thread.subject || thread.thread_type.replace(/_/g, ' ')}
                    </span>
                    {thread.is_read_only && (
                      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
                        <Lock className="h-3 w-3" /> Read-only
                      </span>
                    )}
                  </div>
                  <span className={cn('text-xs px-2 py-0.5 rounded-full font-medium',
                    thread.status === 'OPEN' ? 'bg-green-50 text-green-600' :
                    thread.status === 'CLOSED' ? 'bg-muted text-muted-foreground' :
                    'bg-amber-50 text-amber-600'
                  )}>
                    {thread.status}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  {thread.session_id ? `Session: ${thread.session_id.slice(0, 8)}...` : ''}
                  {thread.created_at ? ` | ${formatDate(thread.created_at)}` : ''}
                </p>
              </Link>
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}
