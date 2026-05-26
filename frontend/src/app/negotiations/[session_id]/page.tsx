'use client';

import * as React from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { useQuery, useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  Play, FastForward, UserCog, StopCircle, ArrowLeft, Circle,
  AlertTriangle, CheckCircle2, XCircle, Loader2, ArrowRight,
  BarChart2, X,
} from 'lucide-react';

import { AppShell } from '@/components/layout/AppShell';
import { SectionHeader } from '@/components/shared/SectionHeader';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { NegotiationTimeline } from '@/components/shared/NegotiationTimeline';
import { PriceConvergenceChart } from '@/components/shared/PriceConvergenceChart';
import { HumanOverridePanel } from '@/components/shared/HumanOverridePanel';
import { ConfirmDialog } from '@/components/shared/ConfirmDialog';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';

import { useAuth } from '@/hooks/useAuth';
import { useSSE } from '@/hooks/useSSE';
import { api } from '@/lib/api';
import { formatCurrency, cn } from '@/lib/utils';
import { ROUTES } from '@/lib/constants';
import type { NegotiationSession, NegotiationOffer, SessionStatus } from '@/types';

const INITIAL_OFFERS: NegotiationOffer[] = [];

// ── Gap meter ──────────────────────────────────────────────────────────────
function GapMeter({ buyerOffers, sellerOffers }: { buyerOffers: number[]; sellerOffers: number[] }) {
  const lastBuyer = buyerOffers[buyerOffers.length - 1] ?? null;
  const lastSeller = sellerOffers[sellerOffers.length - 1] ?? null;
  if (!lastBuyer || !lastSeller) return null;

  const gap = Math.abs(lastSeller - lastBuyer) / Math.min(lastBuyer, lastSeller) * 100;
  const gapColor = gap <= 2 ? 'text-green-600' : gap <= 5 ? 'text-emerald-600' : gap <= 10 ? 'text-amber-600' : 'text-red-600';
  const barColor = gap <= 2 ? 'bg-green-500' : gap <= 5 ? 'bg-emerald-500' : gap <= 10 ? 'bg-amber-500' : 'bg-red-500';
  const fillPct = Math.max(0, 100 - gap * 5);

  return (
    <div className="flex items-center gap-3 bg-secondary/50 border border-border rounded-lg px-4 py-2.5 mt-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground min-w-0 flex-1">
        <span className="font-mono font-semibold text-blue-600 shrink-0">{formatCurrency(lastSeller)}</span>
        <span className="text-muted-foreground/40 shrink-0">Seller</span>

        <div className="flex-1 flex items-center gap-1 min-w-[80px] mx-1">
          <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
            <div
              className={cn('h-full rounded-full transition-all duration-700', barColor)}
              style={{ width: `${fillPct}%`, marginLeft: `${(100 - fillPct) / 2}%` }}
            />
          </div>
        </div>

        <span className="text-muted-foreground/40 shrink-0">Buyer</span>
        <span className="font-mono font-semibold text-emerald-600 shrink-0">{formatCurrency(lastBuyer)}</span>
      </div>
      <div className={cn('shrink-0 font-bold tabular-nums text-sm px-2 py-0.5 rounded border', gapColor,
        gap <= 2 ? 'bg-green-50 border-green-200' :
        gap <= 5 ? 'bg-emerald-50 border-emerald-200' :
        gap <= 10 ? 'bg-amber-50 border-amber-200' : 'bg-red-50 border-red-200'
      )}>
        {gap.toFixed(1)}% gap
      </div>
    </div>
  );
}

