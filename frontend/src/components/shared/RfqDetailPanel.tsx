'use client';

import * as React from 'react';
import { Loader2, Zap, CheckCircle2, XCircle, Clock, Trophy } from 'lucide-react';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { AsyncPollingStatus } from '@/components/shared/AsyncPollingStatus';
import { ConfirmDialog } from '@/components/shared/ConfirmDialog';
import { Button } from '@/components/ui/button';
import { formatDate, formatCurrency } from '@/lib/utils';
import type { RFQ, SellerMatch } from '@/types';

interface NegotiationSession {
  session_id: string;
  seller_enterprise_id: string;
  buyer_enterprise_id: string;
  status: string;
  current_round: number;
  agreed_price?: number;
  agreed_terms_json?: any;
  seller_name?: string;
}

interface RfqDetailPanelProps {
  rfq: RFQ;
  matches: SellerMatch[];
  matchesLoading: boolean;
  negotiations?: NegotiationSession[];
  onStartNegotiations: () => void;
  isStartingNegotiations: boolean;
  onAcceptDeal: (match: SellerMatch) => void;
  isAcceptingDeal: boolean;
}

const FIELD_LABELS: Record<string, string> = {
  product: 'Product',
  hsn: 'HSN Code',
  quantity: 'Quantity',
  budget_min: 'Budget Min',
  budget_max: 'Budget Max',
  delivery_days: 'Delivery',
  geography: 'Geography',
};

const NEG_STATUS_ICONS: Record<string, React.ReactNode> = {
  AGREED: <CheckCircle2 className="h-4 w-4 text-green-600" />,
  FAILED: <XCircle className="h-4 w-4 text-red-500" />,
  WALK_AWAY: <XCircle className="h-4 w-4 text-red-500" />,
  TIMEOUT: <Clock className="h-4 w-4 text-amber-500" />,
};

