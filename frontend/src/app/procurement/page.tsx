'use client';

import * as React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { FileText, Download, CheckCircle2, Clock, XCircle, Plus } from 'lucide-react';

import { AppShell } from '@/components/layout/AppShell';
import { SectionHeader } from '@/components/shared/SectionHeader';
import { EmptyState } from '@/components/shared/EmptyState';
import { useAuth } from '@/hooks/useAuth';
import { api } from '@/lib/api';
import { cn, formatDate } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { toast } from 'sonner';

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
  };
  seller_accepted_at?: string | null;
}

const STATUS_STYLES: Record<string, { icon: React.ElementType; color: string; bg: string }> = {
  DRAFT: { icon: Clock, color: 'text-muted-foreground', bg: 'bg-muted' },
  PENDING_SELLER_ACCEPTANCE: { icon: Clock, color: 'text-amber-600', bg: 'bg-amber-50' },
  ACTIVE: { icon: CheckCircle2, color: 'text-green-600', bg: 'bg-green-50' },
  AMENDED: { icon: FileText, color: 'text-blue-600', bg: 'bg-blue-50' },
  CANCELLED: { icon: XCircle, color: 'text-red-600', bg: 'bg-red-50' },
};

export default function ProcurementPage() {
  const { enterprise } = useAuth();
  const queryClient = useQueryClient();
  const [showGenerateForm, setShowGenerateForm] = React.useState(false);
  const [sessionId, setSessionId] = React.useState('');

  const { data: documents = [], isLoading } = useQuery<ProcurementDoc[]>({
    queryKey: ['procurement-documents'],
    queryFn: () => api.get('/v1/procurement').then(r => r.data?.data || []),
  });

  const generateMutation = useMutation({
    mutationFn: (sid: string) => api.post('/v1/procurement/generate', { session_id: sid }),
    onSuccess: () => {
      toast.success('Purchase Order generated');
      queryClient.invalidateQueries({ queryKey: ['procurement-documents'] });
      setShowGenerateForm(false);
      setSessionId('');
    },
    onError: (err: any) => {
      const detail = err.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'Failed to generate PO');
    },
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

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <SectionHeader
            title="Procurement Documents"
            description="Purchase orders generated from agreed negotiations."
          />
          <Button
            onClick={() => setShowGenerateForm(!showGenerateForm)}
            className="bg-primary text-primary-foreground"
          >
            <Plus className="h-4 w-4 mr-1.5" /> Generate PO
          </Button>
        </div>

        {showGenerateForm && (
          <div className="border border-border rounded-lg p-4 bg-card space-y-3">
            <h3 className="text-sm font-semibold text-foreground">Generate Purchase Order</h3>
            <p className="text-xs text-muted-foreground">
              Enter the Session ID of an agreed negotiation to generate a PO.
            </p>
            <div className="flex gap-2">
              <Input
                placeholder="Negotiation Session ID"
                value={sessionId}
                onChange={e => setSessionId(e.target.value)}
                className="flex-1"
              />
              <Button
                onClick={() => sessionId && generateMutation.mutate(sessionId)}
                disabled={!sessionId || generateMutation.isPending}
              >
                {generateMutation.isPending ? 'Generating...' : 'Generate'}
              </Button>
              <Button variant="ghost" onClick={() => setShowGenerateForm(false)}>Cancel</Button>
            </div>
          </div>
        )}

        {isLoading ? (
          <p className="text-sm text-muted-foreground py-8 text-center">Loading documents...</p>
        ) : documents.length === 0 ? (
          <EmptyState
            icon={FileText}
            title="No procurement documents yet"
            description="Purchase orders are generated after a negotiation reaches agreement. Click 'Generate PO' with an agreed session ID."
          />
        ) : (
          <div className="space-y-3">
            {documents.map(doc => {
              const style = STATUS_STYLES[doc.status] || STATUS_STYLES.DRAFT;
              const StatusIcon = style.icon;
              const canAccept = isSeller
                && doc.status === 'PENDING_SELLER_ACCEPTANCE'
                && doc.seller_enterprise_id === enterprise?.id;

              return (
                <div key={doc.id} className="border border-border rounded-lg p-4 bg-card">
                  <div className="flex items-start justify-between">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <FileText className="h-4 w-4 text-muted-foreground" />
                        <span className="text-sm font-semibold text-foreground font-mono">
                          {doc.po_number}
                        </span>
                        <span className={cn('inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium', style.bg, style.color)}>
                          <StatusIcon className="h-3 w-3" />
                          {doc.status.replace(/_/g, ' ')}
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Created {formatDate(doc.created_at)}
                        {doc.seller_accepted_at && ` · Accepted ${formatDate(doc.seller_accepted_at)}`}
                      </p>
                    </div>

                    <div className="flex gap-2">
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
                            {new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(doc.document_snapshot.agreed_price_inr)}
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
