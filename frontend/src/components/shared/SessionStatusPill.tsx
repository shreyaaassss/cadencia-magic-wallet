import { cn } from '@/lib/utils';
import type { SessionStatus } from '@/types';

interface SessionStatusPillProps {
  status: SessionStatus;
  currentRound: number;
  maxRounds: number;
}

const statusConfig: Record<SessionStatus, { label: string; className: string }> = {
  ACTIVE:       { label: 'Active',        className: 'bg-green-50 text-green-700 border-green-200' },
  AGREED:       { label: 'Agreed',        className: 'bg-green-50 text-green-700 border-green-200' },
  WALK_AWAY:    { label: 'Walk Away',     className: 'bg-amber-50 text-amber-700 border-amber-200' },
  TIMEOUT:      { label: 'Timed Out',     className: 'bg-amber-50 text-amber-700 border-amber-200' },
  POLICY_BREACH:{ label: 'Policy Breach', className: 'bg-red-50 text-red-700 border-red-200' },
  FAILED:       { label: 'Failed',        className: 'bg-red-50 text-red-700 border-red-200' },
  TERMINATED:   { label: 'Terminated',    className: 'bg-muted text-muted-foreground border-border' },
};

export function SessionStatusPill({ status, currentRound, maxRounds }: SessionStatusPillProps) {
  const config = statusConfig[status] ?? statusConfig.TERMINATED;
  const roundText = status === 'TERMINATED' ? 'Terminated' : `${currentRound}/${maxRounds}`;

  return (
    <span className={cn(
      'inline-flex items-center gap-1.5 border font-medium rounded-md px-2 py-0.5 text-xs',
      config.className
    )}>
      {config.label}
      <span className="opacity-60">{roundText}</span>
    </span>
  );
}
