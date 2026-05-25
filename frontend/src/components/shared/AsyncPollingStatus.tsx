import { Loader2, Zap, CheckCircle2 } from 'lucide-react';
import { cn } from '@/lib/utils';

interface AsyncPollingStatusProps {
  status: 'DRAFT' | 'PARSED' | 'MATCHED' | 'CONFIRMED';
}

const statusConfig: Record<string, { icon: React.ElementType; label: string; className: string; animate?: string }> = {
  DRAFT:     { icon: Loader2,      label: 'Draft -- processing...',           className: 'text-muted-foreground',  animate: 'animate-spin' },
  PARSED:    { icon: Zap,          label: 'Parsed -- generating matches...',  className: 'text-amber-600',         animate: 'animate-pulse' },
  MATCHED:   { icon: CheckCircle2, label: 'Matches ready',                   className: 'text-green-700' },
  CONFIRMED: { icon: CheckCircle2, label: 'Negotiation started',             className: 'text-green-700' },
};

export function AsyncPollingStatus({ status }: AsyncPollingStatusProps) {
  const config = statusConfig[status] ?? statusConfig.DRAFT;
  const Icon = config.icon;

  return (
    <div className="flex items-center gap-2 py-2">
      <Icon className={cn('h-4 w-4', config.className, config.animate)} />
      <span className={cn('text-sm', config.className)}>{config.label}</span>
    </div>
  );
}
