'use client';

import * as React from 'react';
import { Cpu } from 'lucide-react';
import { formatCurrency } from '@/lib/utils';
import { cn } from '@/lib/utils';
import type { NegotiationOffer, SessionStatus } from '@/types';

interface NegotiationTimelineProps {
  offers: NegotiationOffer[];
  sessionStatus: SessionStatus;
}

export function NegotiationTimeline({ offers, sessionStatus }: NegotiationTimelineProps) {
  const endRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [offers.length]);

  const isWaiting = sessionStatus === 'ACTIVE';

  return (
    <div className="space-y-1">
      {offers.map((offer, i) => {
        const isBuyer = offer.proposer_role === 'BUYER';
        const borderColor = isBuyer ? 'border-l-green-500' : 'border-l-blue-500';
        const agentLabel = isBuyer ? 'Buyer Agent' : 'Seller Agent';

        return (
          <div
            key={`${offer.round_number}-${offer.proposer_role}`}
            className={cn(
              'relative pl-8 py-3 border-l-2 ml-3',
              borderColor,
              i === offers.length - 1 && isWaiting && 'opacity-100'
            )}
          >
            <div className={cn(
              'absolute left-[-13px] top-3 bg-card border border-border rounded-full p-1',
            )}>
              <Cpu className={cn('h-4 w-4', isBuyer ? 'text-green-400' : 'text-blue-400')} />
            </div>

            <div className="flex items-baseline justify-between gap-2">
              <div>
                <span className={cn('text-xs font-medium', isBuyer ? 'text-green-400' : 'text-blue-400')}>
                  {agentLabel}
                </span>
                <span className="text-xs text-muted-foreground ml-2">Round {offer.round_number}</span>
              </div>
              <span className="text-lg font-bold text-foreground">
                {formatCurrency(offer.price)}
                <span className="text-xs font-normal text-muted-foreground"> total</span>
              </span>
            </div>

            {offer.terms && Object.keys(offer.terms).length > 0 && (
              <div className="flex flex-wrap gap-2 mt-1.5">
                {Object.entries(offer.terms).map(([k, v]) => (
                  <span key={k} className="text-xs bg-secondary text-secondary-foreground px-2 py-0.5 rounded">
                    {k}: {String(v)}
                  </span>
                ))}
              </div>
            )}

            <div className="flex items-center gap-3 mt-1">
              <span className="text-xs text-muted-foreground">
                Confidence: {offer.confidence != null ? `${Math.round(offer.confidence * 100)}%` : '—'}
              </span>
              <div className="flex-1 max-w-[100px] bg-muted rounded-full h-1">
                <div
                  className={cn('h-1 rounded-full', (offer.confidence ?? 0) >= 0.8 ? 'bg-green-500' : (offer.confidence ?? 0) >= 0.6 ? 'bg-amber-500' : 'bg-destructive')}
                  style={{ width: `${(offer.confidence ?? 0) * 100}%` }}
                />
              </div>
            </div>

            {offer.agent_reasoning && (
              <p className="text-xs text-muted-foreground/70 mt-1.5 italic leading-relaxed">
                {offer.agent_reasoning}
              </p>
            )}
          </div>
        );
      })}

      {/* Waiting indicator */}
      {isWaiting && (
        <div className="relative pl-8 py-3 border-l-2 border-l-border ml-3 opacity-50">
          <div className="absolute left-[-13px] top-3 bg-card border border-border rounded-full p-1">
            <Cpu className="h-4 w-4 text-muted-foreground animate-pulse" />
          </div>
          <span className="text-sm text-muted-foreground animate-pulse">
            Waiting for response
            <span className="inline-flex ml-1 tracking-widest">
              <span className="animate-bounce" style={{ animationDelay: '0ms' }}>.</span>
              <span className="animate-bounce" style={{ animationDelay: '150ms' }}>.</span>
              <span className="animate-bounce" style={{ animationDelay: '300ms' }}>.</span>
            </span>
          </span>
        </div>
      )}

      <div ref={endRef} />
    </div>
  );
}
