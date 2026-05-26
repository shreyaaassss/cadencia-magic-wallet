'use client';

import * as React from 'react';
import { useQuery, useInfiniteQuery, useMutation } from '@tanstack/react-query';
import { Landmark, FileText, File, Receipt, Download, Copy, Check } from 'lucide-react';

import { AppShell } from '@/components/layout/AppShell';
import { StatCard } from '@/components/shared/StatCard';
import { AuthGuard } from '@/components/shared/AuthGuard';
import { AdminGuard } from '@/components/shared/AdminGuard';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { Button } from '@/components/ui/button';
import { ComplianceTabs } from '@/components/shared/ComplianceTabs';
import { CursorPagination } from '@/components/shared/CursorPagination';
import { DownloadProgress } from '@/components/shared/DownloadProgress';
import { HashChainVerifier } from '@/components/shared/HashChainVerifier';

import { useAuth } from '@/hooks/useAuth';
import { api } from '@/lib/api';
import { formatCurrency, formatDate } from '@/lib/utils';
import type { AuditEntry, FEMARecord, GSTRecord } from '@/types';

export default function CompliancePage() {
  const { isAdmin } = useAuth();
  
  const [activeTab, setActiveTab] = React.useState<'audit' | 'fema' | 'gst'>('audit');
  const [selectedEscrowId, setSelectedEscrowId] = React.useState<string>('');
  const [copiedHash, setCopiedHash] = React.useState<string | null>(null);

  const [exportStatus, setExportStatus] = React.useState<'idle' | 'queued' | 'processing' | 'ready' | 'failed'>('idle');
  const [exportData, setExportData] = React.useState<{ task_id?: string; download_url?: string | null }>({});

  // 1. Recent Escrows (for dropdown filter)
  const { data: recentEscrows } = useQuery<{ escrow_id: string }[]>({
    queryKey: ['recent-escrows'],
    queryFn: () => api.get('/v1/escrow?limit=20').then(r =>
      (r.data.data || []).map((e: any) => ({ escrow_id: e.escrow_id }))
    ),
  });

  // Auto-select first escrow when data loads
  React.useEffect(() => {
    if (recentEscrows && recentEscrows.length > 0 && !selectedEscrowId) {
      setSelectedEscrowId(recentEscrows[0].escrow_id);
    }
  }, [recentEscrows, selectedEscrowId]);

  // 2. Audit Logs
  const {
    data: auditLogData,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading: isLoadingAudit
  } = useInfiniteQuery({
    queryKey: ['audit', selectedEscrowId],
    queryFn: ({ pageParam }) =>
      api.get(`/v1/audit/${selectedEscrowId}?cursor=${pageParam}&limit=20`).then(r => r.data),
    initialPageParam: '',
    getNextPageParam: (lastPage: any) => lastPage.next_cursor || undefined,
    enabled: !!selectedEscrowId,
  });

  const auditLogs: AuditEntry[] = auditLogData?.pages.flatMap((page: any) => page.data?.entries ?? page.data ?? []) || [];

  // Chain Verification
  const verifyMutation = useMutation({
    mutationFn: () => api.get(`/v1/audit/${selectedEscrowId}/verify`).then(r => r.data.data),
  });

  // 3. FEMA Record
  const { data: femaRecord, isLoading: isFemaLoading } = useQuery({
    queryKey: ['fema', selectedEscrowId],
    queryFn: () => api.get(`/v1/compliance/${selectedEscrowId}/fema`).then(r => r.data.data),
    enabled: activeTab === 'fema' && !!selectedEscrowId,
  });

  // 4. GST Record
  const { data: gstRecord, isLoading: isGstLoading } = useQuery({
    queryKey: ['gst', selectedEscrowId],
    queryFn: () => api.get(`/v1/compliance/${selectedEscrowId}/gst`).then(r => r.data.data),
    enabled: activeTab === 'gst' && !!selectedEscrowId,
  });

  // Export Mutations
  const bulkExportMutation = useMutation({
    mutationFn: () => api.post('/v1/compliance/export/zip').then(r => r.data.data),
    onSuccess: (data: any) => {
      setExportStatus('processing');
      setExportData(data);
      // Simulate polling completion
      setTimeout(() => {
        setExportStatus('ready');
        setExportData(prev => ({ ...prev, download_url: '/mock/bulk-export.zip' }));
      }, 3000);
    },
  });

  const handleDownload = (type: 'fema' | 'gst') => {
    const endpoint = `/v1/compliance/${selectedEscrowId}/${type}/${type === 'fema' ? 'pdf' : 'csv'}`;
    api.get(endpoint).then(r => {
      const url = r.data.data?.download_url;
      if (url) window.open(url, '_blank');
      else {
        // Fallback for CSV mock which returns raw data in some cases
        const blob = new Blob([JSON.stringify(r.data.data)], { type: 'text/csv' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `${type}-${selectedEscrowId}.csv`;
        a.click();
      }
    });
  };

  const copyToClipboard = (hash: string) => {
    navigator.clipboard.writeText(hash);
    setCopiedHash(hash);
    setTimeout(() => setCopiedHash(null), 2000);
  };

  return (
    <AppShell>
      <AuthGuard>
        <div className="p-6 space-y-8">
          
          {/* Header */}
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
              <File className="h-6 w-6 text-primary" />
              Compliance & Audit
            </h1>
            <p className="text-muted-foreground mt-2">Immutable audit logs and regulatory compliance reporting.</p>
          </div>

          {/* Compliance Stats Overview */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
             <StatCard label="Total Escrows" value={recentEscrows?.length ?? 0} icon={Landmark} />
             <StatCard label="Audit Entries" value={auditLogs.length} icon={FileText} />
             <StatCard label="FEMA Records" value={femaRecord ? 1 : 0} icon={File} />
             <StatCard label="GST Exports" value={gstRecord ? 1 : 0} icon={Receipt} />
          </div>

          {/* Empty state when no escrows */}
          {recentEscrows && recentEscrows.length === 0 && (
            <div className="bg-card border border-border rounded-lg p-12 text-center">
              <Landmark className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
              <h3 className="text-lg font-semibold text-foreground mb-1">No Escrow Transactions Yet</h3>
              <p className="text-sm text-muted-foreground">Compliance data will appear here once you have completed escrow transactions.</p>
            </div>
          )}

          {/* Main Content Area */}
          {selectedEscrowId && <div className="bg-card border border-border rounded-lg overflow-hidden">
            <ComplianceTabs activeTab={activeTab} onTabChange={setActiveTab} />
            
            <div className="px-6 pb-6 pt-2">
              {/* Common Filter Row */}
              <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center justify-between mb-6">
                <div className="flex items-center gap-4">
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-semibold text-muted-foreground">Select Escrow</label>
                    <select 
                      className="bg-muted border border-border rounded-md text-sm px-3 py-1.5 outline-none min-w-[200px]"
                      value={selectedEscrowId}
                      onChange={(e) => setSelectedEscrowId(e.target.value)}
                    >
                      {recentEscrows?.map(e => (
                        <option key={e.escrow_id} value={e.escrow_id}>{e.escrow_id.slice(0, 16)}</option>
                      ))}
                    </select>
                  </div>
                  {activeTab === 'audit' && (
                    <div className="flex flex-col gap-1">
                      <label className="text-xs font-semibold text-muted-foreground">Date Range</label>
                      <select className="bg-muted border border-border rounded-md text-sm px-3 py-1.5 outline-none">
                        <option value="all">All Time</option>
                        <option value="month">This Month</option>
                      </select>
                    </div>
                  )}
                </div>

                {activeTab === 'audit' && (
                  <HashChainVerifier 
                    onVerify={() => verifyMutation.mutate()} 
                    isVerifying={verifyMutation.isPending} 
                    verification={verifyMutation.data || null} 
                  />
                )}
              </div>

              {/* Tab: Audit */}
              {activeTab === 'audit' && (
                <div className="border border-border rounded-lg overflow-hidden">
                  <div className="w-full overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-border text-xs font-semibold text-muted-foreground text-left uppercase tracking-wider bg-muted/20">
                          <th className="px-6 py-4">Hash</th>
                          <th className="px-6 py-4">Event</th>
                          <th className="px-6 py-4">Seq #</th>
                          <th className="px-6 py-4 text-right">Date</th>
                        </tr>
                      </thead>
                      <tbody>
                        {isLoadingAudit ? (
                          <tr><td colSpan={4} className="px-6 py-8 text-center text-muted-foreground">Loading audit log...</td></tr>
                        ) : auditLogs.length === 0 ? (
                          <tr><td colSpan={4} className="px-6 py-8 text-center text-muted-foreground">No audit entries found.</td></tr>
                        ) : (
                          auditLogs.map((log) => (
                            <tr key={log.entry_id} className="border-b border-border hover:bg-muted/30">
                              <td className="px-6 py-4">
                                <div className="flex items-center gap-2">
                                  <span className="font-mono text-xs text-primary truncate max-w-[150px]" title={log.entry_hash}>
                                    {log.entry_hash.substring(0, 16)}...
                                  </span>
                                  <button onClick={() => copyToClipboard(log.entry_hash)} className="text-muted-foreground hover:text-foreground">
                                    {copiedHash === log.entry_hash ? <Check className="h-3 w-3 text-green-600" /> : <Copy className="h-3 w-3" />}
                                  </button>
                                </div>
                              </td>
                              <td className="px-6 py-4">
                                <StatusBadge status={log.event_type} size="sm" />
                              </td>
                              <td className="px-6 py-4 truncate max-w-[180px] font-mono text-xs">
                                #{log.sequence_no}
                              </td>
                              <td className="px-6 py-4 text-right text-muted-foreground text-xs whitespace-nowrap">
                                {formatDate(log.created_at)}
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                  <CursorPagination 
                    data={auditLogs}
                    hasMore={!!hasNextPage}
                    isLoading={isFetchingNextPage}
                    loadMore={() => fetchNextPage()}
                  />
                </div>
              )}

              {/* Tab: FEMA */}
              {activeTab === 'fema' && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {isFemaLoading ? (
                    <div className="h-40 bg-muted/30 animate-pulse rounded-lg border border-border" />
                  ) : femaRecord ? (
                    <div className="bg-muted/10 border border-border rounded-lg p-6 flex flex-col justify-between">
                      <div>
                        <div className="flex justify-between items-start mb-4">
                          <div>
                            <h3 className="font-medium text-foreground">FEMA Compliance</h3>
                            <p className="text-xs text-muted-foreground font-mono mt-1">Form {femaRecord.form_type} &middot; Escrow #{femaRecord.escrow_id}</p>
                          </div>
                          <span className="flex items-center gap-1 text-xs text-primary bg-primary/10 px-2 py-1 rounded border border-primary/20">
                            {femaRecord.purpose_code}
                          </span>
                        </div>

                        <div className="space-y-2 text-sm">
                          <div className="flex justify-between"><span className="text-muted-foreground">Amount INR:</span> <span className="font-semibold">{formatCurrency(femaRecord.amount_inr)}</span></div>
                          <div className="flex justify-between"><span className="text-muted-foreground">Amount ALGO:</span> <span>{femaRecord.amount_algo}</span></div>
                          <div className="flex justify-between"><span className="text-muted-foreground">FX Rate (INR/ALGO):</span> <span>{femaRecord.fx_rate_inr_per_algo}</span></div>
                          <div className="flex justify-between"><span className="text-muted-foreground">Buyer PAN:</span> <span className="font-mono">{femaRecord.buyer_pan}</span></div>
                          <div className="flex justify-between"><span className="text-muted-foreground">Seller PAN:</span> <span className="font-mono">{femaRecord.seller_pan}</span></div>
                        </div>
                      </div>

                      <div className="mt-8 flex gap-3">
                        <Button onClick={() => handleDownload('fema')} className="w-full bg-primary text-primary-foreground">
                          <Download className="h-4 w-4 mr-2" /> Download FEMA PDF
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="text-center py-8 text-muted-foreground">No FEMA record available.</div>
                  )}
                </div>
              )}

              {/* Tab: GST */}
              {activeTab === 'gst' && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {isGstLoading ? (
                    <div className="h-40 bg-muted/30 animate-pulse rounded-lg border border-border" />
                  ) : gstRecord ? (
                    <div className="bg-muted/10 border border-border rounded-lg p-6 flex flex-col justify-between">
                      <div>
                        <div className="flex justify-between items-start mb-4">
                          <div>
                            <h3 className="font-medium text-foreground">GST Compliance</h3>
                            <p className="text-xs text-muted-foreground font-mono mt-1">Escrow #{gstRecord.escrow_id}</p>
                          </div>
                          <span className="flex items-center gap-1 text-xs text-primary bg-primary/10 px-2 py-1 rounded border border-primary/20">
                            HSN: {gstRecord.hsn_code} &middot; {gstRecord.tax_type}
                          </span>
                        </div>

                        <div className="space-y-2 text-sm">
                          <div className="flex justify-between"><span className="text-muted-foreground">Taxable Amount:</span> <span className="font-semibold">{formatCurrency(gstRecord.taxable_amount)}</span></div>
                          <div className="flex justify-between"><span className="text-muted-foreground">Buyer GSTIN:</span> <span className="font-mono">{gstRecord.buyer_gstin}</span></div>
                          <div className="flex justify-between"><span className="text-muted-foreground">Seller GSTIN:</span> <span className="font-mono">{gstRecord.seller_gstin}</span></div>
                          <div className="flex justify-between border-t border-border pt-2 mt-2"><span className="text-muted-foreground">CGST:</span> <span>{formatCurrency(gstRecord.cgst_amount)}</span></div>
                          <div className="flex justify-between"><span className="text-muted-foreground">SGST:</span> <span>{formatCurrency(gstRecord.sgst_amount)}</span></div>
                          <div className="flex justify-between"><span className="text-muted-foreground">IGST:</span> <span>{formatCurrency(gstRecord.igst_amount)}</span></div>
                          <div className="flex justify-between font-semibold border-t border-border pt-2 mt-2"><span className="text-muted-foreground">Total Tax:</span> <span>{formatCurrency(gstRecord.total_tax)}</span></div>
                        </div>
                      </div>

                      <div className="mt-8 flex gap-3">
                        <Button onClick={() => handleDownload('gst')} className="w-full bg-primary text-primary-foreground">
                          <Download className="h-4 w-4 mr-2" /> Download GST CSV
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="text-center py-8 text-muted-foreground">No GST record available.</div>
                  )}
                </div>
              )}

            </div>
          </div>}

          {/* Bulk Export (Admin) */}
          <AdminGuard>
            <div className="bg-card border border-border rounded-lg p-6 flex flex-col md:flex-row items-center justify-between gap-6">
              <div>
                <h3 className="text-lg font-semibold text-foreground flex items-center gap-2">
                  <Download className="h-5 w-5 text-primary" />
                  Bulk Export
                </h3>
                <p className="text-sm text-muted-foreground mt-1">Export all compliance documents and audit logs as a single ZIP archive for regulatory reporting.</p>
                {exportStatus === 'ready' && <p className="text-xs text-primary mt-2">Est. size: 45MB &bull; Last export: Just now</p>}
              </div>

              <div className="shrink-0 bg-muted/20 p-4 rounded-lg border border-border">
                <DownloadProgress 
                  status={exportStatus}
                  progress={exportStatus === 'processing' ? 64 : exportStatus === 'ready' ? 100 : 0}
                  downloadUrl={exportData.download_url || undefined}
                  onExport={() => bulkExportMutation.mutate()}
                  onRetry={() => {
                    setExportStatus('idle');
                    bulkExportMutation.mutate();
                  }}
                />
              </div>
            </div>
          </AdminGuard>

        </div>
      </AuthGuard>
    </AppShell>
  );
}
