'use client';

import * as React from 'react';
import { formatCurrency, cn } from '@/lib/utils';
import type { NegotiationOffer, SessionStatus } from '@/types';

interface NegotiationTimelineProps {
  offers: NegotiationOffer[];
  sessionStatus: SessionStatus;
}

// ── Strategy tag ─────────────────────────────────────────────────────────────
function getStrategyTag(reasoning: string): { label: string; lightCls: string; darkCls: string } | null {
  const r = reasoning.toLowerCase();
  if (r.startsWith('reject:') || r.includes('must reject') || r.includes('walk away'))
    return { label: 'REJECT', lightCls: 'text-red-600 border-red-300/60', darkCls: 'text-[#c96b5a] border-[rgba(201,107,90,.3)]' };
  if (r.includes('prices crossed') || r.includes('instant agreement'))
    return { label: 'INSTANT DEAL', lightCls: 'text-emerald-700 border-emerald-300/60', darkCls: 'text-[#5ab98a] border-[rgba(90,185,138,.3)]' };
  if (r.includes('no zone') || r.includes('no zopa') || r.includes('walking away'))
    return { label: 'NO ZOPA', lightCls: 'text-red-600 border-red-300/60', darkCls: 'text-[#c96b5a] border-[rgba(201,107,90,.3)]' };
  if (r.includes('anchor') || r.includes('listed asking price'))
    return { label: 'ANCHOR', lightCls: 'text-blue-600 border-blue-300/60', darkCls: 'text-[#7aaedf] border-[rgba(122,174,223,.3)]' };
  if (r.includes('maximize') || r.includes('aggressive'))
    return { label: 'AGGRESSIVE', lightCls: 'text-orange-600 border-orange-300/60', darkCls: 'text-[#d4876a] border-[rgba(212,135,106,.3)]' };
  if (r.includes('conservative') || r.includes('cautious'))
    return { label: 'CONSERVATIVE', lightCls: 'text-muted-foreground border-border', darkCls: 'text-[#7a7268] border-[#3a3830]' };
  if (r.includes('concession') || r.includes('concede') || r.includes('halfway'))
    return { label: 'CONCESSIVE', lightCls: 'text-violet-600 border-violet-300/60', darkCls: 'text-[#a891d8] border-[rgba(168,145,216,.3)]' };
  if (r.includes('budget ceiling') || r.includes('budget') || r.includes('floor'))
    return { label: 'CONSTRAINED', lightCls: 'text-amber-600 border-amber-300/60', darkCls: 'text-[#c9a05a] border-[rgba(201,160,90,.3)]' };
  return null;
}

// ── Price delta ──────────────────────────────────────────────────────────────
function PriceDelta({ current, previous, isBuyer }: { current: number; previous: number | null; isBuyer: boolean }) {
  if (previous === null || Math.abs(current - previous) < 1) return null;
  const delta = current - previous;
  const isUp = delta > 0;
  // Up = buyer conceding (good for seller) or seller raising (bad)
  // Show red for price going up (for buyer), green for price going down (for seller)
  const isGood = isBuyer ? isUp : !isUp; // buyer moving up = progress; seller moving down = progress
  return (
    <span className={cn(
      'inline-flex items-center gap-0.5 text-[11px] font-mono font-medium px-1.5 py-0.5 rounded border',
      isGood
        ? 'text-emerald-600 bg-emerald-50/80 border-emerald-200 dark:text-[#5ab98a] dark:bg-[rgba(90,185,138,.07)] dark:border-[rgba(90,185,138,.2)]'
        : 'text-red-500 bg-red-50/80 border-red-200 dark:text-[#c96b5a] dark:bg-[rgba(201,107,90,.07)] dark:border-[rgba(201,107,90,.2)]'
    )}>
      {isUp ? '↑' : '↓'} {formatCurrency(Math.abs(delta))}
    </span>
  );
}

// ── Confidence bar ───────────────────────────────────────────────────────────
function ConfBar({ value, isBuyer }: { value: number; isBuyer: boolean }) {
  const color = value >= 0.75
    ? '#5ab98a'
    : value >= 0.5
    ? '#c9a05a'
    : '#c96b5a';
  return (
    <div className="flex items-center gap-2">
      <div className="w-14 h-1.5 rounded-full bg-black/10 dark:bg-white/10 overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{ width: `${Math.round(value * 100)}%`, background: color }}
        />
      </div>
      <span className="text-[10px] font-mono text-muted-foreground">{Math.round(value * 100)}%</span>
    </div>
  );
}

