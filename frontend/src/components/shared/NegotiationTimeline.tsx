'use client';

import * as React from 'react';
import { Bot, ArrowDownRight, ArrowUpRight, Zap, Ban, TrendingDown } from 'lucide-react';
import { formatCurrency, cn } from '@/lib/utils';
import type { NegotiationOffer, SessionStatus } from '@/types';

interface NegotiationTimelineProps {
  offers: NegotiationOffer[];
  sessionStatus: SessionStatus;
}

// ── Confidence ring gauge ────────────────────────────────────────────────────
function ConfidenceRing({ value }: { value: number }) {
  const r = 13;
  const circ = 2 * Math.PI * r;
  const offset = circ - value * circ;
  const color = value >= 0.75 ? '#22c55e' : value >= 0.5 ? '#f59e0b' : '#ef4444';
  return (
    <svg width="34" height="34" viewBox="0 0 34 34" className="shrink-0">
      <circle cx="17" cy="17" r={r} fill="none" stroke="hsl(var(--muted))" strokeWidth="2.5" />
      <circle
        cx="17" cy="17" r={r}
        fill="none" stroke={color} strokeWidth="2.5"
        strokeDasharray={`${circ}`} strokeDashoffset={`${offset}`}
        strokeLinecap="round" transform="rotate(-90 17 17)"
        style={{ transition: 'stroke-dashoffset 0.6s cubic-bezier(.4,0,.2,1)' }}
      />
      <text x="17" y="21" textAnchor="middle" fontSize="8.5" fill={color} fontWeight="700">
        {Math.round(value * 100)}
      </text>
    </svg>
  );
}

// ── Strategy tag extracted from reasoning ────────────────────────────────────
function getStrategyTag(reasoning: string): { label: string; style: string } | null {
  const r = reasoning.toLowerCase();
  if (r.startsWith('reject:') || r.includes('must reject') || r.includes('walk away')) {
    return { label: 'REJECT', style: 'bg-red-50 text-red-700 border-red-200' };
  }
  if (r.includes('prices crossed') || r.includes('instant agreement')) {
    return { label: 'INSTANT DEAL', style: 'bg-green-50 text-green-700 border-green-200' };
  }
  if (r.includes('no zone') || r.includes('no zopa') || r.includes('walking away')) {
    return { label: 'NO ZOPA', style: 'bg-red-50 text-red-700 border-red-200' };
  }
  if (r.includes('anchor') || r.includes('listed asking price')) {
    return { label: 'ANCHOR', style: 'bg-blue-50 text-blue-700 border-blue-200' };
  }
  if (r.includes('maximize') || r.includes('aggressive')) {
    return { label: 'AGGRESSIVE', style: 'bg-orange-50 text-orange-700 border-orange-200' };
  }
  if (r.includes('conservative') || r.includes('cautious')) {
    return { label: 'CONSERVATIVE', style: 'bg-secondary text-muted-foreground border-border' };
  }
  if (r.includes('concession') || r.includes('concede') || r.includes('halfway')) {
    return { label: 'CONCESSIVE', style: 'bg-violet-50 text-violet-700 border-violet-200' };
  }
  if (r.includes('budget ceiling') || r.includes('budget') || r.includes('floor')) {
    return { label: 'CONSTRAINED', style: 'bg-amber-50 text-amber-600 border-amber-200' };
  }
  return null;
}

// ── Price delta indicator ────────────────────────────────────────────────────
function PriceDelta({ current, previous }: { current: number; previous: number | null }) {
  if (previous === null || Math.abs(current - previous) < 1) return null;
  const delta = current - previous;
  const isBuying = delta > 0; // buyer going up = conceding; seller going down = conceding
  const Icon = delta > 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <span className="flex items-center gap-0.5 text-[11px] font-medium text-muted-foreground">
      <Icon className="h-3 w-3" />
      {formatCurrency(Math.abs(delta))}
    </span>
  );
}

