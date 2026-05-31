'use client';

import * as React from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { useQuery, useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  Play, FastForward, UserCog, StopCircle, ArrowLeft, ArrowRight,
  AlertTriangle, CheckCircle2, XCircle, Loader2, BarChart2,
} from 'lucide-react';

import { AppShell } from '@/components/layout/AppShell';
import { NegotiationTimeline } from '@/components/shared/NegotiationTimeline';
import { PriceConvergenceChart } from '@/components/shared/PriceConvergenceChart';
import { HumanOverridePanel } from '@/components/shared/HumanOverridePanel';
import { ConfirmDialog } from '@/components/shared/ConfirmDialog';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';

import { useAuth } from '@/hooks/useAuth';
import { useSSE } from '@/hooks/useSSE';
import { api } from '@/lib/api';
import { formatCurrency, cn } from '@/lib/utils';
import { ROUTES } from '@/lib/constants';
import type { NegotiationSession, NegotiationOffer, SessionStatus } from '@/types';

// ── Gap meter ─────────────────────────────────────────────────────────────────
function GapMeter({ buyerOffers, sellerOffers }: { buyerOffers: number[]; sellerOffers: number[] }) {
  const lastBuyer = buyerOffers[buyerOffers.length - 1] ?? null;
  const lastSeller = sellerOffers[sellerOffers.length - 1] ?? null;
  if (!lastBuyer || !lastSeller) return null;

  const gap = Math.abs(lastSeller - lastBuyer) / Math.min(lastBuyer, lastSeller) * 100;
  const gapCls = gap <= 2 ? 'gap-tight' : gap <= 5 ? 'gap-close' : gap <= 10 ? 'gap-medium' : 'gap-wide';
  const barBg = gap <= 5 ? '#5ab98a' : gap <= 10 ? '#c9a05a' : '#c96b5a';
  const fillPct = Math.max(5, Math.min(90, 100 - gap * 4));
  const leftPct = (100 - fillPct) / 2;

  return (
    <div className="nego-gap-row">
      <span className="nego-gap-price nego-seller">{formatCurrency(lastSeller)}</span>
      <div className="nego-gap-bar-track">
        <div className="nego-gap-bar-fill"
          style={{ background: barBg, width: `${fillPct}%`, left: `${leftPct}%` }} />
      </div>
      <span className="nego-gap-price nego-buyer">{formatCurrency(lastBuyer)}</span>
      <span className={cn('nego-gap-pct', gapCls)}>{gap.toFixed(1)}% gap</span>
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

  const [offers, setOffers] = React.useState<NegotiationOffer[]>([]);
  const [sessionStatus, setSessionStatus] = React.useState<SessionStatus>('ACTIVE');
  const [stallWarning, setStallWarning] = React.useState(false);
  const [agreedPrice, setAgreedPrice] = React.useState<number | null>(null);
  const [showOverride, setShowOverride] = React.useState(false);
  const [showLeaveDialog, setShowLeaveDialog] = React.useState(false);
  const [showEndDialog, setShowEndDialog] = React.useState(false);
  const [showChart, setShowChart] = React.useState(false);
  const [showConnecting, setShowConnecting] = React.useState(false);

  const { data: session } = useQuery<NegotiationSession>({
    queryKey: ['session', sessionId],
    queryFn: () => api.get(`/v1/sessions/${sessionId}`).then(r => r.data.data),
    enabled: !!sessionId,
  });

  React.useEffect(() => {
    if (session) {
      setSessionStatus(session.status);
      if (session.agreed_price) setAgreedPrice(session.agreed_price);
      if (session.offers?.length) setOffers(session.offers);
    }
  }, [session]);

  const { isConnected } = useSSE({
    sessionId,
    enabled: sessionStatus === 'ACTIVE',
    onEvent: (event, data: any) => {
      switch (event) {
        case 'new_offer':
          setOffers(prev => {
            const key = `${data.offer.round_number}-${data.offer.proposer_role}`;
            return prev.some(o => `${o.round_number}-${o.proposer_role}` === key) ? prev : [...prev, data.offer];
          });
          break;
        case 'session_agreed':
          setSessionStatus('AGREED'); setAgreedPrice(data.agreed_price);
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
    mutationFn: (maxRounds: number) => api.post(`/v1/sessions/${sessionId}/run-auto?max_rounds=${maxRounds}`),
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

  const statusLabel: Record<string, string> = {
    ACTIVE: 'Active', AGREED: 'Agreed', FAILED: 'Not Selected',
    WALK_AWAY: 'Not Selected', TIMEOUT: 'Timed Out',
    POLICY_BREACH: 'Policy Breach', TERMINATED: 'Terminated',
  };

  return (
    <AppShell>
      {/* ── Negotiation Room CSS ────────────────────────────────────────────── */}
      <style>{`
        /* ── Base tokens matching HTML design ─────────────────────────────── */
        .nego-room {
          max-width: 860px;
          margin: 0 auto;
          padding: 1.5rem 1rem 5rem;
          font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
        }

        /* ── Session header card ──────────────────────────────────────────── */
        .nego-header {
          border-radius: 1.25rem;
          overflow: hidden;
          margin-bottom: 0.875rem;
          background: hsl(var(--card));
          border: 1px solid hsl(var(--border));
        }

        /* Top strip */
        .nego-strip {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 0.625rem 1.25rem;
          border-bottom: 1px solid hsl(var(--border));
          background: hsl(var(--muted) / 0.5);
          flex-wrap: wrap;
          gap: 0.5rem;
        }
        .nego-strip-left { display: flex; align-items: center; gap: 0.75rem; }
        .nego-session-id {
          font-family: "JetBrains Mono", monospace;
          font-size: 0.6875rem;
          color: hsl(var(--muted-foreground));
          letter-spacing: 0.04em;
        }
        .nego-strip-actions { display: flex; gap: 0.5rem; align-items: center; }

        /* Status pill */
        .nego-status-pill {
          display: inline-flex; align-items: center; gap: 0.375rem;
          font-size: 0.625rem; font-weight: 600; letter-spacing: 0.1em;
          text-transform: uppercase; padding: 0.2rem 0.625rem;
          border-radius: 999px; border: 1px solid;
        }
        .nego-status-pill.active {
          color: #16a34a; background: rgba(22,163,74,.1); border-color: rgba(22,163,74,.3);
        }
        .dark .nego-status-pill.active {
          color: #5ab98a; background: rgba(90,185,138,.1); border-color: rgba(90,185,138,.25);
        }
        .nego-status-pill.agreed {
          color: #0a2e0e; background: rgba(10,46,14,.1); border-color: rgba(10,46,14,.25);
        }
        .dark .nego-status-pill.agreed {
          color: #5ab98a; background: rgba(90,185,138,.1); border-color: rgba(90,185,138,.3);
        }
        .nego-status-pill.failed, .nego-status-pill.walk_away {
          color: #aa2d00; background: rgba(170,45,0,.1); border-color: rgba(170,45,0,.25);
        }
        .dark .nego-status-pill.failed, .dark .nego-status-pill.walk_away {
          color: #c96b5a; background: rgba(201,107,90,.1); border-color: rgba(201,107,90,.3);
        }
        .nego-status-pill.stalled, .nego-status-pill.timeout {
          color: #92400e; background: rgba(146,64,14,.1); border-color: rgba(146,64,14,.25);
        }
        .dark .nego-status-pill.stalled, .dark .nego-status-pill.timeout {
          color: #c9a05a; background: rgba(201,160,90,.1); border-color: rgba(201,160,90,.3);
        }
        .nego-live-dot {
          width: 5px; height: 5px; border-radius: 50%;
          background: #16a34a;
          box-shadow: 0 0 5px #16a34a;
          animation: nego-pulse 2s ease-in-out infinite;
        }
        .dark .nego-live-dot { background: #5ab98a; box-shadow: 0 0 5px #5ab98a; }

        /* Body */
        .nego-body { padding: 1.125rem 1.25rem 1rem; }

        /* Participants line */
        .nego-participants {
          font-size: 1.375rem; font-weight: 300; line-height: 1.3;
          margin-bottom: 1rem;
          color: hsl(var(--foreground));
        }
        .nego-buyer-name { color: #0a7847; }
        .dark .nego-buyer-name { color: #6bbf9e; }
        .nego-seller-name { color: #1b61c9; }
        .dark .nego-seller-name { color: #7aaedf; }
        .nego-sep { color: hsl(var(--muted-foreground)); padding: 0 0.5rem; font-style: italic; }

        /* Stats row */
        .nego-stats-row {
          display: flex; align-items: stretch; flex-wrap: wrap;
          border: 1px solid hsl(var(--border));
          border-radius: 0.875rem; overflow: hidden;
        }
        .nego-stat-cell {
          flex: 1; min-width: 100px;
          padding: 0.625rem 1rem;
          border-right: 1px solid hsl(var(--border));
        }
        .nego-stat-cell:last-child { border-right: none; }
        .nego-stat-label {
          font-size: 0.5625rem; font-weight: 600; letter-spacing: 0.1em;
          text-transform: uppercase; color: hsl(var(--muted-foreground));
          margin-bottom: 0.25rem;
        }
        .nego-stat-val {
          font-family: "JetBrains Mono", monospace;
          font-size: 0.9rem; font-weight: 500;
          color: hsl(var(--foreground));
        }
        .nego-stat-val.accent { color: #181d26; }
        .dark .nego-stat-val.accent { color: #e8c99a; }

        /* Round progress bar */
        .nego-round-track {
          height: 3px; background: hsl(var(--muted)); border-radius: 999px;
          overflow: hidden; margin-top: 0.4rem;
        }
        .nego-round-fill {
          height: 100%; border-radius: 999px;
          background: #181d26; transition: width 0.6s cubic-bezier(.4,0,.2,1);
        }
        .dark .nego-round-fill { background: #e8c99a; }

        /* Gap meter */
        .nego-gap-row {
          display: flex; align-items: center; gap: 0.625rem;
          flex: 2; min-width: 200px;
          padding: 0.5rem 0;
        }
        .nego-gap-price {
          font-family: "JetBrains Mono", monospace;
          font-size: 0.8125rem; font-weight: 600;
          white-space: nowrap;
        }
        .nego-seller { color: #1b61c9; }
        .dark .nego-seller { color: #7aaedf; }
        .nego-buyer  { color: #0a7847; }
        .dark .nego-buyer  { color: #6bbf9e; }
        .nego-gap-bar-track {
          flex: 1; height: 3px; background: hsl(var(--muted));
          border-radius: 999px; position: relative; overflow: hidden;
        }
        .nego-gap-bar-fill {
          position: absolute; height: 100%; border-radius: 999px;
          transition: all 0.6s ease;
        }
        .nego-gap-pct {
          font-family: "JetBrains Mono", monospace;
          font-size: 0.6875rem; font-weight: 600;
          padding: 0.125rem 0.375rem; border-radius: 0.3rem; border: 1px solid;
          white-space: nowrap;
        }
        .gap-tight  { color:#15803d; background:rgba(21,128,61,.08);  border-color:rgba(21,128,61,.25); }
        .gap-close  { color:#16a34a; background:rgba(22,163,74,.07);  border-color:rgba(22,163,74,.2); }
        .gap-medium { color:#b45309; background:rgba(180,83,9,.08);   border-color:rgba(180,83,9,.25); }
        .gap-wide   { color:#aa2d00; background:rgba(170,45,0,.08);   border-color:rgba(170,45,0,.25); }
        .dark .gap-tight  { color:#5ab98a; background:rgba(90,185,138,.1);  border-color:rgba(90,185,138,.25); }
        .dark .gap-close  { color:#5ab98a; background:rgba(90,185,138,.07); border-color:rgba(90,185,138,.2); }
        .dark .gap-medium { color:#c9a05a; background:rgba(201,160,90,.08); border-color:rgba(201,160,90,.25); }
        .dark .gap-wide   { color:#c96b5a; background:rgba(201,107,90,.08); border-color:rgba(201,107,90,.25); }

        /* ── Banners ────────────────────────────────────────────────────────── */
        .nego-banner {
          display: flex; align-items: flex-start; gap: 0.875rem;
          border-radius: 0.875rem; padding: 0.875rem 1.125rem;
          margin-bottom: 0.875rem; border: 1px solid;
        }
        .nego-banner-info    { background:rgba(27,97,201,.04); border-color:rgba(27,97,201,.2); }
        .nego-banner-success { background:rgba(10,46,14,.06);  border-color:rgba(10,46,14,.2); }
        .nego-banner-warning { background:rgba(180,83,9,.05);  border-color:rgba(180,83,9,.22); }
        .nego-banner-error   { background:rgba(170,45,0,.05);  border-color:rgba(170,45,0,.22); }
        .dark .nego-banner-info    { background:rgba(122,174,223,.04); border-color:rgba(122,174,223,.2); }
        .dark .nego-banner-success { background:rgba(90,185,138,.04);  border-color:rgba(90,185,138,.2); }
        .dark .nego-banner-warning { background:rgba(201,160,90,.04);  border-color:rgba(201,160,90,.2); }
        .dark .nego-banner-error   { background:rgba(201,107,90,.04);  border-color:rgba(201,107,90,.2); }
        .nego-banner-title {
          font-size: 0.9375rem; font-weight: 500; margin-bottom: 0.125rem;
        }
        .nego-banner-info    .nego-banner-title { color: #1b61c9; }
        .nego-banner-success .nego-banner-title { color: #0a2e0e; }
        .nego-banner-warning .nego-banner-title { color: #92400e; }
        .nego-banner-error   .nego-banner-title { color: #aa2d00; }
        .dark .nego-banner-info    .nego-banner-title { color: #7aaedf; }
        .dark .nego-banner-success .nego-banner-title { color: #5ab98a; }
        .dark .nego-banner-warning .nego-banner-title { color: #c9a05a; }
        .dark .nego-banner-error   .nego-banner-title { color: #c96b5a; }
        .nego-banner-desc { font-size: 0.75rem; color: hsl(var(--muted-foreground)); }

        /* ── Chat card ──────────────────────────────────────────────────────── */
        .nego-chat-card {
          background: hsl(var(--card)); border: 1px solid hsl(var(--border));
          border-radius: 1.25rem; overflow: hidden; margin-bottom: 0.875rem;
        }
        .nego-chat-head {
          display: flex; align-items: center; justify-content: space-between;
          padding: 0.875rem 1.25rem;
          border-bottom: 1px solid hsl(var(--border));
        }
        .nego-chat-title {
          font-size: 1.0625rem; font-weight: 500;
          color: hsl(var(--foreground));
        }
        .nego-chat-sub { font-size: 0.6875rem; color: hsl(var(--muted-foreground)); margin-top: 0.125rem; }
        .nego-legend { display: flex; gap: 1rem; align-items: center; }
        .nego-legend-item { display: flex; align-items: center; gap: 0.375rem; font-size: 0.6875rem; color: hsl(var(--muted-foreground)); }
        .nego-legend-dot { width: 6px; height: 6px; border-radius: 50%; }
        .nego-chat-feed {
          max-height: 580px; overflow-y: auto;
          padding: 1.25rem; scroll-behavior: smooth;
        }
        .nego-chat-feed::-webkit-scrollbar { width: 3px; }
        .nego-chat-feed::-webkit-scrollbar-track { background: transparent; }
        .nego-chat-feed::-webkit-scrollbar-thumb { background: hsl(var(--border)); border-radius: 999px; }

        /* ── Action bar ─────────────────────────────────────────────────────── */
        .nego-action-bar {
          background: hsl(var(--card)); border: 1px solid hsl(var(--border));
          border-radius: 1.25rem; padding: 0.875rem 1.25rem;
          margin-bottom: 0.875rem;
        }
        .nego-action-buttons {
          display: flex; flex-wrap: wrap; align-items: center;
          justify-content: center; gap: 0.625rem;
        }

        /* ── Override panel ─────────────────────────────────────────────────── */
        .nego-override {
          background: hsl(var(--card)); border: 1px solid hsl(var(--border));
          border-radius: 1.25rem; padding: 1.125rem 1.25rem;
          margin-bottom: 0.875rem;
        }
        .nego-override h3 {
          font-size: 1.0625rem; font-weight: 500;
          color: hsl(var(--foreground)); margin-bottom: 0.25rem;
        }
        .nego-override p { font-size: 0.75rem; color: hsl(var(--muted-foreground)); margin-bottom: 0.875rem; }

        /* Animations */
        @keyframes nego-pulse { 0%,100%{opacity:1} 50%{opacity:.3} }
      `}</style>

      <div className="nego-room">

        {/* ── Session Header ───────────────────────────────────────────────── */}
        <div className="nego-header">
          {/* Top strip */}
          <div className="nego-strip">
            <div className="nego-strip-left">
              <span className="nego-session-id">{sessionId?.slice(0, 8)}…{sessionId?.slice(-4)}</span>
              <span className={cn('nego-status-pill', sessionStatus.toLowerCase().replace('_', ''))}>
                {isActive && <span className="nego-live-dot" />}
                {statusLabel[sessionStatus] ?? sessionStatus}
              </span>
              {isActive && (
                <span className="text-[10px] text-muted-foreground">
                  {isConnected ? '● Live' : '○ Syncing'}
                </span>
              )}
            </div>
            <div className="nego-strip-actions">
              {offers.length >= 2 && (
                <button
                  className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground px-2.5 py-1.5 rounded-lg border border-border hover:bg-accent transition-colors"
                  onClick={() => setShowChart(true)}
                >
                  <BarChart2 className="h-3.5 w-3.5" /> Chart
                </button>
              )}
              <button
                className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground px-2.5 py-1.5 rounded-lg border border-border hover:bg-accent transition-colors"
                onClick={() => setShowLeaveDialog(true)}
              >
                <ArrowLeft className="h-3.5 w-3.5" /> Leave
              </button>
            </div>
          </div>

          {/* Body */}
          <div className="nego-body">
            {/* Participants */}
            <div className="nego-participants">
              <span className="nego-buyer-name">You ({yourRole})</span>
              <span className="nego-sep">×</span>
              <span className="nego-seller-name">{opponent ?? '—'}</span>
            </div>

            {/* Stats row */}
            <div className="nego-stats-row">
              {/* Round */}
              <div className="nego-stat-cell">
                <div className="nego-stat-label">Round</div>
                <div className="nego-stat-val accent">
                  {latestRound} <span style={{ color: 'hsl(var(--muted-foreground))', fontSize: '0.75rem', fontWeight: 400 }}>/ {maxRounds}</span>
                </div>
                <div className="nego-round-track">
                  <div className="nego-round-fill" style={{ width: `${(latestRound / maxRounds) * 100}%` }} />
                </div>
              </div>

              {/* Offers */}
              <div className="nego-stat-cell">
                <div className="nego-stat-label">Offers</div>
                <div className="nego-stat-val">{offers.length} exchanged</div>
              </div>

              {/* Gap meter — spans remaining space */}
              <div className="nego-stat-cell" style={{ flex: 2, minWidth: 200 }}>
                <div className="nego-stat-label">Price Gap</div>
                <GapMeter buyerOffers={buyerOffers} sellerOffers={sellerOffers} />
                {!buyerOffers.length && !sellerOffers.length && (
                  <div className="nego-stat-val text-muted-foreground" style={{ fontSize: '0.75rem' }}>Awaiting first offers</div>
                )}
              </div>

              {/* Agreed price if settled */}
              {agreedPrice && (
                <div className="nego-stat-cell">
                  <div className="nego-stat-label">Agreed</div>
                  <div className="nego-stat-val" style={{ color: '#0a7847', fontWeight: 700 }}>
                    {formatCurrency(agreedPrice)}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── Banners ──────────────────────────────────────────────────────── */}
        {showConnecting && isActive && !autoNegotiateMutation.isPending && (
          <div className="nego-banner nego-banner-info">
            <Loader2 className="h-4 w-4 animate-spin shrink-0 mt-0.5 text-blue-600 dark:text-[#7aaedf]" />
            <div>
              <p className="nego-banner-title">Connecting to live feed</p>
              <p className="nego-banner-desc">Establishing real-time connection to negotiation stream.</p>
            </div>
          </div>
        )}

        {autoNegotiateMutation.isPending && (
          <div className="nego-banner nego-banner-info">
            <Loader2 className="h-4 w-4 animate-spin shrink-0 mt-0.5 text-blue-600 dark:text-[#7aaedf]" />
            <div>
              <p className="nego-banner-title">AI negotiation in progress</p>
              <p className="nego-banner-desc">Agents are exchanging offers in real time.</p>
            </div>
          </div>
        )}

        {sessionStatus === 'AGREED' && (
          <div className="nego-banner nego-banner-success">
            <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5" style={{ color: '#0a7847' }} />
            <div className="flex-1">
              <p className="nego-banner-title">Deal agreed</p>
              <p className="nego-banner-desc">Final price: {formatCurrency(agreedPrice ?? 0)} · Ready for on-chain settlement.</p>
            </div>
            <Button size="sm" onClick={() => router.push(`/escrow?session=${sessionId}`)}
              className="shrink-0 text-xs bg-[#0a2e0e] text-white hover:bg-[#0a2e0e]/90 border-0">
              Proceed to escrow <ArrowRight className="h-3 w-3 ml-1" />
            </Button>
          </div>
        )}

        {(sessionStatus === 'FAILED' || sessionStatus === 'WALK_AWAY') && (
          <div className="nego-banner nego-banner-error">
            <XCircle className="h-4 w-4 shrink-0 mt-0.5" style={{ color: '#aa2d00' }} />
            <div>
              <p className="nego-banner-title">Not selected</p>
              <p className="nego-banner-desc">
                Another seller was chosen for this order. This negotiation has been closed.
              </p>
            </div>
          </div>
        )}

        {stallWarning && isActive && (
          <div className="nego-banner nego-banner-warning">
            <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" style={{ color: '#92400e' }} />
            <div className="flex-1">
              <p className="nego-banner-title">Stall detected</p>
              <p className="nego-banner-desc">Agents have not made meaningful concessions — consider a manual override.</p>
            </div>
            <Button size="sm" onClick={() => { setShowOverride(true); setStallWarning(false); }}
              className="shrink-0 text-xs border border-border bg-transparent hover:bg-accent text-foreground">
              Override
            </Button>
          </div>
        )}

        {/* ── Chat Card ─────────────────────────────────────────────────────── */}
        <div className="nego-chat-card">
          <div className="nego-chat-head">
            <div>
              <div className="nego-chat-title">Live Negotiation</div>
              <div className="nego-chat-sub">{offers.length} offer{offers.length !== 1 ? 's' : ''} exchanged</div>
            </div>
            <div className="nego-legend">
              <div className="nego-legend-item">
                <span className="nego-legend-dot" style={{ background: '#1b61c9' }} />
                Seller
              </div>
              <div className="nego-legend-item">
                <span className="nego-legend-dot" style={{ background: '#0a7847' }} />
                Buyer
              </div>
            </div>
          </div>
          <div className="nego-chat-feed">
            <NegotiationTimeline offers={offers} sessionStatus={sessionStatus} />
          </div>
        </div>

        {/* ── Action Bar ────────────────────────────────────────────────────── */}
        {!isEnded && (
          <div className="nego-action-bar">
            <div className="nego-action-buttons">
              <Button
                onClick={() => autoNegotiateMutation.mutate(20)}
                disabled={autoNegotiateMutation.isPending || nextTurnMutation.isPending || !isActive}
                className="bg-[#181d26] text-white hover:bg-[#0d1218] dark:bg-[#e8c99a] dark:text-[#0e0d0b] dark:hover:bg-[#f0d5a8] px-5 font-semibold border-0"
              >
                {autoNegotiateMutation.isPending ? (
                  <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Negotiating…</>
                ) : (
                  <><FastForward className="h-4 w-4 mr-2" />Auto-Negotiate</>
                )}
              </Button>
              <Button variant="outline" onClick={() => nextTurnMutation.mutate()}
                disabled={nextTurnMutation.isPending || autoNegotiateMutation.isPending || !isActive}
                className="border-border hover:bg-accent">
                <Play className="h-4 w-4 mr-2" />Next Round
              </Button>
              <Button variant="ghost" onClick={() => setShowOverride(!showOverride)}
                className="hover:bg-accent text-muted-foreground hover:text-foreground">
                <UserCog className="h-4 w-4 mr-2" />Override
              </Button>
              <Button variant="outline" onClick={() => setShowEndDialog(true)}
                className="text-destructive border-destructive/40 hover:bg-red-50 dark:hover:bg-[rgba(201,107,90,.07)]">
                <StopCircle className="h-4 w-4 mr-2" />End
              </Button>
            </div>
          </div>
        )}

        {/* ── Override Panel ────────────────────────────────────────────────── */}
        {showOverride && !isEnded && (
          <div className="nego-override animate-in fade-in slide-in-from-top-2 duration-200">
            <h3>Human Override</h3>
            <p>Submit a manual price to override the AI agent for the next round.</p>
            <HumanOverridePanel
              onSubmit={(offer) => overrideMutation.mutate(offer)}
              isSubmitting={overrideMutation.isPending}
            />
          </div>
        )}

        {/* ── Chart Modal ───────────────────────────────────────────────────── */}
        <Dialog open={showChart} onOpenChange={setShowChart}>
          <DialogContent className="max-w-3xl w-full bg-card border-border">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2 text-foreground">
                <BarChart2 className="h-5 w-5" />
                Price Convergence — {offers.length} offers
              </DialogTitle>
            </DialogHeader>
            <div className="mt-2">
              <PriceConvergenceChart buyerOffers={buyerOffers} sellerOffers={sellerOffers} />
            </div>
            <p className="text-xs text-muted-foreground text-center mt-2">
              Shaded region shows Zone of Possible Agreement (ZOPA).
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