// ── Main ─────────────────────────────────────────────────────────────────────
export function NegotiationTimeline({ offers, sessionStatus }: NegotiationTimelineProps) {
  const endRef = React.useRef<HTMLDivElement>(null);
  const isActive = sessionStatus === 'ACTIVE';

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [offers.length]);

  const buyerHistory: number[] = [];
  const sellerHistory: number[] = [];

  return (
    <div className="flex flex-col gap-5 pb-2">
      {offers.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-muted-foreground/50">
          <svg className="w-10 h-10 mb-3 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1"
              d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
          </svg>
          <p className="text-sm italic">Waiting for the first offer…</p>
        </div>
      )}

      {offers.map((offer) => {
        const isBuyer = offer.proposer_role === 'BUYER';
        const history = isBuyer ? buyerHistory : sellerHistory;
        const prevPrice = history.length > 0 ? history[history.length - 1] : null;
        history.push(offer.price);
        const strategy = getStrategyTag(offer.agent_reasoning ?? '');
        const isHuman = offer.is_human_override;

        return (
          <div
            key={`${offer.round_number}-${offer.proposer_role}`}
            className={cn(
              'flex gap-3 items-start',
              'animate-in fade-in slide-in-from-bottom-2 duration-300',
              isBuyer ? 'flex-row-reverse' : 'flex-row'
            )}
          >
            {/* Avatar */}
            <div className={cn(
              'mt-1.5 shrink-0 w-8 h-8 rounded-full flex items-center justify-center border',
              isBuyer
                ? 'bg-emerald-50 border-emerald-300/70 dark:bg-[rgba(107,191,158,.08)] dark:border-[rgba(107,191,158,.18)]'
                : 'bg-blue-50 border-blue-300/70 dark:bg-[rgba(122,174,223,.08)] dark:border-[rgba(122,174,223,.18)]'
            )}>
              <svg className={cn('w-3.5 h-3.5',
                isBuyer ? 'text-emerald-700 dark:text-[#6bbf9e]' : 'text-blue-700 dark:text-[#7aaedf]'
              )} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5"
                  d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
              </svg>
            </div>

            {/* Bubble */}
            <div className={cn(
              'relative max-w-[70%] min-w-[240px] rounded-xl px-4 py-3.5 border',
              isBuyer
                ? 'rounded-tr-sm bg-emerald-50/70 border-emerald-200/70 dark:bg-[rgba(107,191,158,.07)] dark:border-[rgba(107,191,158,.18)]'
                : 'rounded-tl-sm bg-blue-50/70 border-blue-200/70 dark:bg-[rgba(122,174,223,.07)] dark:border-[rgba(122,174,223,.18)]',
              isHuman && 'ring-1 ring-offset-1 ring-amber-400/60 dark:ring-[rgba(232,201,154,.4)]'
            )}>
              {/* Header row */}
              <div className={cn('flex items-center gap-2 mb-2.5 flex-wrap',
                isBuyer ? 'justify-end' : 'justify-start'
              )}>
                <span className={cn('text-[10px] font-bold tracking-widest uppercase',
                  isBuyer ? 'text-emerald-700 dark:text-[#6bbf9e]' : 'text-blue-700 dark:text-[#7aaedf]'
                )}>
                  {isBuyer ? 'Buyer Agent' : 'Seller Agent'}
                </span>
                <span className="text-[10px] font-mono text-muted-foreground bg-black/5 dark:bg-white/8 px-1.5 py-0.5 rounded">
                  R{offer.round_number}
                </span>
                {strategy && (
                  <span className={cn(
                    'text-[9px] font-mono font-medium uppercase tracking-wider px-1.5 py-0.5 rounded border',
                    strategy.lightCls,
                    // dark mode via CSS class — can't use dark: with arbitrary values easily
                  )}>
                    {strategy.label}
                  </span>
                )}
                {isHuman && (
                  <span className="text-[9px] font-mono font-medium uppercase tracking-wider px-1.5 py-0.5 rounded border text-amber-600 border-amber-300/70 dark:text-[#e8c99a] dark:border-[rgba(232,201,154,.35)]">
                    Human
                  </span>
                )}
              </div>

              {/* Price row — big serif-style number */}
              <div className={cn('flex items-baseline gap-2 mb-2.5',
                isBuyer ? 'justify-end' : 'justify-start'
              )}>
                <span className={cn(
                  'text-3xl font-light tabular-nums tracking-tight leading-none',
                  isBuyer ? 'text-emerald-700 dark:text-[#6bbf9e]' : 'text-blue-700 dark:text-[#7aaedf]'
                )}>
                  {formatCurrency(offer.price)}
                </span>
                <span className="text-xs text-muted-foreground/60">total</span>
                <PriceDelta current={offer.price} previous={prevPrice} isBuyer={isBuyer} />
              </div>

              {/* Reasoning */}
              {offer.agent_reasoning && (
                <p className={cn(
                  'text-[11px] text-muted-foreground leading-relaxed border-t pt-2 mt-1 mb-2.5',
                  isBuyer
                    ? 'text-right border-emerald-200/50 dark:border-[rgba(107,191,158,.15)]'
                    : 'text-left border-blue-200/50 dark:border-[rgba(122,174,223,.15)]'
                )}>
                  {offer.agent_reasoning}
                </p>
              )}

              {/* Confidence bar */}
              {offer.confidence != null && (
                <div className={cn('flex', isBuyer ? 'justify-end' : 'justify-start')}>
                  <ConfBar value={offer.confidence} isBuyer={isBuyer} />
                </div>
              )}
            </div>
          </div>
        );
      })}

      {/* Thinking indicator */}
      {isActive && offers.length > 0 && (
        <div className="flex items-center gap-3 py-1 pl-1">
          <div className="w-8 h-8 rounded-full bg-muted border border-border flex items-center justify-center shrink-0">
            <svg className="w-3.5 h-3.5 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5"
                d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
            </svg>
          </div>
          <div className="flex items-center gap-1.5">
            {[0, 1, 2].map(i => (
              <div key={i} className="w-1.5 h-1.5 rounded-full bg-muted-foreground/40"
                style={{ animation: 'bounce 1.2s infinite', animationDelay: `${i * 200}ms` }} />
            ))}
            <span className="text-xs text-muted-foreground italic ml-1.5">Agent is calculating…</span>
          </div>
        </div>
      )}

      <div ref={endRef} />
    </div>
  );
}
