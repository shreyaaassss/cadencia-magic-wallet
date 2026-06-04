import { cn } from '@/lib/utils';

interface StatusBadgeProps {
  status: string;
  size?: 'sm' | 'md';
}

const statusConfig: Record<string, { label: string; className: string }> = {
  // Trade roles
  BUYER:         { label: 'Buyer',         className: 'bg-green-50 text-green-700 border-green-200' },
  SELLER:        { label: 'Seller',        className: 'bg-blue-50 text-blue-700 border-blue-200' },
  BOTH:          { label: 'Buyer & Seller', className: 'bg-secondary text-secondary-foreground border-border' },

  // Green — success states
  ACTIVE:        { label: 'Active',        className: 'bg-green-50 text-green-700 border-green-200' },
  AGREED:        { label: 'Agreed',        className: 'bg-green-50 text-green-700 border-green-200' },
  MATCHED:       { label: 'Matched',       className: 'bg-green-50 text-green-700 border-green-200' },
  RELEASED:      { label: 'Released',      className: 'bg-green-50 text-green-700 border-green-200' },
  KYCD:          { label: 'KYC Active',    className: 'bg-green-50 text-green-700 border-green-200' },

  // Amber — in-progress states
  PENDING:       { label: 'Pending',       className: 'bg-amber-50 text-amber-700 border-amber-200' },
  PENDING_APPROVAL: { label: 'Pending Approval', className: 'bg-amber-50 text-amber-700 border-amber-200' },
  PARSED:        { label: 'Parsed',        className: 'bg-amber-50 text-amber-700 border-amber-200' },
  DEPLOYED:      { label: 'Deployed',      className: 'bg-amber-50 text-amber-700 border-amber-200' },
  STALLED:       { label: 'Stalled',       className: 'bg-amber-50 text-amber-700 border-amber-200' },
  NEGOTIATING:   { label: 'Negotiating',   className: 'bg-purple-50 text-purple-700 border-purple-200' },

  // Blue — confirmed states
  CONFIRMED:     { label: 'Confirmed',     className: 'bg-blue-50 text-blue-700 border-blue-200' },
  FUNDED:        { label: 'Funded',        className: 'bg-blue-50 text-blue-700 border-blue-200' },
  DISPATCHED:    { label: 'Dispatched',   className: 'bg-indigo-50 text-indigo-700 border-indigo-200' },
  WALLET_LINKED: { label: 'Wallet Linked', className: 'bg-blue-50 text-blue-700 border-blue-200' },
  ADMIN:         { label: 'Admin',         className: 'bg-blue-50 text-blue-700 border-blue-200' },

  // Muted — neutral / initial states
  DRAFT:         { label: 'Draft',         className: 'bg-muted text-muted-foreground border-border' },
  NOT_SUBMITTED: { label: 'Not Submitted', className: 'bg-muted text-muted-foreground border-border' },
  IDLE:          { label: 'Idle',          className: 'bg-muted text-muted-foreground border-border' },
  TERMINATED:    { label: 'Terminated',    className: 'bg-muted text-muted-foreground border-border' },

  // Gray — closed by external action
  CLOSED_BY_BUYER: { label: 'Buyer Selected Other', className: 'bg-muted text-muted-foreground border-border' },

  // Red — error / failure states
  PARSE_FAILED:  { label: 'Parse Failed',  className: 'bg-red-50 text-red-700 border-red-200' },
  FAILED:        { label: 'Not Selected',   className: 'bg-amber-50 text-amber-700 border-amber-200' },
  REJECTED:      { label: 'Rejected',      className: 'bg-red-50 text-red-700 border-red-200' },
  FROZEN:        { label: 'Frozen',        className: 'bg-red-50 text-red-700 border-red-200' },
  REFUNDED:      { label: 'Refunded',      className: 'bg-red-50 text-red-700 border-red-200' },
};

export function StatusBadge({ status, size = 'sm' }: StatusBadgeProps) {
  const config = statusConfig[status] ?? {
    label: status,
    className: 'bg-muted text-muted-foreground border-border',
  };

  return (
    <span className={cn(
      'inline-flex items-center border font-medium rounded-md',
      size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-3 py-1 text-sm',
      config.className
    )}>
      {config.label}
    </span>
  );
}