// ── Main component ───────────────────────────────────────────────────────────
export function NegotiationTimeline({ offers, sessionStatus }: NegotiationTimelineProps) {
  const endRef = React.useRef<HTMLDivElement>(null);
  const isActive = sessionStatus === 'ACTIVE';

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [offers.length]);

  // Track per-side history for deltas
  const buyerHistory: number[] = [];
  const sellerHistory: number[] = [];

  return (
    <div className="space-y-4 pb-2">
      {offers.map((offer) => {
        const isBuyer = offer.proposer_role === 'BUYER';
        const side = isBuyer ? 'buyer' : 'seller';
        const history = isBuyer ? buyerHistory : sellerHistory;
        const prevPrice = history.length > 0 ? history[history.length - 1] : null;
        history.push(offer.price);

        const strategy = getStrategyTag(offer.agent_reasoning ?? '');

        return (
          <div
            key={`${offer.round_number}-${offer.proposer_role}`}
            className={cn('flex gap-3 items-start animate-in fade-in slide-in-from-bottom-2 duration-300', isBuyer ? 'flex-row-reverse' : 'flex-row')}
          >
            {/* Agent avatar */}
            <div className={cn(
              'mt-1 shrink-0 w-9 h-9 rounded-full flex items-center justify-center border-2 shadow-lg',
              isBuyer
                ? 'bg-emerald-50 border-emerald-700 shadow-emerald-100'
                : 'bg-blue-50 border-blue-700 shadow-blue-100'
            )}>
              <Bot className={cn('h-4 w-4', isBuyer ? 'text-emerald-700' : 'text-blue-700')} />
            </div>

            {/* Bubble */}
            <div className={cn(
              'relative max-w-[72%] min-w-[220px] rounded-2xl px-4 py-3 border shadow-md',
              isBuyer
                ? 'rounded-tr-sm bg-emerald-50 border-emerald-200 shadow-emerald-100/20'
                : 'rounded-tl-sm bg-blue-50 border-blue-200 shadow-blue-100/20'
            )}>

              {/* Top row: agent name + round + strategy tag */}
              <div className={cn('flex items-center gap-2 mb-2 flex-wrap', isBuyer ? 'justify-end' : 'justify-start')}>
                <span className={cn('text-[11px] font-bold tracking-wider uppercase', isBuyer ? 'text-emerald-700' : 'text-blue-700')}>
                  {isBuyer ? 'Buyer Agent' : 'Seller Agent'}
                </span>
                <span className="text-[10px] text-muted-foreground bg-secondary px-1.5 py-0.5 rounded font-mono">
                  R{offer.round_number}
                </span>
                {strategy && (
                  <span className={cn('text-[9px] px-1.5 py-0.5 rounded border font-mono uppercase tracking-widest', strategy.style)}>
                    {strategy.label}
                  </span>
                )}
              </div>

              {/* Price row */}
              <div className={cn('flex items-baseline gap-2 mb-2', isBuyer ? 'justify-end' : 'justify-start')}>
                <span className={cn(
                  'text-2xl font-black tabular-nums tracking-tight',
                  isBuyer ? 'text-emerald-700' : 'text-blue-700'
                )}>
                  {formatCurrency(offer.price)}
                </span>
                <span className="text-xs text-muted-foreground/60">total</span>
                <PriceDelta current={offer.price} previous={prevPrice} />
              </div>

              {/* Reasoning */}
              {offer.agent_reasoning && (
                <p className={cn(
                  'text-[11px] text-muted-foreground/75 leading-relaxed italic border-t pt-2 mt-1',
                  isBuyer ? 'text-right border-emerald-200' : 'text-left border-blue-200'
                )}>
                  {offer.agent_reasoning}
                </p>
              )}

              {/* Footer: confidence ring */}
              {offer.confidence != null && (
                <div className={cn('flex items-center gap-1.5 mt-2', isBuyer ? 'justify-end' : 'justify-start')}>
                  <ConfidenceRing value={offer.confidence} />
                  <span className="text-[9px] text-muted-foreground uppercase tracking-widest">confidence</span>
                </div>
              )}
            </div>
          </div>
        );
      })}

      {/* AI thinking indicator */}
      {isActive && offers.length > 0 && (
        <div className="flex items-center gap-3 py-1 pl-2">
          <div className="w-9 h-9 rounded-full bg-secondary border border-border flex items-center justify-center shrink-0">
            <Bot className="h-4 w-4 text-muted-foreground animate-pulse" />
          </div>
          <div className="flex items-center gap-1.5">
            {[0, 1, 2].map(i => (
              <div
                key={i}
                className="w-2 h-2 rounded-full bg-primary/50"
                style={{
                  animation: 'bounce 1.2s infinite',
                  animationDelay: `${i * 200}ms`,
                }}
              />
            ))}
            <span className="text-xs text-muted-foreground ml-1">Agent is calculating next move</span>
          </div>
        </div>
      )}

      {offers.length === 0 && (
        <div className="text-center py-12 text-muted-foreground">
          <Bot className="h-10 w-10 mx-auto mb-3 opacity-20" />
          <p className="text-sm">Waiting for first offer...</p>
        </div>
      )}

      <div ref={endRef} />
    </div>
  );
}
