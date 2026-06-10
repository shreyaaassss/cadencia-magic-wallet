'use client';

import * as React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { FileText, Download, CheckCircle2, Clock, XCircle } from 'lucide-react';

import { AppShell } from '@/components/layout/AppShell';
import { SectionHeader } from '@/components/shared/SectionHeader';
import { EmptyState } from '@/components/shared/EmptyState';
import { useAuth } from '@/hooks/useAuth';
import { api, getAccessToken } from '@/lib/api';
import { cn, formatDate, formatCurrency } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { API_BASE_URL } from '@/lib/constants';

interface ProcurementDoc {
  id: string;
  po_number: string;
  status: string;
  buyer_enterprise_id: string;
  seller_enterprise_id: string;
  created_at: string;
  document_snapshot?: {
    buyer?: { legal_name?: string };
    seller?: { legal_name?: string };
    agreed_price_inr?: number;
    session_id?: string;
    round_count?: number;
  };
  seller_accepted_at?: string | null;
  buyer_accepted_at?: string | null;
}

const STATUS_STYLES: Record<string, { icon: React.ElementType; color: string; bg: string }> = {
  DRAFT: { icon: Clock, color: 'text-muted-foreground', bg: 'bg-muted' },
  PENDING_SELLER_ACCEPTANCE: { icon: Clock, color: 'text-amber-600 dark:text-amber-400', bg: 'bg-amber-50 dark:bg-amber-900/20' },
  ACTIVE: { icon: CheckCircle2, color: 'text-green-600 dark:text-green-400', bg: 'bg-green-50 dark:bg-green-900/20' },
  AMENDED: { icon: FileText, color: 'text-blue-600', bg: 'bg-blue-50' },
  CANCELLED: { icon: XCircle, color: 'text-red-600', bg: 'bg-red-50' },
};

