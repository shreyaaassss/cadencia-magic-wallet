import * as React from 'react';
import Link from 'next/link';
import { Play, Pause, ExternalLink } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from './ConfirmDialog';
import { formatDate } from '@/lib/utils';
import { ROUTES } from '@/lib/constants';

export interface AdminAgent {
  session_id: string;
  status: string;
  current_round: number;
  model: string;
  latency_ms: number;
  buyer: string;
  seller: string;
  started_at: string;
}

interface AgentMonitorRowProps {
  agent: AdminAgent;
  onPause: (sessionId: string) => void;
  onResume: (sessionId: string) => void;
  isLoading: boolean;
}

export function AgentMonitorRow({ agent, onPause, onResume, isLoading }: AgentMonitorRowProps) {
  const [action, setAction] = React.useState<'pause' | 'resume' | null>(null);

  const handleConfirm = () => {
    if (action === 'pause') onPause(agent.session_id);
    if (action === 'resume') onResume(agent.session_id);
    setAction(null);
  };

  const isRunning = agent.status === 'RUNNING';
  
  // Latency color
  const latencyColor = 
    agent.latency_ms === 0 ? 'text-muted-foreground' :
    agent.latency_ms < 500 ? 'text-green-700' :
    agent.latency_ms < 2000 ? 'text-amber-600' :
    'text-destructive';

  return (
    <>
      <div className="bg-card border border-border rounded-lg p-4">
        <div className="flex justify-between items-start mb-2">
          <div className="flex items-center gap-2">
            <div className={`h-2 w-2 rounded-full ${isRunning ? 'bg-green-500 animate-pulse' : 'bg-amber-500'}`} />
            <span className="font-mono text-xs text-primary">{agent.session_id}</span>
          </div>
          <span className={`text-xs font-mono font-medium ${latencyColor}`}>
            {agent.latency_ms > 0 ? `${agent.latency_ms}ms` : '--'}
          </span>
        </div>
        
        <p className="text-sm font-medium text-foreground mb-1 truncate">
          {agent.buyer} <span className="text-muted-foreground mx-1">&rarr;</span> {agent.seller}
        </p>
        
        <div className="flex items-center gap-3 text-xs text-muted-foreground mb-4">
          <span className="bg-muted px-1.5 py-0.5 rounded font-mono text-[10px]">{agent.model}</span>
          <span>Round {agent.current_round}</span>
          <span>&bull;</span>
          <span>Since {formatDate(agent.started_at)}</span>
        </div>
        
        <div className="flex gap-2">
          {isRunning ? (
            <Button
              size="sm"
              variant="outline"
              className="border-border text-foreground hover:bg-accent hover:border-muted-foreground text-xs px-2 py-1.5 h-auto flex-1 flex items-center justify-center gap-1 leading-none transition-all duration-200 hover:-translate-y-[1px]"
              onClick={() => setAction('pause')}
              disabled={isLoading}
            >
              <Pause className="h-3 w-3" /> Pause
            </Button>
          ) : (
            <Button
              size="sm"
              className="bg-primary text-primary-foreground hover:opacity-90 text-xs px-2 py-1.5 h-auto flex-1 flex items-center justify-center gap-1 leading-none transition-all duration-200 hover:-translate-y-[1px] hover:shadow-[0_4px_16px_hsl(var(--primary)/0.3)]"
              onClick={() => setAction('resume')}
              disabled={isLoading}
            >
              <Play className="h-3 w-3" /> Resume
            </Button>
          )}
          <Link href={`${ROUTES.NEGOTIATIONS}/${agent.session_id}`} target="_blank" className="flex-1">
            <Button 
              size="sm" 
              variant="outline" 
              className="w-full text-xs px-2 py-1.5 h-auto flex items-center justify-center gap-1 leading-none"
            >
              View <ExternalLink className="h-3 w-3" />
            </Button>
          </Link>
        </div>
      </div>

      <ConfirmDialog
        open={!!action}
        onOpenChange={(v) => !v && setAction(null)}
        title={action === 'pause' ? 'Pause Agent' : 'Resume Agent'}
        description={`Are you sure you want to ${action} the AI agent for session ${agent.session_id}?`}
        confirmLabel={action === 'pause' ? 'Pause' : 'Resume'}
        variant={action === 'pause' ? 'destructive' : 'default'}
        onConfirm={handleConfirm}
        isLoading={isLoading}
      />
    </>
  );
}
