'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Plus, RotateCcw, FileText, ChevronDown, Loader2, Pencil, AlertTriangle } from 'lucide-react';

import { AppShell } from '@/components/layout/AppShell';
import { SectionHeader } from '@/components/shared/SectionHeader';
import { DataTable } from '@/components/shared/DataTable';
import { StatusBadge } from '@/components/shared/StatusBadge';
// TextareaWithButton removed — draft step now uses inline textarea + two buttons
import { RfqDetailPanel } from '@/components/shared/RfqDetailPanel';
import { Button } from '@/components/ui/button';
import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';

import { api } from '@/lib/api';
import { formatDate } from '@/lib/utils';
import { ROUTES } from '@/lib/constants';
import type { RFQ, SellerMatch } from '@/types';

const STATUS_OPTIONS = ['All', 'DRAFT', 'PARSE_FAILED', 'PARSED', 'MATCHED', 'NEGOTIATING', 'CONFIRMED'] as const;

export default function MarketplacePage() {
  const router = useRouter();
  const queryClient = useQueryClient();

  // ─── State ──────────────────────────────────────────────────────────────────
  const [formExpanded, setFormExpanded] = React.useState(false);
  const [rfqText, setRfqText] = React.useState('');
  const [selectedRfqId, setSelectedRfqId] = React.useState<string | null>(null);
  const [filter, setFilter] = React.useState<string>('All');
  const [mobileSheetOpen, setMobileSheetOpen] = React.useState(false);

  // ─── AI Preview wizard state ──────────────────────────────────────────────
  const [wizardStep, setWizardStep] = React.useState<'draft' | 'preview' | 'confirm'>('draft');
  const [previewData, setPreviewData] = React.useState<any>(null);
  const [userOverrides, setUserOverrides] = React.useState<Record<string, any>>({});

  // ─── x402 auto-negotiation state ────────────────────────────────────────────
  const [autoNegSessionIds, setAutoNegSessionIds] = React.useState<string[]>([]);
  const [x402TotalSpent, setX402TotalSpent] = React.useState(0);
  const autoNegAbortRef = React.useRef(false);

  // Active FSM states the frontend considers "still running"
  const _ACTIVE_STATES = ['ACTIVE', 'INIT', 'SELLER_ANCHOR', 'BUYER_RESPONSE',
    'BUYER_ANCHOR', 'SELLER_RESPONSE', 'ROUND_LOOP'];

  const runAutoNegotiateForSession = React.useCallback(async (sid: string) => {
    const maxTurns = 30;
    for (let i = 0; i < maxTurns; i++) {
      if (autoNegAbortRef.current) break;
      try {
        const sesRes = await api.get(`/v1/sessions/${sid}`);
        const st = sesRes.data.data?.status;
        if (!_ACTIVE_STATES.includes(st)) break;
        // Execute turn — axios interceptor handles x402 payment silently
        await api.post(`/v1/sessions/${sid}/turn`);
        setX402TotalSpent(prev => +(prev + 0.01).toFixed(4));
      } catch (err: any) {
        if (err.message?.includes('[x402]')) {
          toast.error(`Wallet error: ${err.message}`);
          break;
        }
        if (err.response?.status === 409) break;
        break;
      }
      await new Promise(r => setTimeout(r, 2000));
    }
  }, []);

  // ─── Market Overview ────────────────────────────────────────────────────────
  const { data: marketOverview } = useQuery<any>({
    queryKey: ['market-overview'],
    queryFn: () => api.get('/v1/marketplace/market-overview').then(r => r.data.data),
    staleTime: 60_000,
  });

  // ─── Fetch all RFQs from API ───────────────────────────────────────────────
  const { data: allRfqs = [], isLoading: rfqsLoading } = useQuery<RFQ[]>({
    queryKey: ['rfqs'],
    queryFn: () => api.get('/v1/marketplace/rfqs').then(r => r.data.data as RFQ[]),
    refetchInterval: 5000,
  });

  // ─── Filter ─────────────────────────────────────────────────────────────────
  const filteredRfqs = React.useMemo(() => {
    if (filter === 'All') return allRfqs;
    return allRfqs.filter(r => r.status === filter);
  }, [allRfqs, filter]);

  // ─── Pagination (10 per page) ────────────────────────────────────────────────
  const PAGE_SIZE = 10;
  const [rfqPage, setRfqPage] = React.useState(1);
  const totalRfqPages = Math.max(1, Math.ceil(filteredRfqs.length / PAGE_SIZE));
  const pagedRfqs = filteredRfqs.slice((rfqPage - 1) * PAGE_SIZE, rfqPage * PAGE_SIZE);
  React.useEffect(() => { setRfqPage(1); }, [filter]);

  // ─── Selected RFQ ──────────────────────────────────────────────────────────
  const selectedRfq = allRfqs.find(r => r.id === selectedRfqId) ?? null;

  // ─── Matches for selected RFQ ──────────────────────────────────────────────
  const { data: matches = [], isLoading: matchesLoading } = useQuery<SellerMatch[]>({
    queryKey: ['rfq', selectedRfqId, 'matches'],
    queryFn: () => api.get(`/v1/marketplace/rfq/${selectedRfqId}/matches`).then(r => r.data.data),
    enabled: !!selectedRfqId && (selectedRfq?.status === 'MATCHED' || selectedRfq?.status === 'NEGOTIATING'),
  });

  // ─── Negotiation sessions for NEGOTIATING RFQs ────────────────────────────
  const { data: negotiations = [] } = useQuery<any[]>({
    queryKey: ['rfq', selectedRfqId, 'negotiations'],
    queryFn: () => api.get('/v1/sessions').then(r => {
      const sessions = r.data.data || [];
      // Filter sessions linked to this RFQ
      return sessions.filter((s: any) => String(s.rfq_id) === selectedRfqId);
    }),
    enabled: !!selectedRfqId && selectedRfq?.status === 'NEGOTIATING',
    refetchInterval: 5000,
  });

  // ─── Polling for DRAFT/PARSED RFQs ────────────────────────────────────────
  React.useEffect(() => {
    const hasPendingRfqs = allRfqs.some(r => ['DRAFT', 'PARSED', 'PARSE_FAILED'].includes(r.status));
    if (!hasPendingRfqs) return;

    const interval = setInterval(() => {
      queryClient.invalidateQueries({ queryKey: ['rfqs'] });
    }, 3000);

    return () => clearInterval(interval);
  }, [allRfqs, queryClient]);

  // ─── Submit new RFQ ────────────────────────────────────────────────────────
  const submitMutation = useMutation({
    mutationFn: async (rawText: string) => {
      const res = await api.post('/v1/marketplace/rfq', { raw_text: rawText });
      return res.data.data as { rfq_id: string; status: string };
    },
    onSuccess: (data) => {
      toast.success(`RFQ submitted! ID: ${data.rfq_id}`);
      setRfqText('');
      setFormExpanded(false);
      setSelectedRfqId(data.rfq_id);
      // Invalidate to refetch the full list
      queryClient.invalidateQueries({ queryKey: ['rfqs'] });
    },
    onError: () => {
      toast.error('Failed to submit RFQ');
    },
  });

  // ─── AI Preview mutation ────────────────────────────────────────────────────
  const previewMutation = useMutation({
    mutationFn: async (rawText: string) => {
      const res = await api.post('/v1/marketplace/rfq/ai-preview', { raw_text: rawText });
      return res.data.data;
    },
    onSuccess: (data) => {
      setPreviewData(data);
      setUserOverrides({});
      setWizardStep('preview');
    },
    onError: (err: any) => {
      if (err.response?.status === 503) {
        toast.info('AI preview unavailable — submitting directly');
        submitMutation.mutate(rfqText);
      } else {
        toast.error('AI preview failed');
      }
    },
  });

  const handleConfirmSubmit = React.useCallback(() => {
    // Append user overrides to raw text as natural-language additions
    const overrideLines: string[] = [];
    if (userOverrides.product) overrideLines.push(`Product: ${userOverrides.product}`);
    if (userOverrides.quantity) overrideLines.push(`Quantity: ${userOverrides.quantity} ${userOverrides.quantity_unit || ''}`);
    if (userOverrides.quantity_unit && !userOverrides.quantity) overrideLines.push(`Unit: ${userOverrides.quantity_unit}`);
    if (userOverrides.budget_max) overrideLines.push(`Total budget: INR ${userOverrides.budget_max}`);
    if (userOverrides.delivery_window_days) overrideLines.push(`Delivery within ${userOverrides.delivery_window_days} days`);
    const finalText = overrideLines.length > 0
      ? `${rfqText}\n\nAdditional details: ${overrideLines.join('. ')}.`
      : rfqText;
    submitMutation.mutate(finalText);
    setWizardStep('draft');
    setPreviewData(null);
  }, [rfqText, userOverrides, submitMutation]);

  // ─── Start all negotiations (x402 per-turn payments via client-side loop) ───
  const startNegotiationsMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post(`/v1/marketplace/rfq/${selectedRfqId}/start-negotiations`);
      return res.data.data as { session_ids: string[]; message: string };
    },
    onSuccess: async (data) => {
      const sids = data.session_ids;
      setAutoNegSessionIds(sids);
      setX402TotalSpent(0);
      autoNegAbortRef.current = false;
      toast.success(`${sids.length} sessions created — AI negotiation starting...`);
      queryClient.invalidateQueries({ queryKey: ['rfqs'] });
      queryClient.invalidateQueries({ queryKey: ['rfq', selectedRfqId, 'negotiations'] });
      queryClient.invalidateQueries({ queryKey: ['sessions'] });

      // Run client-side auto-negotiate for each session (staggered by 3s)
      const promises = sids.map((sid, i) =>
        new Promise<void>(resolve => {
          setTimeout(async () => {
            await runAutoNegotiateForSession(sid);
            resolve();
          }, i * 3000);
        })
      );
      await Promise.all(promises);

      // All sessions done
      setAutoNegSessionIds([]);
      toast.success('All negotiations complete');
      queryClient.invalidateQueries({ queryKey: ['rfqs'] });
      queryClient.invalidateQueries({ queryKey: ['sessions'] });
    },
    onError: () => {
      toast.error('Failed to start negotiations');
    },
  });

  // ─── Accept best deal (confirm) ──────────────────────────────────────────
  const confirmMutation = useMutation({
    mutationFn: async (match: SellerMatch) => {
      const res = await api.post(`/v1/marketplace/rfq/${selectedRfqId}/confirm`, {
        seller_enterprise_id: match.enterprise_id,
      });
      return res.data.data as { session_id: string };
    },
    onSuccess: (data) => {
      toast.success('Deal accepted! Proceeding to escrow.');
      queryClient.invalidateQueries({ queryKey: ['rfqs'] });
      router.push(`${ROUTES.ESCROW}`);
    },
    onError: () => {
      toast.error('Failed to accept deal');
    },
  });

  // ─── Retry parsing for PARSE_FAILED RFQs ──────────────────────────────────
  const retryParseMutation = useMutation({
    mutationFn: async (rfqId: string) => {
      const rfq = allRfqs.find(r => r.id === rfqId);
      const res = await api.put(`/v1/marketplace/rfq/${rfqId}`, {
        raw_text: rfq?.raw_text,
      });
      return res.data.data;
    },
    onSuccess: (_data, rfqId) => {
      toast.success(`Retrying parse for RFQ #${rfqId}`);
      queryClient.invalidateQueries({ queryKey: ['rfqs'] });
    },
    onError: () => {
      toast.error('Failed to retry parsing');
    },
  });

  // ─── Row click handler ─────────────────────────────────────────────────────
  const handleRowClick = (rfq: RFQ) => {
    setSelectedRfqId(rfq.id);
    // On mobile open sheet
    if (window.innerWidth < 1024) {
      setMobileSheetOpen(true);
    }
  };

  // ─── Refresh all ───────────────────────────────────────────────────────────
  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ['rfqs'] });
  };

  // ─── Detail content (reused in desktop panel and mobile sheet) ─────────────
  const detailContent = selectedRfq ? (
    <div className="space-y-4">
      {/* PARSE_FAILED warning */}
      {selectedRfq.status === 'PARSE_FAILED' && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 dark:border-amber-700 dark:bg-amber-950/30 p-4">
          <div className="flex items-start gap-2 mb-2">
            <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
            <p className="text-sm font-medium text-amber-800 dark:text-amber-300">Parsing failed</p>
          </div>
          {selectedRfq.parse_error && (
            <p className="text-xs text-amber-700 dark:text-amber-400 mb-3 ml-6">
              {selectedRfq.parse_error}
            </p>
          )}
          <div className="flex gap-2 ml-6">
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs border-amber-400 text-amber-800 hover:bg-amber-100 dark:border-amber-600 dark:text-amber-300 dark:hover:bg-amber-900/50"
              disabled={retryParseMutation.isPending}
              onClick={() => retryParseMutation.mutate(selectedRfq.id)}
            >
              {retryParseMutation.isPending ? (
                <><Loader2 className="h-3 w-3 animate-spin mr-1" />Retrying...</>
              ) : (
                <><RotateCcw className="h-3 w-3 mr-1" />Retry Parsing</>
              )}
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs border-amber-400 text-amber-800 hover:bg-amber-100 dark:border-amber-600 dark:text-amber-300 dark:hover:bg-amber-900/50"
              onClick={() => toast.info('Manual entry — coming soon')}
            >
              <Pencil className="h-3 w-3 mr-1" />Fill In Manually
            </Button>
          </div>
        </div>
      )}

      <RfqDetailPanel
        rfq={selectedRfq}
        matches={matches}
        matchesLoading={matchesLoading}
        negotiations={negotiations}
        onStartNegotiations={() => startNegotiationsMutation.mutate()}
        isStartingNegotiations={startNegotiationsMutation.isPending}
        onAcceptDeal={(match) => confirmMutation.mutate(match)}
        isAcceptingDeal={confirmMutation.isPending}
      />
    </div>
  ) : (
    <div className="flex items-center justify-center h-full py-16">
      <p className="text-sm text-muted-foreground">Select an RFQ to view details</p>
    </div>
  );

  return (
    <AppShell>
      <div className="p-6">

        {/* Market Overview */}
        {marketOverview && (
          <div className="bg-card border border-border rounded-lg p-6 mb-6">
            <h3 className="text-base font-semibold text-foreground mb-4">Market Overview</h3>
            <div className="grid grid-cols-3 gap-4 mb-4">
              <div className="text-center">
                <p className="text-2xl font-bold text-primary">{marketOverview.total_sellers}</p>
                <p className="text-xs text-muted-foreground">Active Sellers</p>
              </div>
              <div className="text-center">
                <p className="text-2xl font-bold text-emerald-600">{marketOverview.total_products}</p>
                <p className="text-xs text-muted-foreground">Products Listed</p>
              </div>
              <div className="text-center">
                <p className="text-2xl font-bold text-violet-600">{marketOverview.industries?.length ?? 0}</p>
                <p className="text-xs text-muted-foreground">Industries</p>
              </div>
            </div>
            {marketOverview.industries?.length > 0 && (
              <div className="space-y-1.5 border-t border-border pt-3">
                {marketOverview.industries.slice(0, 5).map((ind: any) => (
                  <div key={ind.name} className="flex justify-between text-sm">
                    <span className="text-foreground">{ind.name}</span>
                    <span className="text-muted-foreground">{ind.seller_count} seller{ind.seller_count !== 1 ? 's' : ''}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Section 1: New RFQ Form */}
        <div className="bg-card border border-border rounded-lg p-6 mb-8">
          <SectionHeader
            title="Request for Quotation"
            action={{
              label: formExpanded ? 'Cancel' : 'New RFQ',
              icon: formExpanded ? undefined : Plus,
              onClick: () => setFormExpanded(!formExpanded),
            }}
          />
          {formExpanded && (
            <div className="animate-in fade-in slide-in-from-top-2 duration-200">
              {/* Step 1: Draft */}
              {wizardStep === 'draft' && (
                <>
                  <p className="text-sm text-muted-foreground mb-3">
                    Describe your requirement in natural language.
                  </p>
                  <div className="space-y-3">
                    <textarea
                      rows={6}
                      value={rfqText}
                      onChange={(e) => setRfqText(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && rfqText.trim().length > 0) {
                          e.preventDefault();
                          submitMutation.mutate(rfqText);
                        }
                      }}
                      placeholder="Need 500 metric tons of HR Coil, IS 2062 grade, delivery to Mumbai 400001 within 45 days. Budget: ₹38,000-42,000 per MT. 30% advance, 70% on delivery."
                      disabled={submitMutation.isPending || previewMutation.isPending}
                      className="flex w-full rounded-md border border-border bg-input px-3 py-2 text-sm text-foreground ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 resize-vertical"
                    />
                    <div className="flex justify-between items-center">
                      <p className="text-xs text-muted-foreground">Press Ctrl+Enter to submit</p>
                      <div className="flex gap-2">
                        <Button
                          variant="outline"
                          onClick={() => previewMutation.mutate(rfqText)}
                          disabled={rfqText.trim().length === 0 || previewMutation.isPending || submitMutation.isPending}
                          className="border-border"
                        >
                          {previewMutation.isPending ? (
                            <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Enhancing...</>
                          ) : (
                            'Enhance with AI'
                          )}
                        </Button>
                        <Button
                          onClick={() => submitMutation.mutate(rfqText)}
                          disabled={rfqText.trim().length === 0 || submitMutation.isPending || previewMutation.isPending}
                          className="bg-primary text-primary-foreground hover:bg-primary/90"
                        >
                          {submitMutation.isPending ? (
                            <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Submitting...</>
                          ) : (
                            'Submit RFQ'
                          )}
                        </Button>
                      </div>
                    </div>
                  </div>
                </>
              )}

              {/* Step 2: Preview + Completeness */}
              {wizardStep === 'preview' && previewData && (() => {
                const p = { ...previewData.parsed_fields, ...userOverrides };
                const c = previewData.completeness;
                const isMissingT1 = (c.missing_tier1 as string[]).filter(k => !userOverrides[k] && !p[k]);
                const isMissingT2 = (c.missing_tier2 as string[]).filter(k => !userOverrides[k] && !p[k]);
                const canSubmit = isMissingT1.length === 0;
                return (
                  <div className="space-y-4">
                    {/* Zone A: Extracted preview */}
                    <div className="bg-muted/50 border border-border rounded-lg p-4 space-y-2">
                      <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">AI Extracted Fields</p>
                      {p.product && (
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-sm font-semibold text-foreground">{p.product}</span>
                          {p.product_category && <span className="text-xs bg-primary/10 text-primary px-1.5 py-0.5 rounded">{p.product_category}</span>}
                          {p.hsn_code && <span className="text-xs font-mono text-muted-foreground">HSN {p.hsn_code}</span>}
                        </div>
                      )}
                      {p.grade && <p className="text-xs text-muted-foreground">{p.grade}</p>}
                      {(p.quantity || p.budget_max) && (
                        <div className="flex items-center gap-3 text-sm">
                          {p.quantity && <span>{p.quantity} {p.quantity_unit || ''}</span>}
                          {p.budget_per_unit && <span>· ₹{Number(p.budget_per_unit).toLocaleString('en-IN')}/unit</span>}
                          {p.budget_max && <span>· Total ₹{Number(p.budget_max).toLocaleString('en-IN')}</span>}
                          {p.incoterms && <span className="text-xs bg-secondary text-secondary-foreground px-1.5 py-0.5 rounded">{p.incoterms}</span>}
                        </div>
                      )}
                      {(p.delivery_pincode || p.delivery_city || p.delivery_window_days) && (
                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                          {p.delivery_pincode && <span>{p.delivery_pincode}</span>}
                          {p.delivery_city && <span>· {p.delivery_city}{p.delivery_state ? `, ${p.delivery_state}` : ''}</span>}
                          {p.delivery_window_days && <span>· within {p.delivery_window_days} days</span>}
                        </div>
                      )}
                      {p.preferred_payment_terms?.length > 0 && (
                        <div className="flex gap-1 flex-wrap">
                          {p.preferred_payment_terms.map((t: string) => (
                            <span key={t} className="text-xs bg-secondary text-secondary-foreground px-1.5 py-0.5 rounded">{t}</span>
                          ))}
                        </div>
                      )}
                      {p.required_certifications?.length > 0 && (
                        <div className="flex gap-1 flex-wrap">
                          {p.required_certifications.map((c: string) => (
                            <span key={c} className="text-xs bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300 px-1.5 py-0.5 rounded">{c}</span>
                          ))}
                          {p.requires_test_certificate && <span className="text-xs text-green-600">✓ Test cert</span>}
                        </div>
                      )}
                    </div>

                    {/* Zone B: Missing Tier 1 (blocks submission) */}
                    {isMissingT1.length > 0 && (
                      <div className="bg-red-50 dark:bg-red-900/10 border border-red-200 dark:border-red-800/30 rounded-lg p-4">
                        <p className="text-xs font-semibold text-red-700 dark:text-red-400 mb-3">Required — please add:</p>
                        <div className="grid gap-2">
                          {isMissingT1.includes('product') && (
                            <input type="text" placeholder="Product name" className="w-full px-3 py-1.5 text-sm border border-border rounded-md bg-background" value={userOverrides.product || ''} onChange={e => setUserOverrides(o => ({ ...o, product: e.target.value }))} />
                          )}
                          {(isMissingT1.includes('quantity') || isMissingT1.includes('quantity_unit')) && (
                            <div className="flex gap-2">
                              <input type="number" placeholder="Quantity" className="flex-1 px-3 py-1.5 text-sm border border-border rounded-md bg-background" value={userOverrides.quantity || ''} onChange={e => setUserOverrides(o => ({ ...o, quantity: e.target.value }))} />
                              <select className="px-3 py-1.5 text-sm border border-border rounded-md bg-background" value={userOverrides.quantity_unit || ''} onChange={e => setUserOverrides(o => ({ ...o, quantity_unit: e.target.value }))}>
                                <option value="">Unit</option>
                                {['MT', 'KG', 'PIECE', 'LITRE', 'METRE', 'BUNDLE', 'BOX'].map(u => <option key={u} value={u}>{u}</option>)}
                              </select>
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Zone C: Missing Tier 2 (warning, optional) */}
                    {isMissingT2.length > 0 && (
                      <div className="bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-800/30 rounded-lg p-4">
                        <p className="text-xs font-semibold text-amber-700 dark:text-amber-400 mb-3">Add for better matches (optional):</p>
                        <div className="grid gap-2">
                          {isMissingT2.includes('budget_max') && (
                            <input type="number" placeholder="Total budget (₹)" className="w-full px-3 py-1.5 text-sm border border-border rounded-md bg-background" value={userOverrides.budget_max || ''} onChange={e => setUserOverrides(o => ({ ...o, budget_max: e.target.value }))} />
                          )}
                          {isMissingT2.includes('delivery_window_days') && (
                            <input type="number" placeholder="Delivery window (days)" className="w-full px-3 py-1.5 text-sm border border-border rounded-md bg-background" value={userOverrides.delivery_window_days || ''} onChange={e => setUserOverrides(o => ({ ...o, delivery_window_days: e.target.value }))} />
                          )}
                        </div>
                      </div>
                    )}

                    {/* Actions */}
                    <div className="flex gap-3">
                      <Button variant="outline" onClick={() => { setWizardStep('draft'); setPreviewData(null); }} className="border-border">
                        Back to edit
                      </Button>
                      <Button onClick={handleConfirmSubmit} disabled={!canSubmit || submitMutation.isPending} className="bg-primary text-primary-foreground hover:bg-primary/90 flex-1">
                        {submitMutation.isPending ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Submitting...</> : 'Confirm & Submit RFQ'}
                      </Button>
                    </div>
                  </div>
                );
              })()}
            </div>
          )}
        </div>

        {/* Section 2: RFQ List + Detail Panel */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

          {/* Left: RFQ List */}
          <div className="lg:col-span-2">
            <div className="flex items-center justify-between flex-col sm:flex-row gap-3 border-b border-border pb-3 mb-4">
              <h3 className="text-base font-semibold text-foreground">Your RFQs</h3>
              <div className="flex items-center gap-2">
                {/* Filter dropdown */}
                <div className="relative">
                  <select
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    className="appearance-none bg-muted border border-border rounded-md px-3 py-1.5 pr-8 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring cursor-pointer"
                  >
                    {STATUS_OPTIONS.map(opt => (
                      <option key={opt} value={opt}>{opt === 'All' ? 'All' : opt}</option>
                    ))}
                  </select>
                  <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
                </div>

                {/* Refresh */}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleRefresh}
                  className="text-primary hover:bg-secondary"
                >
                  <RotateCcw className="h-3.5 w-3.5 mr-1.5" />
                  Refresh
                </Button>
              </div>
            </div>

            <DataTable<RFQ>
              columns={[
                {
                  key: 'id',
                  label: 'RFQ ID',
                  render: (v) => <span className="text-primary font-mono text-xs">{String(v)}</span>,
                },
                {
                  key: 'raw_text',
                  label: 'Description',
                  render: (v) => {
                    const s = String(v);
                    return (
                      <span className="text-foreground" title={s}>
                        {s.length > 40 ? s.slice(0, 40) + '...' : s}
                      </span>
                    );
                  },
                },
                {
                  key: 'status',
                  label: 'Status',
                  render: (v) => <StatusBadge status={String(v)} />,
                },
                {
                  key: 'created_at',
                  label: 'Created',
                  sortable: true,
                  render: (v) => <span className="text-muted-foreground text-xs">{formatDate(String(v))}</span>,
                },
                {
                  key: '_actions' as any,
                  label: '',
                  render: (_v, row) => {
                    const rfq = row as RFQ;
                    if (!['DRAFT', 'PARSED', 'PARSE_FAILED'].includes(rfq.status)) return null;
                    return (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-muted-foreground hover:text-foreground"
                        onClick={(e) => {
                          e.stopPropagation();
                          toast.info('Edit RFQ — coming soon');
                        }}
                        title="Edit RFQ"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                    );
                  },
                },
              ]}
              data={pagedRfqs}
              isLoading={rfqsLoading}
              keyExtractor={(row) => row.id}
              onRowClick={handleRowClick}
              emptyState={{ icon: FileText, title: 'No RFQs yet', description: 'Submit your first RFQ above' }}
            />
            {totalRfqPages > 1 && (
              <div className="flex items-center justify-between px-1 pt-3 border-t border-border">
                <span className="text-xs text-muted-foreground">
                  Page {rfqPage} of {totalRfqPages} · {filteredRfqs.length} RFQ{filteredRfqs.length !== 1 ? 's' : ''}
                </span>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setRfqPage(p => Math.max(1, p - 1))}
                    disabled={rfqPage === 1}
                  >
                    ← Prev
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setRfqPage(p => Math.min(totalRfqPages, p + 1))}
                    disabled={rfqPage === totalRfqPages}
                  >
                    Next →
                  </Button>
                </div>
              </div>
            )}
          </div>

          {/* Right: Detail Panel (desktop) */}
          <div className="hidden lg:block space-y-4">
            <div className="bg-card border border-border rounded-lg p-5 sticky top-20">
              <h3 className="text-base font-semibold text-foreground border-b border-border pb-3 mb-4">
                {selectedRfq ? `RFQ #${selectedRfq.id}` : 'RFQ Details'}
              </h3>
              {detailContent}
            </div>

            {/* x402 auto-negotiation progress indicator */}
            {autoNegSessionIds.length > 0 && (
              <div className="bg-card border border-border rounded-lg p-5">
                <div className="flex items-center gap-2 mb-2">
                  <Loader2 className="h-4 w-4 animate-spin text-primary" />
                  <h3 className="text-sm font-semibold text-foreground">AI Negotiating...</h3>
                </div>
                <p className="text-xs text-muted-foreground mb-2">
                  {autoNegSessionIds.length} session{autoNegSessionIds.length > 1 ? 's' : ''} in progress
                </p>
                <p className="text-xs font-mono text-primary">
                  {x402TotalSpent.toFixed(2)} ALGO spent
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Mobile Sheet for Detail Panel */}
        <Sheet open={mobileSheetOpen} onOpenChange={setMobileSheetOpen}>
          <SheetContent side="right" className="bg-card border-border w-full sm:max-w-md overflow-y-auto">
            <SheetHeader>
              <SheetTitle className="text-foreground">
                {selectedRfq ? `RFQ #${selectedRfq.id}` : 'RFQ Details'}
              </SheetTitle>
            </SheetHeader>
            <div className="mt-4">
              {detailContent}
            </div>
          </SheetContent>
        </Sheet>
      </div>
    </AppShell>
  );
}
