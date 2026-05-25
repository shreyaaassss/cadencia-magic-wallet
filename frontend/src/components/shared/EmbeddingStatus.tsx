import { CheckCircle2, Loader2, AlertCircle, Clock, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { formatDateTime } from '@/lib/utils';
import { cn } from '@/lib/utils';

interface EmbeddingStatusProps {
  status: 'active' | 'queued' | 'failed' | 'outdated';
  lastUpdated?: string;
  onRefresh: () => void;
  isRefreshing: boolean;
}

const statusConfig: Record<string, { icon: React.ElementType; label: string; className: string; animate?: string }> = {
  active:   { icon: CheckCircle2, label: 'Active',      className: 'text-green-700' },
  queued:   { icon: Loader2,      label: 'Processing...', className: 'text-amber-600', animate: 'animate-spin' },
  failed:   { icon: AlertCircle,  label: 'Failed',       className: 'text-destructive' },
  outdated: { icon: Clock,        label: 'Outdated',     className: 'text-muted-foreground' },
};

export function EmbeddingStatus({ status, lastUpdated, onRefresh, isRefreshing }: EmbeddingStatusProps) {
  const config = statusConfig[status] ?? statusConfig.outdated;
  const Icon = config.icon;

  const subtextMap: Record<string, string> = {
    active: lastUpdated ? `Last updated: ${formatDateTime(lastUpdated)}` : 'Up to date',
    queued: 'Embedding recomputation in progress',
    failed: 'Update your profile to regenerate',
    outdated: lastUpdated ? `Last updated: ${formatDateTime(lastUpdated)}` : 'Never computed',
  };

  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-3">
        <div className={cn('rounded-md bg-muted p-2')}>
          <Icon className={cn('h-4 w-4', config.className, config.animate)} />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-foreground">Embedding</span>
            <span className={cn('text-sm font-medium', config.className)}>{config.label}</span>
          </div>
          <p className="text-xs text-muted-foreground">{subtextMap[status]}</p>
        </div>
      </div>
      <Button
        variant="ghost"
        size="sm"
        onClick={onRefresh}
        disabled={isRefreshing || status === 'queued'}
        className="text-primary hover:bg-secondary"
      >
        <RotateCcw className={cn('h-3.5 w-3.5 mr-1.5', isRefreshing && 'animate-spin')} />
        Refresh
      </Button>
    </div>
  );
}
