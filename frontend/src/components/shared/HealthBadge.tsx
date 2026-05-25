import { cn } from '@/lib/utils';

interface HealthBadgeProps {
  status: 'healthy' | 'degraded' | 'down' | 'unknown';
  showLabel?: boolean;
  size?: 'sm' | 'md';
}

const config: Record<string, { label: string; dotClass: string; textClass: string; ringClass: string }> = {
  healthy:  { label: 'Operational', dotClass: 'bg-green-500',          textClass: 'text-green-700',          ringClass: 'ring-2 ring-green-500/30 animate-pulse' },
  degraded: { label: 'Degraded',    dotClass: 'bg-amber-500',          textClass: 'text-amber-600',          ringClass: '' },
  down:     { label: 'Down',        dotClass: 'bg-destructive',        textClass: 'text-destructive',        ringClass: '' },
  unknown:  { label: 'Unknown',     dotClass: 'bg-muted-foreground',   textClass: 'text-muted-foreground',   ringClass: '' },
};

export function HealthBadge({ status, showLabel = true, size = 'sm' }: HealthBadgeProps) {
  const c = config[status] ?? config.unknown;
  const dotSize = size === 'sm' ? 'h-2 w-2' : 'h-2.5 w-2.5';

  return (
    <div className="flex items-center gap-1.5">
      <span className={cn('rounded-full shrink-0', dotSize, c.dotClass, status === 'healthy' && c.ringClass)} />
      {showLabel && (
        <span className={cn('text-xs', c.textClass)}>{c.label}</span>
      )}
    </div>
  );
}