export function RfqDetailPanel({
  rfq, matches, matchesLoading, negotiations = [],
  onStartNegotiations, isStartingNegotiations,
  onAcceptDeal, isAcceptingDeal,
}: RfqDetailPanelProps) {
  const [acceptTarget, setAcceptTarget] = React.useState<SellerMatch | null>(null);
  const [confirmStartOpen, setConfirmStartOpen] = React.useState(false);

  const parsedEntries = React.useMemo(() => {
    if (!rfq.parsed_fields) return [];
    return Object.entries(rfq.parsed_fields).map(([key, val]) => ({
      label: FIELD_LABELS[key] ?? key,
      value: key === 'delivery_days' ? `${val} days` : String(val),
    }));
  }, [rfq.parsed_fields]);

  // Map negotiations to matches for comparison table (stringify UUIDs for safe comparison)
  const negotiationsBySellerMap = React.useMemo(() => {
    const map = new Map<string, NegotiationSession>();
    negotiations.forEach(n => {
      map.set(String(n.seller_enterprise_id), n);
    });
    return map;
  }, [negotiations]);

  const agreedDeals = matches.filter(m => {
    const neg = negotiationsBySellerMap.get(m.enterprise_id);
    return neg?.status === 'AGREED';
  }).sort((a, b) => {
    const negA = negotiationsBySellerMap.get(a.enterprise_id);
    const negB = negotiationsBySellerMap.get(b.enterprise_id);
    return (negA?.agreed_price ?? Infinity) - (negB?.agreed_price ?? Infinity);
  });

  return (
    <div className="space-y-5">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-1 flex-wrap">
          <h3 className="text-sm font-semibold text-foreground">
            {rfq.parsed_fields?.product
              ? String(rfq.parsed_fields.product).charAt(0).toUpperCase() + String(rfq.parsed_fields.product).slice(1)
              : `RFQ #${rfq.id.slice(0, 8)}…`}
            {rfq.parsed_fields?.quantity && (
              <span className="text-muted-foreground font-normal"> × {rfq.parsed_fields.quantity}</span>
            )}
          </h3>
          <StatusBadge status={rfq.status} />
        </div>
        <p className="text-xs text-muted-foreground">{formatDate(rfq.created_at)}</p>
      </div>

      {/* Raw text */}
      <div>
        <p className="text-xs uppercase tracking-wide text-muted-foreground mb-1">Description</p>
        <p className="text-sm text-foreground leading-relaxed">{rfq.raw_text}</p>
      </div>

      {/* Polling status for DRAFT/PARSED */}
      {(rfq.status === 'DRAFT' || rfq.status === 'PARSED') && (
        <AsyncPollingStatus status={rfq.status} />
      )}

      {/* Parsed fields */}
      {parsedEntries.length > 0 && (
        <div>
          <p className="text-xs uppercase tracking-wide text-muted-foreground mb-2">Parsed Fields (AI-extracted)</p>
          <div className="grid grid-cols-2 gap-3">
            {parsedEntries.map(({ label, value }) => (
              <div key={label}>
                <p className="text-xs text-muted-foreground">{label}</p>
                <p className="text-sm font-medium text-foreground">{value}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* MATCHED: Show matches + Start All Negotiations button */}
      {rfq.status === 'MATCHED' && (
        <div>
          <p className="text-xs uppercase tracking-wide text-muted-foreground mb-3">
            Matched Sellers ({matches.length})
          </p>
          {matchesLoading ? (
            <div className="flex items-center gap-2 py-4">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              <span className="text-sm text-muted-foreground">Loading matches...</span>
            </div>
          ) : matches.length === 0 ? (
            <p className="text-sm text-muted-foreground py-2">No matches found</p>
          ) : (
            <>
              <div className="space-y-2 mb-4">
                {matches.map((m) => (
                  <div
                    key={m.enterprise_id}
                    className="flex items-center justify-between p-3 bg-muted rounded-lg border border-border"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-mono text-muted-foreground">#{m.rank}</span>
                        <span className="text-sm font-medium text-foreground truncate">{m.enterprise_name}</span>
                      </div>
                      {m.capabilities && m.capabilities.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1">
                          {m.capabilities.map((c) => (
                            <span key={c} className="text-xs bg-secondary text-secondary-foreground px-1.5 py-0.5 rounded">
                              {c}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    <span className="text-sm font-semibold text-primary shrink-0 ml-3">{m.score}%</span>
                  </div>
                ))}
              </div>
              <Button
                onClick={() => setConfirmStartOpen(true)}
                disabled={isStartingNegotiations}
                className="w-full bg-primary text-primary-foreground hover:bg-primary/90"
              >
                {isStartingNegotiations ? (
                  <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Starting...</>
                ) : (
                  <><Zap className="mr-2 h-4 w-4" />Start AI Negotiations with All Sellers</>
                )}
              </Button>
            </>
          )}
        </div>
      )}

      {/* NEGOTIATING: Comparison table */}
      {rfq.status === 'NEGOTIATING' && (
        <div>
          <p className="text-xs uppercase tracking-wide text-muted-foreground mb-3">
            Negotiation Progress
          </p>

          {matches.length === 0 ? (
            <div className="flex items-center gap-2 py-4">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              <span className="text-sm text-muted-foreground">Loading negotiations...</span>
            </div>
          ) : (
            <div className="space-y-2">
              {matches.map((m) => {
                const neg = negotiationsBySellerMap.get(m.enterprise_id);
                const isAgreed = neg?.status === 'AGREED';
                const isBestDeal = agreedDeals.length > 0 && agreedDeals[0].enterprise_id === m.enterprise_id;

                return (
                  <div
                    key={m.enterprise_id}
                    className={`p-3 rounded-lg border ${
                      isBestDeal
                        ? 'border-green-200 bg-green-50'
                        : 'border-border bg-muted'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2 min-w-0 flex-1">
                        {isBestDeal && <Trophy className="h-4 w-4 text-green-600 shrink-0" />}
                        <span className="text-sm font-medium text-foreground truncate">{m.enterprise_name}</span>
                      </div>
                      <div className="flex items-center gap-2 shrink-0 ml-2">
                        {neg ? (
                          <>
                            {NEG_STATUS_ICONS[neg.status] || <Loader2 className="h-4 w-4 animate-spin text-blue-700" />}
                            <StatusBadge status={neg.status} size="sm" />
                          </>
                        ) : (
                          <span className="text-xs text-muted-foreground">Pending</span>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center justify-between text-xs gap-2">
                      <div className="flex gap-3 items-center min-w-0">
                        <span className="text-muted-foreground shrink-0">
                          R<span className="text-foreground font-mono font-semibold">{neg?.current_round ?? 0}</span>/20
                        </span>
                        {/* Round progress bar */}
                        <div className="w-12 h-1 bg-muted rounded-full overflow-hidden">
                          <div
                            className="h-full rounded-full bg-primary/60 transition-all duration-500"
                            style={{ width: `${((neg?.current_round ?? 0) / 20) * 100}%` }}
                          />
                        </div>
                        <span className="text-muted-foreground shrink-0">
                          <span className="text-foreground font-medium">{m.score}%</span> match
                        </span>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {isAgreed && neg?.agreed_price && (
                          <span className="text-green-600 font-semibold">
                            {formatCurrency(neg.agreed_price)}
                          </span>
                        )}
                      </div>
                    </div>

                    {isAgreed && (
                      <Button
                        size="sm"
                        onClick={() => setAcceptTarget(m)}
                        disabled={isAcceptingDeal}
                        className={`mt-2 w-full text-xs h-7 ${
                          isBestDeal
                            ? 'bg-green-600 text-white hover:bg-green-700'
                            : 'bg-primary text-primary-foreground hover:bg-primary/90'
                        }`}
                      >
                        {isBestDeal ? 'Accept Best Deal' : 'Accept This Deal'}
                      </Button>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {agreedDeals.length === 0 && negotiations.length > 0 && (
            <p className="text-xs text-muted-foreground text-center mt-3">
              AI agents are negotiating with sellers. Deals will appear here as they are agreed.
            </p>
          )}
        </div>
      )}

      {rfq.status === 'CONFIRMED' && (
        <AsyncPollingStatus status="CONFIRMED" />
      )}

      {/* Confirm Start All Negotiations Dialog — x402 cost warning */}
      <ConfirmDialog
        open={confirmStartOpen}
        onOpenChange={setConfirmStartOpen}
        title="Start AI Negotiations"
        description={`Each AI negotiation offer requires a micropayment of 0.01 ALGO from your connected wallet. With ${matches.length} matched seller${matches.length > 1 ? 's' : ''} and up to 15 rounds each, estimated max cost is ${(matches.length * 15 * 0.01).toFixed(2)} ALGO. Proceed?`}
        confirmLabel="Start Negotiations"
        onConfirm={() => {
          onStartNegotiations();
          setConfirmStartOpen(false);
        }}
        isLoading={isStartingNegotiations}
      />

      {/* Accept Deal Dialog */}
      <ConfirmDialog
        open={!!acceptTarget}
        onOpenChange={(open) => { if (!open) setAcceptTarget(null); }}
        title="Accept Deal"
        description={`Accept the deal with ${acceptTarget?.enterprise_name}? This will confirm this seller and close all other negotiations. The deal will proceed to escrow.`}
        confirmLabel="Accept Deal"
        onConfirm={() => {
          if (acceptTarget) {
            onAcceptDeal(acceptTarget);
            setAcceptTarget(null);
          }
        }}
        isLoading={isAcceptingDeal}
      />
    </div>
  );
}