export default function ProcurementPage() {
  const { enterprise } = useAuth();
  const queryClient = useQueryClient();

  const { data: documents = [], isLoading } = useQuery<ProcurementDoc[]>({
    queryKey: ['procurement-documents'],
    queryFn: () => api.get('/v1/procurement').then(r => r.data?.data || []),
    refetchInterval: 10_000,
  });

  const acceptMutation = useMutation({
    mutationFn: (docId: string) => api.patch(`/v1/procurement/${docId}/seller-accept`),
    onSuccess: () => {
      toast.success('Purchase Order accepted');
      queryClient.invalidateQueries({ queryKey: ['procurement-documents'] });
    },
    onError: (err: any) => {
      const detail = err.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'Failed to accept PO');
    },
  });

  const isSeller = enterprise?.trade_role === 'SELLER' || enterprise?.trade_role === 'BOTH';
  const isBuyer = enterprise?.trade_role === 'BUYER' || enterprise?.trade_role === 'BOTH';
  const pendingCount = documents.filter(
    d => d.status === 'PENDING_SELLER_ACCEPTANCE' && d.seller_enterprise_id === enterprise?.id,
  ).length;

  const title = isSeller && !isBuyer
    ? 'Purchase Orders'
    : 'Your Purchase Orders';
  const description = isSeller && pendingCount > 0
    ? `${pendingCount} PO${pendingCount > 1 ? 's' : ''} awaiting your acceptance`
    : 'Purchase orders are generated automatically once a negotiation reaches agreement.';

  return (
    <AppShell>
      <div className="space-y-6">
        <SectionHeader title={title} description={description} />

        {isLoading ? (
          <p className="text-sm text-muted-foreground py-8 text-center">Loading documents...</p>
        ) : documents.length === 0 ? (
          <EmptyState
            icon={FileText}
            title="No purchase orders yet"
            description="Purchase orders are generated automatically once a negotiation reaches agreement."
          />
        ) : (
          <div className="space-y-3">
            {documents.map(doc => {
              const style = STATUS_STYLES[doc.status] || STATUS_STYLES.DRAFT;
              const StatusIcon = style.icon;
              const canAccept = isSeller
                && doc.status === 'PENDING_SELLER_ACCEPTANCE'
                && doc.seller_enterprise_id === enterprise?.id;
              const isSellerOwned = doc.seller_enterprise_id === enterprise?.id;
              const sessionId = doc.document_snapshot?.session_id;

              return (
                <div key={doc.id} className="border border-border rounded-lg p-4 bg-card">
                  <div className="flex items-start justify-between">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <FileText className="h-4 w-4 text-muted-foreground" />
                        <span className="text-sm font-semibold text-foreground font-mono">
                          {doc.po_number}
                        </span>
                        <span className={cn('inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium', style.bg, style.color)}>
                          <StatusIcon className="h-3 w-3" />
                          {doc.status === 'PENDING_SELLER_ACCEPTANCE'
                            ? (isSellerOwned ? 'Awaiting your acceptance' : 'Awaiting seller acceptance')
                            : doc.status.replace(/_/g, ' ')}
                        </span>
                        {doc.status === 'ACTIVE' && isSellerOwned && (
                          <span className="text-xs text-green-600 dark:text-green-400 font-medium">✓ Accepted</span>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Created {formatDate(doc.created_at)}
                        {doc.seller_accepted_at && ` · Accepted ${formatDate(doc.seller_accepted_at)}`}
                      </p>
                    </div>

                    <div className="flex gap-2 items-center">
                      {canAccept && (
                        <Button
                          size="sm"
                          onClick={() => acceptMutation.mutate(doc.id)}
                          disabled={acceptMutation.isPending}
                          className="bg-green-600 hover:bg-green-700 text-white"
                        >
                          <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
                          Accept PO
                        </Button>
                      )}
                      <a
                        href={`${API_BASE_URL}/v1/procurement/${doc.id}/download`}
                        download={`${doc.po_number}.pdf`}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => {
                          // Add auth header via fetch for the download
                          e.preventDefault();
                          const token = getAccessToken();
                          fetch(`${API_BASE_URL}/v1/procurement/${doc.id}/download`, {
                            headers: token ? { Authorization: `Bearer ${token}` } : {},
                          })
                            .then(r => {
                              if (!r.ok) throw new Error('Download failed');
                              return r.blob();
                            })
                            .then(blob => {
                              const url = URL.createObjectURL(blob);
                              const a = document.createElement('a');
                              a.href = url;
                              a.download = `${doc.po_number.replace(/-/g, '_')}.pdf`;
                              a.click();
                              URL.revokeObjectURL(url);
                            })
                            .catch(() => toast.error('Failed to download PDF'));
                        }}
                        className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md border border-border text-muted-foreground hover:text-foreground hover:border-primary transition-colors cursor-pointer"
                      >
                        <Download className="h-3.5 w-3.5" />
                        PDF
                      </a>
                      {sessionId && (
                        <a
                          href={`/negotiations/${sessionId}`}
                          className="text-xs text-primary hover:underline"
                        >
                          View negotiation
                        </a>
                      )}
                    </div>
                  </div>

                  {doc.document_snapshot && (
                    <div className="mt-3 grid grid-cols-3 gap-4 text-xs">
                      <div>
                        <p className="text-muted-foreground">Buyer</p>
                        <p className="text-foreground font-medium">{doc.document_snapshot.buyer?.legal_name || '—'}</p>
                      </div>
                      <div>
                        <p className="text-muted-foreground">Seller</p>
                        <p className="text-foreground font-medium">{doc.document_snapshot.seller?.legal_name || '—'}</p>
                      </div>
                      {doc.document_snapshot.agreed_price_inr && (
                        <div>
                          <p className="text-muted-foreground">Agreed Price</p>
                          <p className="text-foreground font-medium">
                            {formatCurrency(doc.document_snapshot.agreed_price_inr)}
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </AppShell>
  );
}
