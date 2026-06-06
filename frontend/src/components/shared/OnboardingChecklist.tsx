'use client';

import * as React from 'react';
import { CheckCircle2, Circle, X } from 'lucide-react';
import { cn } from '@/lib/utils';

interface ChecklistItem {
  key: string;
  label: string;
  description: string;
  completed: boolean;
  href?: string;
}

interface OnboardingChecklistProps {
  role: 'BUYER' | 'SELLER' | 'BOTH';
  checklist: Record<string, boolean>;
  onDismiss: () => void;
}

const BUYER_STEPS: Omit<ChecklistItem, 'completed'>[] = [
  { key: 'wallet_linked', label: 'Link your wallet', description: 'Connect your Algorand wallet for secure escrow', href: '/settings/wallet' },
  { key: 'first_rfq', label: 'Submit your first RFQ', description: 'Tell us what you need — AI finds the best sellers', href: '/marketplace' },
  { key: 'first_negotiation_viewed', label: 'View a negotiation', description: 'Watch your AI agent negotiate on your behalf', href: '/negotiations' },
];

const SELLER_STEPS: Omit<ChecklistItem, 'completed'>[] = [
  { key: 'wallet_linked', label: 'Link your wallet', description: 'Connect your Algorand wallet to receive payments', href: '/settings/wallet' },
  { key: 'catalogue_item_added', label: 'Add a product', description: 'List your products so buyers can find you', href: '/marketplace/catalogue' },
  { key: 'profile_completed', label: 'Complete your profile', description: 'Set capacity, certifications, and payment terms', href: '/marketplace/profile' },
];

export function OnboardingChecklist({ role, checklist, onDismiss }: OnboardingChecklistProps) {
  const steps = role === 'BUYER' ? BUYER_STEPS : SELLER_STEPS;
  const items: ChecklistItem[] = steps.map(s => ({ ...s, completed: !!checklist[s.key] }));
  const allDone = items.every(i => i.completed);

  if (allDone) return null;

  const completed = items.filter(i => i.completed).length;
  const pct = Math.round((completed / items.length) * 100);

  return (
    <div className="border border-border rounded-lg bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-foreground">Getting Started</h3>
          <p className="text-xs text-muted-foreground">{completed}/{items.length} completed ({pct}%)</p>
        </div>
        <button onClick={onDismiss} className="p-1 rounded hover:bg-accent text-muted-foreground">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="h-1.5 bg-muted rounded-full overflow-hidden">
        <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
      </div>
      <div className="space-y-2">
        {items.map(item => (
          <a
            key={item.key}
            href={item.href || '#'}
            className={cn(
              'flex items-start gap-3 p-2 rounded-md transition-colors',
              item.completed ? 'opacity-60' : 'hover:bg-accent',
            )}
          >
            {item.completed ? (
              <CheckCircle2 className="h-4 w-4 text-green-500 mt-0.5 shrink-0" />
            ) : (
              <Circle className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
            )}
            <div>
              <p className={cn('text-sm font-medium', item.completed ? 'line-through text-muted-foreground' : 'text-foreground')}>
                {item.label}
              </p>
              <p className="text-xs text-muted-foreground">{item.description}</p>
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}
