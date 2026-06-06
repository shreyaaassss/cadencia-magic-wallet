'use client';

import * as React from 'react';
import { useParams } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Send, Lock, ArrowLeft } from 'lucide-react';
import Link from 'next/link';

import { AppShell } from '@/components/layout/AppShell';
import { useAuth } from '@/hooks/useAuth';
import { api } from '@/lib/api';
import { cn, formatDate } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

interface Message {
  id: string;
  sender_enterprise_id: string;
  body: string;
  is_system_generated: boolean;
  created_at: string;
}

interface Thread {
  id: string;
  subject: string | null;
  status: string;
  is_read_only: boolean;
}

export default function ThreadPage() {
  const params = useParams();
  const threadId = params.thread_id as string;
  const { enterprise } = useAuth();
  const queryClient = useQueryClient();
  const [newMessage, setNewMessage] = React.useState('');
  const messagesEndRef = React.useRef<HTMLDivElement>(null);

  const { data: messages = [], isLoading } = useQuery<Message[]>({
    queryKey: ['thread-messages', threadId],
    queryFn: () => api.get(`/v1/threads/${threadId}/messages`).then(r => r.data?.data || []),
    refetchInterval: 5000,  // poll every 5s
  });

  const { data: threads = [] } = useQuery<Thread[]>({
    queryKey: ['threads'],
    queryFn: () => api.get('/v1/threads').then(r => r.data?.data || []),
  });
  const thread = threads.find(t => t.id === threadId);
  const isReadOnly = thread?.status === 'CLOSED';

  const sendMutation = useMutation({
    mutationFn: (body: string) =>
      api.post(`/v1/threads/${threadId}/messages`, { body }),
    onSuccess: () => {
      setNewMessage('');
      queryClient.invalidateQueries({ queryKey: ['thread-messages', threadId] });
    },
  });

  React.useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = (e: React.FormEvent) => {
    e.preventDefault();
    if (newMessage.trim() && !isReadOnly) {
      sendMutation.mutate(newMessage.trim());
    }
  };

  const myEnterpriseId = enterprise?.id;

  return (
    <AppShell>
      <div className="flex flex-col h-[calc(100vh-120px)]">
        {/* Header */}
        <div className="flex items-center gap-3 pb-4 border-b border-border">
          <Link href="/messages" className="p-1.5 rounded hover:bg-accent">
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div className="flex-1">
            <h2 className="text-sm font-semibold text-foreground">
              {thread?.subject || 'Conversation'}
            </h2>
            {isReadOnly && (
              <p className="text-xs text-muted-foreground flex items-center gap-1">
                <Lock className="h-3 w-3" /> Deal completed — read-only
              </p>
            )}
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto py-4 space-y-3">
          {isLoading ? (
            <p className="text-sm text-muted-foreground text-center py-8">Loading messages...</p>
          ) : messages.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">No messages yet. Start the conversation.</p>
          ) : (
            messages.map(msg => {
              const isOwn = msg.sender_enterprise_id === myEnterpriseId;
              return (
                <div key={msg.id} className={cn('flex', isOwn ? 'justify-end' : 'justify-start')}>
                  <div className={cn(
                    'max-w-[70%] rounded-lg px-3 py-2 text-sm',
                    msg.is_system_generated
                      ? 'bg-muted/50 text-muted-foreground text-center max-w-full italic text-xs'
                      : isOwn
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-muted text-foreground'
                  )}>
                    <p className="whitespace-pre-wrap">{msg.body}</p>
                    <p className={cn('text-xs mt-1', isOwn ? 'text-primary-foreground/70' : 'text-muted-foreground')}>
                      {formatDate(msg.created_at)}
                    </p>
                  </div>
                </div>
              );
            })
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        {isReadOnly ? (
          <div className="py-3 text-center border-t border-border">
            <p className="text-xs text-muted-foreground flex items-center justify-center gap-1">
              <Lock className="h-3 w-3" /> This conversation is closed. Chat history is preserved for reference.
            </p>
          </div>
        ) : (
          <form onSubmit={handleSend} className="flex gap-2 pt-3 border-t border-border">
            <Input
              value={newMessage}
              onChange={e => setNewMessage(e.target.value)}
              placeholder="Type a message..."
              className="flex-1"
              maxLength={5000}
            />
            <Button type="submit" disabled={!newMessage.trim() || sendMutation.isPending} size="sm">
              <Send className="h-4 w-4" />
            </Button>
          </form>
        )}
      </div>
    </AppShell>
  );
}
