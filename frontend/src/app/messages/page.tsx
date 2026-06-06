'use client';

import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { MessageSquare, Lock } from 'lucide-react';
import Link from 'next/link';

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

export default function MessagesPage() {
  const { data: threads = [], isLoading } = useQuery<Thread[]>({
    queryKey: ['threads'],
    queryFn: () => api.get('/v1/threads').then(r => r.data?.data || []),
  });

  return (
    <AppShell>
      <div className="space-y-6">
        <SectionHeader title="Messages" description="Conversations with your trading partners, scoped by deal." />

        {isLoading ? (
          <p className="text-sm text-muted-foreground py-8 text-center">Loading threads...</p>
        ) : threads.length === 0 ? (
          <EmptyState icon={MessageSquare} title="No conversations yet" description="Conversations are created automatically when you start a negotiation." />
        ) : (
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
