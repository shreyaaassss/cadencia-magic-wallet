'use client';

import * as React from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Landmark, CheckCircle2, Clock, Rocket, AlertCircle, Wallet, Package, ExternalLink, Loader2 } from 'lucide-react';
import { toast } from 'sonner';

import { AppShell } from '@/components/layout/AppShell';
import { SectionHeader } from '@/components/shared/SectionHeader';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { Button } from '@/components/ui/button';
import { AuthGuard } from '@/components/shared/AuthGuard';

import { useAuth } from '@/hooks/useAuth';
import { useWalletContext } from '@/context/WalletContext';
import { api } from '@/lib/api';
import { formatCurrency, formatDate } from '@/lib/utils';
import type { NegotiationSession, Escrow } from '@/types';

function TxLink({ txId, type = 'tx' }: { txId: string | number | null; type?: 'tx' | 'app' }) {
  if (!txId) return <span className="text-muted-foreground">—</span>;
  const base = 'https://lora.algokit.io/testnet';
  const url = type === 'app' ? `${base}/application/${txId}` : `${base}/transaction/${txId}`;
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-mono text-xs text-primary hover:underline">
      {String(txId).slice(0, 12)}...
      <ExternalLink className="h-3 w-3" />
    </a>
  );
}

export default function EscrowPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const { isBuyer, isSeller, enterprise } = useAuth();
  const { signAndSubmitFundTxn, activeAddress, isWalletConnected, linkedAddress } = useWalletContext();

  // If navigated from a specific negotiation, scope deals to that RFQ
  const sessionParam = searchParams.get('session');

  // ─── Fetch sessions (AGREED ones for buyer deal selection) ───────────────
  // ESC-04: graceful 401 handling — treat as empty, trigger token refresh via interceptor
  const { data: sessions = [] } = useQuery<NegotiationSession[]>({
    queryKey: ['sessions'],
    queryFn: () =>
      api.get('/v1/sessions').then(r => r.data.data).catch(err => {
        if (err?.response?.status === 401) return [];
        throw err;
      }),
    refetchInterval: 5000,
    retry: 1,
  });

  // ─── Fetch all escrows ──────────────────────────────────────────────────
  // ESC-04: graceful 401/404 handling — seller may have no escrows yet
  const { data: escrows = [], isLoading: escrowsLoading, isError: escrowsError } = useQuery<Escrow[]>({
    queryKey: ['escrows'],
    queryFn: () =>
      api.get('/v1/escrow').then(r => r.data.data).catch(err => {
        if (err?.response?.status === 401 || err?.response?.status === 404) return [];
        throw err;
      }),
    refetchInterval: 5000,
    retry: 1,
  });

  // Agreed sessions the buyer can still select.
  // Rules:
  //   1. Must be AGREED and not already have an escrow
  //   2. Must NOT belong to an RFQ where another session was already selected
  //      (once one deal is picked, all competing deals for that RFQ are hidden)
  const agreedWithoutEscrow = React.useMemo(() => {
    const escrowSessionIds = new Set(escrows.map(e => e.session_id));

    // RFQ IDs that already have at least one session promoted to escrow
    const rfqsWithSelectedDeal = new Set(
      sessions
        .filter(s => escrowSessionIds.has(s.session_id))
        .map(s => s.rfq_id)
        .filter(Boolean),
    );

    const agreed = sessions.filter(
      s =>
        s.status === 'AGREED' &&
        !escrowSessionIds.has(s.session_id) &&
        !rfqsWithSelectedDeal.has(s.rfq_id),
    );

    // If we came from a specific session, scope to only that RFQ's deals
    if (sessionParam) {
      const sourceSession = sessions.find(s => s.session_id === sessionParam);
      if (sourceSession) {
        return agreed.filter(s => s.rfq_id === sourceSession.rfq_id);
      }
    }
    return agreed;
  }, [sessions, escrows, sessionParam]);

  // ─── Select Deal (buyer picks one) ──────────────────────────────────────
  const selectDealMutation = useMutation({
    mutationFn: async (sessionId: string) => {
      const res = await api.post('/v1/escrow/select-deal', { session_id: sessionId });
      return res.data.data;
    },
    onSuccess: (data) => {
      toast.success(data.message);
      queryClient.invalidateQueries({ queryKey: ['escrows'] });
      queryClient.invalidateQueries({ queryKey: ['sessions'] });
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || 'Failed to select deal');
    },
  });

  // ─── Seller Approve Deal ────────────────────────────────────────────────
  const sellerApproveMutation = useMutation({
    mutationFn: async (escrowId: string) => {
      const res = await api.post(`/v1/escrow/${escrowId}/seller-approve`);
      return res.data.data;
    },
    onSuccess: (data) => {
      toast.success(data.message);
      queryClient.invalidateQueries({ queryKey: ['escrows'] });
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || 'Failed to approve deal');
    },
  });

  // ─── Buyer Fund via Magic embedded wallet (no silent fallback) ─────────
  const fundMutation = useMutation({
    mutationFn: async (escrowId: string) => {
      // Require wallet LINKED to Cadencia platform (not just connected to Pera).
      // A connected-but-unlinked wallet means we have no authoritative address to
      // compare against, so a leaked Pera session from a previous user (e.g. the
      // seller) could silently sign fund transactions with the wrong account.
      if (!linkedAddress) {
        throw new Error(
          'Link your wallet first. Go to Settings → Wallet, connect your Algorand wallet, and click "Link Wallet".'
        );
      }
      if (!isWalletConnected || !activeAddress) {
        throw new Error(
          'Your Magic wallet is not ready. Log in again or open Settings → Wallet.'
        );
      }
      // Hard address check: connected wallet MUST match the enterprise-linked wallet.
      // signTxns() also enforces this, but catching it here gives a clearer UX error.
      if (activeAddress !== linkedAddress) {
        throw new Error(
          `Wrong wallet connected. Your enterprise is linked to ${linkedAddress.slice(0, 8)}... — ` +
          'log out and sign in again with the correct email.'
        );
      }
      return signAndSubmitFundTxn(escrowId);
    },
    onSuccess: () => {
      toast.success('Escrow funded! Transaction submitted to Algorand.');
      queryClient.invalidateQueries({ queryKey: ['escrows'] });
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || err?.message || 'Failed to fund escrow');
    },
  });


  // ─── Seller Dispatch Order ──────────────────────────────────────────────
  const sellerDispatchMutation = useMutation({
    mutationFn: async (escrowId: string) => {
      const res = await api.post(`/v1/escrow/${escrowId}/seller-dispatch`);
      return res.data.data;
    },
    onSuccess: (data) => {
      toast.success(data.message);
      queryClient.invalidateQueries({ queryKey: ['escrows'] });
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || 'Failed to mark order as dispatched');
    },
  });

  // ─── Buyer Confirm Delivery ────────────────────────────────────────────
  const buyerConfirmMutation = useMutation({
    mutationFn: async (escrowId: string) => {
      const res = await api.post(`/v1/escrow/${escrowId}/buyer-confirm`);
      return res.data.data;
    },
    onSuccess: (data) => {
      toast.success(data.message);
      queryClient.invalidateQueries({ queryKey: ['escrows'] });
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || 'Failed to confirm delivery');
    },
  });

  // ─── Stepper component ─────────────────────────────────────────────────
  const steps = ['Deal Selected', 'Seller Approved', 'Contract Deployed', 'Buyer Funded', 'Order Dispatched', 'Delivery Confirmed'];
  const getStepIndex = (status: string) => {
    switch (status) {
      case 'PENDING_APPROVAL': return 0;
      case 'APPROVED': return 1;
      case 'DEPLOYED': return 2;
      case 'FUNDED': return 3;
      case 'DISPATCHED': return 4;
      case 'RELEASED': return 5;
      default: return -1;
    }
  };

  return (
    <AppShell>
      <AuthGuard>
        <div className="p-6 space-y-8">

          {/* Header */}
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
              <Landmark className="h-6 w-6 text-primary" />
              Escrow & Payments
            </h1>
            <p className="text-muted-foreground mt-1">
              {isBuyer ? 'Select a deal, fund the escrow, and track your payment.' : 'Accept deals, confirm delivery, and receive payment.'}
            </p>
          </div>

          {/* ── BUYER: Select a Deal ──────────────────────────────────────── */}
          {isBuyer && agreedWithoutEscrow.length > 0 && (
            <div className="bg-card border border-border rounded-lg p-6">
              <SectionHeader title="Select a Deal" description="Pick ONE agreed negotiation to proceed with payment" />
              <div className="space-y-3 mt-4">
                {agreedWithoutEscrow.map(s => (
                  <div key={s.session_id} className="flex items-center justify-between border border-border rounded-lg p-4 hover:bg-accent/50 transition-colors">
                    <div className="flex-1">
                      <p className="text-sm font-medium text-foreground">
                        {s.seller_name || s.seller_enterprise_id.slice(0, 12)}
                      </p>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        Agreed at <span className="font-semibold text-foreground">{formatCurrency(s.agreed_price || 0)}</span> in {s.round_count} rounds
                      </p>
                    </div>
                    <Button
                      size="sm"
                      onClick={() => selectDealMutation.mutate(s.session_id)}
                      disabled={selectDealMutation.isPending}
                      className="bg-primary text-primary-foreground hover:bg-primary/90"
                    >
                      {selectDealMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Select This Deal'}
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ── Active Escrows ────────────────────────────────────────────── */}
          {escrows.length > 0 && (
            <div className="space-y-6">
              {escrows.map(escrow => {
                const stepIdx = getStepIndex(escrow.status);
                const session = sessions.find(s => s.session_id === escrow.session_id);
                const isMyBuyerEscrow = isBuyer && String(enterprise?.id) !== String(escrow.seller_algorand_address);
                const isMySellerEscrow = isSeller;

                return (
                  <div key={escrow.escrow_id} className="bg-card border border-border rounded-lg overflow-hidden">
                    {/* Escrow Header */}
                    <div className="px-6 py-4 border-b border-border flex items-center justify-between">
                      <div>
                        <p className="text-sm font-semibold text-foreground">
                          {escrow.buyer_name || 'Buyer'} &rarr; {escrow.seller_name || 'Seller'}
                        </p>
                        <p className="text-xs text-muted-foreground mt-0.5">
                          {escrow.amount_algo} ALGO &middot; Session {escrow.session_id.slice(0, 8)}
                        </p>
                      </div>
                      <StatusBadge status={escrow.status} />
                    </div>

                    {/* Progress Stepper */}
                    <div className="px-6 py-5">
                      <div className="flex items-center justify-between mb-6">
                        {steps.map((label, idx) => {
                          const done = idx <= stepIdx;
                          const active = idx === stepIdx;
                          return (
                            <div key={label} className="flex flex-col items-center flex-1">
                              <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold border-2 transition-colors ${done ? 'bg-primary border-primary text-primary-foreground' : active ? 'border-primary text-primary' : 'border-muted text-muted-foreground'}`}>
                                {done && idx < stepIdx ? <CheckCircle2 className="h-4 w-4" /> : idx + 1}
                              </div>
                              <span className={`text-[10px] mt-1.5 text-center leading-tight ${done ? 'text-foreground font-medium' : 'text-muted-foreground'}`}>{label}</span>
                            </div>
                          );
                        })}
                      </div>

                      {/* Action Buttons */}
                      <div className="flex items-center justify-center gap-3">

                        {/* Seller: Accept Deal */}
                        {escrow.status === 'PENDING_APPROVAL' && isSeller && (
                          <Button
                            onClick={() => sellerApproveMutation.mutate(escrow.escrow_id)}
                            disabled={sellerApproveMutation.isPending}
                            className="bg-green-600 hover:bg-green-700 text-white"
                          >
                            {sellerApproveMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CheckCircle2 className="mr-2 h-4 w-4" />}
                            Accept Deal
                          </Button>
                        )}
                        {escrow.status === 'PENDING_APPROVAL' && isBuyer && (
                          <div className="flex items-center gap-2 text-amber-500">
                            <Clock className="h-4 w-4 animate-pulse" />
                            <span className="text-sm">Waiting for seller to accept...</span>
                          </div>
                        )}

                        {/* Buyer: Fund Escrow — requires Magic wallet linked */}
                        {escrow.status === 'DEPLOYED' && isBuyer && (
                          isWalletConnected ? (
                            <Button
                              onClick={() => fundMutation.mutate(escrow.escrow_id)}
                              disabled={fundMutation.isPending}
                              className="bg-primary hover:bg-primary/90 text-primary-foreground"
                            >
                              {fundMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Wallet className="mr-2 h-4 w-4" />}
                              Fund via Magic Wallet
                            </Button>
                          ) : (
                            <div className="flex flex-col items-center gap-2">
                              <p className="text-xs text-amber-400">Connect your wallet to fund this escrow</p>
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => router.push('/settings/wallet')}
                                className="border-amber-500 text-amber-400 hover:bg-amber-500/10"
                              >
                                <Wallet className="mr-2 h-4 w-4" />
                                Connect Wallet
                              </Button>
                            </div>
                          )
                        )}
                        {escrow.status === 'DEPLOYED' && isSeller && (
                          <div className="flex items-center gap-2 text-indigo-400">
                            <Rocket className="h-4 w-4" />
                            <span className="text-sm">Contract deployed. Waiting for buyer to fund...</span>
                          </div>
                        )}

                        {/* Seller: Mark Order Dispatched */}
                        {escrow.status === 'FUNDED' && isSeller && (
                          <Button
                            onClick={() => sellerDispatchMutation.mutate(escrow.escrow_id)}
                            disabled={sellerDispatchMutation.isPending}
                            className="bg-blue-600 hover:bg-blue-700 text-white"
                          >
                            {sellerDispatchMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Package className="mr-2 h-4 w-4" />}
                            Mark Order Dispatched
                          </Button>
                        )}
                        {escrow.status === 'FUNDED' && isBuyer && (
                          <div className="flex items-center gap-2 text-green-500">
                            <CheckCircle2 className="h-4 w-4" />
                            <span className="text-sm">Funded! Waiting for seller to dispatch order...</span>
                          </div>
                        )}

                        {/* Buyer: Confirm Delivery (after seller dispatched) */}
                        {escrow.status === 'DISPATCHED' && isBuyer && (
                          <Button
                            onClick={() => buyerConfirmMutation.mutate(escrow.escrow_id)}
                            disabled={buyerConfirmMutation.isPending}
                            className="bg-green-600 hover:bg-green-700 text-white"
                          >
                            {buyerConfirmMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CheckCircle2 className="mr-2 h-4 w-4" />}
                            Confirm Delivery — Release Funds
                          </Button>
                        )}
                        {escrow.status === 'DISPATCHED' && isSeller && (
                          <div className="flex items-center gap-2 text-blue-400">
                            <Package className="h-4 w-4" />
                            <span className="text-sm">Order dispatched. Waiting for buyer to confirm delivery...</span>
                          </div>
                        )}

                        {/* Released */}
                        {escrow.status === 'RELEASED' && (
                          <div className="flex items-center gap-2 text-green-500">
                            <CheckCircle2 className="h-5 w-5" />
                            <span className="text-sm font-medium">Trade Complete! Funds released to seller.</span>
                          </div>
                        )}

                        {/* Rejected */}
                        {escrow.status === 'REJECTED' && (
                          <div className="flex items-center gap-2 text-destructive">
                            <AlertCircle className="h-4 w-4" />
                            <span className="text-sm">Escrow rejected.</span>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Transaction Details */}
                    {(escrow.deploy_tx_id || escrow.fund_tx_id || escrow.release_tx_id) && (
                      <div className="px-6 py-3 border-t border-border bg-muted/20">
                        <div className="flex flex-wrap gap-4 text-xs">
                          {escrow.algo_app_id && (
                            <span className="text-muted-foreground">Contract: <TxLink txId={escrow.algo_app_id} type="app" /></span>
                          )}
                          {escrow.deploy_tx_id && (
                            <span className="text-muted-foreground">Deploy TX: <TxLink txId={escrow.deploy_tx_id} /></span>
                          )}
                          {escrow.fund_tx_id && (
                            <span className="text-muted-foreground">Fund TX: <TxLink txId={escrow.fund_tx_id} /></span>
                          )}
                          {escrow.release_tx_id && (
                            <span className="text-muted-foreground">Release TX: <TxLink txId={escrow.release_tx_id} /></span>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Empty State */}
          {!escrowsLoading && escrows.length === 0 && agreedWithoutEscrow.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="bg-muted p-4 rounded-full mb-4">
                <Landmark className="h-8 w-8 text-muted-foreground" />
              </div>
              <h3 className="font-medium text-foreground">No Escrows Yet</h3>
              <p className="text-sm text-muted-foreground mt-1 max-w-sm">
                {isBuyer
                  ? 'Complete negotiations first, then select a deal to start the payment process.'
                  : 'Escrows will appear here when buyers select your deals.'}
              </p>
            </div>
          )}

        </div>
      </AuthGuard>
    </AppShell>
  );
}