export default function NegotiationRoomPage() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const sessionId = params.session_id as string;
  const autoStart = searchParams.get('auto') === 'true';
  const { enterprise } = useAuth();
  const enterpriseId = enterprise?.id;

  const [offers, setOffers] = React.useState<NegotiationOffer[]>(INITIAL_OFFERS);
  const [sessionStatus, setSessionStatus] = React.useState<SessionStatus>('ACTIVE');
  const [stallWarning, setStallWarning] = React.useState(false);
  const [agreedPrice, setAgreedPrice] = React.useState<number | null>(null);
  const [showOverride, setShowOverride] = React.useState(false);
  const [showLeaveDialog, setShowLeaveDialog] = React.useState(false);
  const [showEndDialog, setShowEndDialog] = React.useState(false);
  const [showChart, setShowChart] = React.useState(false);
  // SSE: suppress "Connecting..." flash — only show after 1.5s delay
  const [showConnecting, setShowConnecting] = React.useState(false);

  const { data: session } = useQuery<NegotiationSession>({
    queryKey: ['session', sessionId],
    queryFn: () => api.get(`/v1/sessions/${sessionId}`).then(r => r.data.data),
    enabled: !!sessionId,
  });

  // Sync from fetched session (REST snapshot — no flash)
  React.useEffect(() => {
    if (session) {
      setSessionStatus(session.status);
      if (session.agreed_price) setAgreedPrice(session.agreed_price);
      if (session.offers && session.offers.length > 0) {
        setOffers(session.offers);
      }
    }
  }, [session]);

  const { isConnected } = useSSE({
    sessionId,
    enabled: sessionStatus === 'ACTIVE',
    onEvent: (event, data: any) => {
      switch (event) {
        case 'new_offer':
          setOffers(prev => {
            // Deduplicate by round+role
            const key = `${data.offer.round_number}-${data.offer.proposer_role}`;
            const exists = prev.some(o => `${o.round_number}-${o.proposer_role}` === key);
            return exists ? prev : [...prev, data.offer];
          });
          break;
        case 'session_agreed':
          setSessionStatus('AGREED');
          setAgreedPrice(data.agreed_price);
          toast.success(`Deal agreed at ${formatCurrency(data.agreed_price)}!`);
          break;
        case 'session_failed':
          setSessionStatus('FAILED');
          toast.error(`Negotiation ended: ${data.reason ?? 'Max rounds reached'}`);
          break;
        case 'stall_detected':
          setStallWarning(true);
          toast.warning('Negotiation stalled — consider manual override');
          break;
      }
    },
  });

  // Only show "Connecting..." banner if SSE hasn't connected after 1.5s
  React.useEffect(() => {
    if (isConnected) { setShowConnecting(false); return; }
    const t = setTimeout(() => setShowConnecting(true), 1500);
    return () => clearTimeout(t);
  }, [isConnected]);

  const nextTurnMutation = useMutation({
    mutationFn: () => api.post(`/v1/sessions/${sessionId}/turn`),
    onSuccess: () => toast.success('Next turn triggered'),
    onError: () => toast.error('Failed to trigger next turn'),
  });

  const overrideMutation = useMutation({
    mutationFn: (offer: { price: number; terms: Record<string, string> }) =>
      api.post(`/v1/sessions/${sessionId}/override`, offer),
    onSuccess: () => { toast.success('Human override submitted'); setShowOverride(false); },
    onError: () => toast.error('Failed to submit override'),
  });

  const terminateMutation = useMutation({
    mutationFn: () => api.post(`/v1/sessions/${sessionId}/terminate`),
    onSuccess: () => { toast.success('Session terminated'); setSessionStatus('TERMINATED'); setShowEndDialog(false); },
    onError: () => toast.error('Failed to terminate session'),
  });

  const autoNegotiateMutation = useMutation({
    mutationFn: (maxRounds: number) =>
      api.post(`/v1/sessions/${sessionId}/run-auto?max_rounds=${maxRounds}`),
    onSuccess: (res) => {
      const data = res.data.data;
      if (data.final_status === 'AGREED') {
        setSessionStatus('AGREED');
        setAgreedPrice(data.session?.agreed_price ?? null);
        toast.success(`Deal agreed at ${formatCurrency(data.session?.agreed_price ?? 0)}!`);
      } else if (data.terminal) {
        setSessionStatus(data.final_status as SessionStatus);
        toast.info(`Negotiation ended: ${data.final_status}`);
      }
      if (data.offers_this_run?.length && offers.length === 0) {
        setOffers(data.session?.offers ?? []);
      }
    },
    onError: () => toast.error('Auto-negotiation encountered an error'),
  });

  const autoStartedRef = React.useRef(false);
  React.useEffect(() => {
    if (autoStart && session && session.status === 'ACTIVE' && !autoStartedRef.current) {
      autoStartedRef.current = true;
      autoNegotiateMutation.mutate(20);
    }
  }, [autoStart, session]);

  const buyerOffers = offers.filter(o => o.proposer_role === 'BUYER').map(o => o.price);
  const sellerOffers = offers.filter(o => o.proposer_role === 'SELLER').map(o => o.price);
  const latestRound = offers.length > 0 ? offers[offers.length - 1].round_number : (session?.round_count ?? 0);
  const maxRounds = 20;
  const isActive = sessionStatus === 'ACTIVE';
  const isEnded = ['AGREED','FAILED','TIMEOUT','WALK_AWAY','POLICY_BREACH','TERMINATED'].includes(sessionStatus);

  const isYouBuyer = session?.buyer_enterprise_id === enterpriseId;
  const yourRole = isYouBuyer ? 'Buyer' : 'Seller';
  const opponent = isYouBuyer ? session?.seller_name : session?.buyer_name;

  return (
    <AppShell>
      <div className="p-4 md:p-6 max-w-4xl mx-auto">

        {/* ── Header ────────────────────────────────────────────────────────── */}
        <div className="bg-secondary border border-border rounded-xl p-5 mb-5">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              {/* Title row */}
              <div className="flex flex-wrap items-center gap-2.5 mb-1">
                <h1 className="text-sm font-mono text-muted-foreground truncate">
                  {sessionId?.slice(0, 8)}…
                </h1>
                <StatusBadge status={sessionStatus} />
                <div className="flex items-center gap-1.5">
                  {isConnected ? (
                    <><Circle className="h-2 w-2 fill-green-500 text-green-600" /><span className="text-xs text-green-600 font-medium">Live</span></>
                  ) : (
                    <><Circle className="h-2 w-2 fill-amber-500/50 text-amber-500 animate-pulse" /><span className="text-xs text-muted-foreground">Syncing</span></>
                  )}
                </div>
              </div>

              {/* Participants */}
              <p className="text-sm text-foreground font-medium mb-1">
                <span className="text-emerald-600">You ({yourRole})</span>
                <span className="mx-2 text-muted-foreground">↔</span>
                <span className="text-blue-600">{opponent ?? '—'}</span>
              </p>

              {/* Round progress */}
              <div className="flex items-center gap-3 flex-wrap">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">Round</span>
                  <span className="text-sm font-mono font-bold text-foreground">{latestRound}</span>
                  <span className="text-xs text-muted-foreground">/ {maxRounds}</span>
                </div>
                <div className="flex-1 max-w-[120px] bg-muted rounded-full h-1.5">
                  <div
                    className="h-full rounded-full bg-primary transition-all duration-500"
                    style={{ width: `${(latestRound / maxRounds) * 100}%` }}
                  />
                </div>
                {agreedPrice && (
                  <span className="text-sm text-green-600 font-semibold">
                    ✓ {formatCurrency(agreedPrice)}
                  </span>
                )}
              </div>

              {/* Gap meter */}
              <GapMeter buyerOffers={buyerOffers} sellerOffers={sellerOffers} />
            </div>

            <div className="flex items-center gap-2 shrink-0 flex-wrap">
              {/* Chart toggle button */}
              {offers.length >= 2 && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowChart(true)}
                  className="text-xs gap-1.5 border-border hover:bg-accent"
                >
                  <BarChart2 className="h-3.5 w-3.5" />
                  Price Chart
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowLeaveDialog(true)}
                className="text-muted-foreground hover:text-foreground hover:bg-accent"
              >
                <ArrowLeft className="h-4 w-4 mr-1.5" />
                Leave
              </Button>
            </div>
          </div>
        </div>

        {/* ── Banners ───────────────────────────────────────────────────────── */}
        {showConnecting && isActive && !autoNegotiateMutation.isPending && (
          <div className="flex items-center gap-3 bg-muted/30 border border-border rounded-lg p-3 mb-4 text-xs text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin shrink-0" />
            Connecting to live feed…
          </div>
        )}

        {autoNegotiateMutation.isPending && (
          <div className="flex items-center gap-3 bg-primary/5 border border-primary/20 rounded-lg p-3 mb-4">
            <Loader2 className="h-4 w-4 text-primary animate-spin shrink-0" />
            <div>
              <p className="text-sm font-medium text-foreground">AI Negotiation in Progress</p>
              <p className="text-xs text-muted-foreground">Agents are exchanging offers — offers appear in real time below.</p>
            </div>
          </div>
        )}

        {sessionStatus === 'AGREED' && (
          <div className="flex items-center gap-3 bg-green-50 border border-green-200 rounded-lg p-4 mb-4">
            <CheckCircle2 className="h-5 w-5 text-green-600 shrink-0" />
            <div className="flex-1">
              <p className="text-sm font-semibold text-green-600">Deal Agreed</p>
              <p className="text-xs text-muted-foreground">Final price: {formatCurrency(agreedPrice ?? 0)}</p>
            </div>
            <Button size="sm" onClick={() => router.push(`/escrow?session=${sessionId}`)}
              className="bg-green-600 hover:bg-green-700 text-white text-xs">
              Proceed to Escrow <ArrowRight className="h-3.5 w-3.5 ml-1" />
            </Button>
          </div>
        )}

        {(sessionStatus === 'FAILED' || sessionStatus === 'WALK_AWAY') && (
          <div className="flex items-center gap-3 bg-red-50 border border-red-200 rounded-lg p-4 mb-4">
            <XCircle className="h-5 w-5 text-destructive shrink-0" />
            <div>
              <p className="text-sm font-semibold text-destructive">
                {sessionStatus === 'WALK_AWAY' ? 'Agent Walked Away' : 'Negotiation Failed'}
              </p>
              <p className="text-xs text-muted-foreground">
                {sessionStatus === 'WALK_AWAY'
                  ? 'No agreement was reached — prices did not converge.'
                  : 'Maximum rounds reached without agreement.'}
              </p>
            </div>
          </div>
        )}

        {stallWarning && isActive && (
          <div className="flex items-center gap-3 bg-amber-50 border border-amber-200 rounded-lg p-4 mb-4">
            <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0" />
            <div className="flex-1">
              <p className="text-sm font-semibold text-amber-600">Stall Detected</p>
              <p className="text-xs text-muted-foreground">Agents have not made meaningful concessions — consider manual override.</p>
            </div>
            <Button size="sm" onClick={() => { setShowOverride(true); setStallWarning(false); }}
              className="ml-auto bg-amber-700 hover:bg-amber-600 text-white text-xs">
              Override
            </Button>
          </div>
        )}

        {/* ── Chat timeline ─────────────────────────────────────────────────── */}
        <div className="bg-card border border-border rounded-xl p-4 mb-4">
          <div className="flex items-center justify-between mb-4 pb-3 border-b border-border">
            <div>
              <h2 className="text-sm font-semibold text-foreground">Live Negotiation</h2>
              <p className="text-xs text-muted-foreground mt-0.5">{offers.length} offers exchanged</p>
            </div>
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-blue-600 inline-block" />
                Seller
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-600 inline-block" />
                Buyer
              </span>
            </div>
          </div>
          <div className="max-h-[560px] overflow-y-auto pr-1 scroll-smooth">
            <NegotiationTimeline offers={offers} sessionStatus={sessionStatus} />
          </div>
        </div>

        {/* ── Actions ───────────────────────────────────────────────────────── */}
        {!isEnded && (
          <div className="bg-card border border-border rounded-xl p-4 mb-4">
            <div className="flex flex-wrap items-center justify-center gap-3">
              <Button
                onClick={() => autoNegotiateMutation.mutate(20)}
                disabled={autoNegotiateMutation.isPending || nextTurnMutation.isPending || !isActive}
                className="bg-primary text-primary-foreground hover:bg-primary/90 px-6 font-semibold"
              >
                {autoNegotiateMutation.isPending ? (
                  <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Negotiating...</>
                ) : (
                  <><FastForward className="h-4 w-4 mr-2" />Auto-Negotiate</>
                )}
              </Button>
              <Button variant="outline" onClick={() => nextTurnMutation.mutate()}
                disabled={nextTurnMutation.isPending || autoNegotiateMutation.isPending || !isActive}
                className="border-border hover:bg-accent">
                <Play className="h-4 w-4 mr-2" />Next Round
              </Button>
              <Button variant="ghost" onClick={() => setShowOverride(!showOverride)} className="hover:bg-accent">
                <UserCog className="h-4 w-4 mr-2" />Override
              </Button>
              <Button variant="outline" onClick={() => setShowEndDialog(true)}
                className="text-destructive border-destructive/40 hover:bg-red-50">
                <StopCircle className="h-4 w-4 mr-2" />End
              </Button>
            </div>
          </div>
        )}

        {/* ── Human Override ─────────────────────────────────────────────────── */}
        {showOverride && !isEnded && (
          <div className="bg-muted/50 border border-border rounded-xl p-5 mb-4 animate-in fade-in slide-in-from-top-2 duration-200">
            <SectionHeader title="Human Override" description="Submit a manual price to override the AI agent" />
            <HumanOverridePanel
              onSubmit={(offer) => overrideMutation.mutate(offer)}
              isSubmitting={overrideMutation.isPending}
            />
          </div>
        )}

        {/* ── Price Chart Modal ─────────────────────────────────────────────── */}
        <Dialog open={showChart} onOpenChange={setShowChart}>
          <DialogContent className="max-w-3xl w-full bg-card border-border">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2 text-foreground">
                <BarChart2 className="h-5 w-5 text-primary" />
                Price Movement — {offers.length} offers
              </DialogTitle>
            </DialogHeader>
            <div className="mt-2">
              <PriceConvergenceChart buyerOffers={buyerOffers} sellerOffers={sellerOffers} />
            </div>
            <p className="text-xs text-muted-foreground text-center mt-2">
              Shaded region shows Zone of Possible Agreement (ZOPA). Hover dots for exact prices.
            </p>
          </DialogContent>
        </Dialog>

        {/* ── Dialogs ───────────────────────────────────────────────────────── */}
        <ConfirmDialog
          open={showLeaveDialog} onOpenChange={setShowLeaveDialog}
          title="Leave Negotiation Room"
          description="The negotiation continues in the background. You can return anytime."
          confirmLabel="Leave"
          onConfirm={() => router.push(ROUTES.NEGOTIATIONS)}
        />
        <ConfirmDialog
          open={showEndDialog} onOpenChange={setShowEndDialog}
          title="End Negotiation Session"
          description="This will permanently terminate the session. Cannot be undone."
          confirmLabel="Terminate" variant="destructive"
          onConfirm={() => terminateMutation.mutate()}
          isLoading={terminateMutation.isPending}
        />
      </div>
    </AppShell>
  );
}
