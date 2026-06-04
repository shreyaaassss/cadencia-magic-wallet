import { cn } from '@/lib/utils';
import type { SessionStatus } from '@/types';

interface SessionStatusPillProps {
  status: SessionStatus;
  currentRound: number;
  maxRounds: number;
}

// Design.md signature colors — bold, high-contrast, unmistakably different
const statusConfig: Record<SessionStatus, { label: string; className: string; dotClass: string }> = {
  ACTIVE: {
    label: 'Active',
    // Primary near-black with white text — "in progress, important"
    className: 'bg-[#181d26] text-white border-[#181d26]',
    dotClass: 'bg-green-400 animate-pulse',
  },
  AGREED: {
    label: 'Agreed',
    // Signature forest green — positive outcome
    className: 'bg-[#0a2e0e] text-white border-[#0a2e0e]',
    dotClass: 'bg-green-300',
  },
  WALK_AWAY: {
    label: 'Not Selected',
    // Signature coral — another seller was chosen
    className: 'bg-[#aa2d00] text-white border-[#aa2d00]',
    dotClass: 'bg-orange-200',
  },
  TIMEOUT: {
    label: 'Timed Out',
    // Muted amber — ran out of time
    className: 'bg-amber-700 text-white border-amber-700',
    dotClass: 'bg-amber-300',
  },
  POLICY_BREACH: {
    label: 'Policy Breach',
    // Strong red — serious violation
    className: 'bg-red-700 text-white border-red-700',
    dotClass: 'bg-red-300',
  },
  FAILED: {
    label: 'Not Selected',
    // Darker muted — another seller was chosen
    className: 'bg-[#41454d] text-white border-[#41454d]',
    dotClass: 'bg-gray-300',
  },
  TERMINATED: {
    label: 'Terminated',
    className: 'bg-[#41454d] text-white border-[#41454d]',
    dotClass: 'bg-gray-300',
  },
  CLOSED_BY_BUYER: {
    label: 'Buyer Selected Other',
    className: 'bg-[#6b7280] text-white border-[#6b7280]',
    dotClass: 'bg-gray-300',
  },
};

export function SessionStatusPill({ status, currentRound, maxRounds }: SessionStatusPillProps) {
  const config = statusConfig[status] ?? statusConfig.TERMINATED;
  const roundText = `${currentRound}/${maxRounds}`;

  return (
    <span className={cn(
      'inline-flex items-center gap-1.5 border font-medium rounded-full px-3 py-1 text-xs tracking-wide',
      config.className
    )}>
      <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', config.dotClass)} />
      {config.label}
      <span className="opacity-60 font-normal">{roundText}</span>
    </span>
  );
}
