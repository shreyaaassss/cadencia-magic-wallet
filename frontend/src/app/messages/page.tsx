'use client';

import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { MessageSquare, Lock, ChevronDown, ChevronRight } from 'lucide-react';
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

function ThreadCard({ thread }: { thread: Thread }) {
  const isOpen = thread.status === 'OPEN';
  return (
    <Link
      href={`/messages/${thread.id}`}
      className={cn(
        'block border rounded-lg p-4 hover:shadow-sm transition-all',
        isOpen
          ? 'border-border bg-card hover:border-primary/30'
          : 'border-border/50 bg-card/50 opacity-75 hover:opacity-90'
      )}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <MessageSquare className={cn('h-4 w-4 flex-shrink-0', isOpen ? 'text-primary' : 'text-muted-foreground')} />
          <span className="text-sm font-medium text-foreground truncate">
            {thread.subject || thread.thread_type.replace(/_/g, ' ')}
          </span>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0 ml-2">
          {!isOpen && (
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
              <Lock className="h-3 w-3" /> Read-only
            </span>
          )}
          <span className={cn('text-xs px-2 py-0.5 rounded-full font-medium',
            isOpen ? 'bg-green-500/10 text-green-500' :
            'bg-muted text-muted-foreground'
          )}>
            {isOpen ? 'Active' : 'Closed'}
          </span>
        </div>
      </div>
      <p className="text-xs text-muted-foreground mt-1.5">
        {thread.session_id ? `Session: ${thread.session_id.slice(0, 8)}...` : ''}
        {thread.created_at ? ` | ${formatDate(thread.created_at)}` : ''}
      </p>
    </Link>
  );
}

export default function MessagesPage() {
  const [historyOpen, setHistoryOpen] = React.useState(false);

  const { data: threads = [], isLoading } = useQuery<Thread[]>({
    queryKey: ['threads'],
    queryFn: () => api.get('/v1/threads').then(r => r.data?.data || []),
    refetchInterval: 10000,
  });

  const activeThreads = threads.filter(t => t.status === 'OPEN');
  const closedThreads = threads.filter(t => t.status !== 'OPEN');

  return (
    <AppShell>
      <div className="space-y-6">
        <SectionHeader title="Messages" description="Conversations with your trading partners, scoped by deal." />

        {isLoading ? (
          <p className="text-sm text-muted-foreground py-8 text-center">Loading conversations...</p>
        ) : activeThreads.length === 0 && closedThreads.length === 0 ? (
          <EmptyState
            icon={MessageSquare}
            title="No conversations yet"
            description="Conversations are created automatically when a deal is agreed between you and a trading partner."
          />
        ) : (
          <>
            {/* Active Conversations */}
            {activeThreads.length > 0 ? (
              <div className="space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground px-1">
                  Active Conversations ({activeThreads.length})
                </h3>
                {activeThreads.map(thread => (
                  <ThreadCard key={thread.id} thread={thread} />
                ))}
              </div>
            ) : closedThreads.length > 0 ? (
              <div className="border border-dashed border-border rounded-lg p-6 text-center">
                <MessageSquare className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
                <p className="text-sm text-muted-foreground">No active conversations. Past conversations are in Chat History below.</p>
              </div>
            ) : null}

            {/* Chat History — collapsible */}
            {closedThreads.length > 0 && (
              <div className="border border-border/50 rounded-lg overflow-hidden">
                <button
                  onClick={() => setHistoryOpen(!historyOpen)}
                  className="w-full flex items-center justify-between px-4 py-3 bg-muted/30 hover:bg-muted/50 transition-colors"
                >
                  <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Chat History ({closedThreads.length})
                  </span>
                  {historyOpen
                    ? <ChevronDown className="h-4 w-4 text-muted-foreground" />
                    : <ChevronRight className="h-4 w-4 text-muted-foreground" />
                  }
                </button>
                {historyOpen && (
                  <div className="p-2 space-y-2">
                    {closedThreads.map(thread => (
                      <ThreadCard key={thread.id} thread={thread} />
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}
