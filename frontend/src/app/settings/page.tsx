'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Controller, useForm } from 'react-hook-form';
import { toast } from 'sonner';
import {
  Cpu, Repeat, Zap, TrendingUp, Trash2, Loader2, ArrowRight,
} from 'lucide-react';

import { AppShell } from '@/components/layout/AppShell';
import { AuthGuard } from '@/components/shared/AuthGuard';
import { SectionHeader } from '@/components/shared/SectionHeader';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { FormField } from '@/components/shared/FormField';
import { DataTable } from '@/components/shared/DataTable';
import { ConfirmDialog } from '@/components/shared/ConfirmDialog';
import { KycStatusBanner } from '@/components/shared/KycStatusBanner';
import { ApiKeyModal } from '@/components/shared/ApiKeyModal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

import { useAuth } from '@/hooks/useAuth';
import { api } from '@/lib/api';
import { formatCurrency, formatDate, formatDateTime, truncateAddress } from '@/lib/utils';
import { ROUTES } from '@/lib/constants';
import type { Enterprise, ApiKey } from '@/types';

// ─── Types for API key with extra fields ────────────────────────────────────
interface ApiKeyRow {
  id: string;
  label: string;
  created_at: string;
  last_used: string | null;
}

interface NewApiKey {
  id: string;
  label: string;
  key: string;
  created_at: string;
}

// ─── Agent Config Form Types ─────────────────────────────────────────────────
interface AgentFormValues {
  negotiation_style: 'AGGRESSIVE' | 'MODERATE' | 'CONSERVATIVE';
  max_rounds: string;
  auto_escalate: boolean;
  escalate_after: string;
  min_acceptable_price: string;
}

export default function SettingsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { enterprise: authEnterprise } = useAuth();
  const enterpriseId = authEnterprise?.id;

  // ─── Enterprise data ────────────────────────────────────────────────────────
  const { data: enterprise, refetch: refetchEnterprise } = useQuery<Enterprise>({
    queryKey: ['enterprise', enterpriseId],
    queryFn: () => api.get(`/v1/enterprises/${enterpriseId}`).then(r => r.data.data),
    enabled: !!enterpriseId,
  });

  // ─── API Keys ────────────────────────────────────────────────────────────────
  const { data: apiKeys = [], isLoading: apiKeysLoading } = useQuery<ApiKeyRow[]>({
    queryKey: ['api-keys'],
    queryFn: () => api.get('/v1/auth/api-keys?limit=10').then(r => r.data.data),
  });

  // ─── KYC Upload ─────────────────────────────────────────────────────────────
  const kycMutation = useMutation({
    mutationFn: async (files: File[]) => {
      const formData = new FormData();
      files.forEach(file => formData.append('documents', file));
      return api.patch(`/v1/enterprises/${enterpriseId}/kyc`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
    },
    onSuccess: () => {
      toast.success('KYC documents submitted successfully');
      refetchEnterprise();
    },
    onError: () => {
      toast.error('Failed to submit KYC documents');
    },
  });

  // ─── Agent Config ───────────────────────────────────────────────────────────
  const agentForm = useForm<AgentFormValues>({
    defaultValues: {
      negotiation_style: 'MODERATE',
      max_rounds: '20',
      auto_escalate: false,
      escalate_after: '15',
      min_acceptable_price: '',
    },
  });

  // Sync form when enterprise data loads
  React.useEffect(() => {
    if (enterprise?.agent_config) {
      const ac = enterprise.agent_config;
      agentForm.reset({
        negotiation_style: ac.negotiation_style,
        max_rounds: String(ac.max_rounds),
        auto_escalate: ac.auto_escalate,
        escalate_after: '15',
        min_acceptable_price: ac.min_acceptable_price ? String(ac.min_acceptable_price) : '',
      });
    }
  }, [enterprise]); // eslint-disable-line react-hooks/exhaustive-deps

  const agentMutation = useMutation({
    mutationFn: async (values: AgentFormValues) => {
      const payload = {
        agent_config: {
          negotiation_style: values.negotiation_style,
          max_rounds: parseInt(values.max_rounds) || 20,
          auto_escalate: values.auto_escalate,
          min_acceptable_price: values.min_acceptable_price ? parseInt(values.min_acceptable_price) : null,
        },
      };
      return api.put(`/v1/enterprises/${enterpriseId}/agent-config`, payload);
    },
    onSuccess: () => {
      toast.success('Agent configuration updated');
      refetchEnterprise();
    },
    onError: () => {
      toast.error('Failed to update agent configuration');
    },
  });

  const watchAutoEscalate = agentForm.watch('auto_escalate');

  // ─── API Key Creation ─────────────────────────────────────────────────────
  const [newKeyLabel, setNewKeyLabel] = React.useState('');
  const [newKeyData, setNewKeyData] = React.useState<NewApiKey | null>(null);
  const [keyModalOpen, setKeyModalOpen] = React.useState(false);

  const createKeyMutation = useMutation({
    mutationFn: async (label: string) => {
      const res = await api.post('/v1/auth/api-keys', { label });
      return res.data.data as NewApiKey;
    },
    onSuccess: (data) => {
      setNewKeyData(data);
      setKeyModalOpen(true);
      setNewKeyLabel('');
      queryClient.invalidateQueries({ queryKey: ['api-keys'] });
    },
    onError: () => {
      toast.error('Failed to create API key');
    },
  });

  // ─── API Key Revocation ───────────────────────────────────────────────────
  const [revokeTarget, setRevokeTarget] = React.useState<ApiKeyRow | null>(null);

  const revokeKeyMutation = useMutation({
    mutationFn: async (keyId: string) => {
      return api.delete(`/v1/auth/api-keys/${keyId}`);
    },
    onSuccess: () => {
      toast.success('API key revoked');
      setRevokeTarget(null);
      queryClient.invalidateQueries({ queryKey: ['api-keys'] });
    },
    onError: () => {
      toast.error('Failed to revoke API key');
    },
  });

  const kycStatus = enterprise?.kyc_status ?? 'NOT_SUBMITTED';
  const walletAddr = enterprise?.algorand_wallet;

  return (
    <AppShell>
      <AuthGuard>
        <div className="p-6">

          {/* Section 1: Enterprise Profile Summary */}
          <div className="bg-card border border-border rounded-lg p-6 mb-8">
            <SectionHeader title="Enterprise Profile" />
            {enterprise ? (
              <div className="space-y-4">
                <div className="flex flex-wrap items-baseline gap-x-3 sm:gap-x-6 gap-y-2">
                  <h2 className="text-xl font-semibold text-foreground">{enterprise.legal_name}</h2>
                  <span className="text-sm font-mono text-muted-foreground">PAN: {enterprise.pan}</span>
                  <span className="text-sm font-mono text-muted-foreground">GSTIN: {enterprise.gstin}</span>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <StatusBadge status={enterprise.trade_role} />
                  <StatusBadge status={enterprise.kyc_status} />
                  {walletAddr ? (
                    <div className="flex items-center gap-2">
                      <StatusBadge status="WALLET_LINKED" />
                      <span className="text-xs font-mono text-muted-foreground">{truncateAddress(walletAddr)}</span>
                      <button
                        onClick={() => router.push(ROUTES.WALLET)}
                        className="text-xs text-primary hover:underline inline-flex items-center gap-1"
                      >
                        Manage
                        <ArrowRight className="h-3 w-3" />
                      </button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2">
                      <StatusBadge status="NOT_SUBMITTED" />
                      <button
                        onClick={() => router.push(ROUTES.WALLET)}
                        className="text-xs text-primary hover:underline inline-flex items-center gap-1"
                      >
                        Link Wallet
                        <ArrowRight className="h-3 w-3" />
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="bg-muted animate-pulse rounded h-6 w-48" />
                <div className="bg-muted animate-pulse rounded h-4 w-64" />
              </div>
            )}
          </div>

          {/* Section 2: KYC Submission */}
          <div className="mb-8">
            <SectionHeader title="KYC Verification" />
            <KycStatusBanner
              status={kycStatus as 'NOT_SUBMITTED' | 'PENDING' | 'ACTIVE' | 'REJECTED'}
              onUpload={async (files) => { await kycMutation.mutateAsync(files); }}
              isUploading={kycMutation.isPending}
            />
          </div>

          {/* Section 3: AI Agent Configuration */}
          <div className="bg-card border border-border rounded-lg p-6 mb-8">
            <SectionHeader title="AI Agent Configuration" description="Configure how the AI negotiation agent behaves on your behalf" />
            <form
              onSubmit={agentForm.handleSubmit((values) => agentMutation.mutate(values))}
              className="space-y-6"
            >
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
                {/* Negotiation Style */}
                <FormField label="Negotiation Style" hint="How aggressively the agent negotiates pricing">
                  <div className="flex items-center gap-2">
                    <Cpu className="h-4 w-4 text-muted-foreground shrink-0" />
                    <Controller
                      control={agentForm.control}
                      name="negotiation_style"
                      render={({ field }) => (
                        <Select onValueChange={field.onChange} value={field.value}>
                          <SelectTrigger className="flex-1">
                            <SelectValue placeholder="Select style" />
                          </SelectTrigger>
                          <SelectContent position="popper" className="bg-popover border-border">
                            <SelectItem value="AGGRESSIVE">Aggressive</SelectItem>
                            <SelectItem value="MODERATE">Moderate</SelectItem>
                            <SelectItem value="CONSERVATIVE">Conservative</SelectItem>
                          </SelectContent>
                        </Select>
                      )}
                    />
                  </div>
                </FormField>

                {/* Max Rounds */}
                <FormField
                  label="Max Rounds"
                  hint="Maximum negotiation rounds before auto-termination (1-50)"
                  error={
                    agentForm.formState.errors.max_rounds
                      ? 'Must be between 1 and 50'
                      : undefined
                  }
                >
                  <div className="flex items-center gap-2">
                    <Repeat className="h-4 w-4 text-muted-foreground shrink-0" />
                    <Input
                      type="number"
                      min={1}
                      max={50}
                      {...agentForm.register('max_rounds', {
                        validate: (v) => {
                          const n = parseInt(v);
                          return (n >= 1 && n <= 50) || 'Must be between 1 and 50';
                        },
                      })}
                    />
                  </div>
                </FormField>
              </div>

              {/* Auto-escalate */}
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <Zap className="h-4 w-4 text-muted-foreground shrink-0" />
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      {...agentForm.register('auto_escalate')}
                      className="h-4 w-4 rounded border-border bg-input text-primary accent-primary"
                    />
                    <span className="text-sm text-foreground">Auto-escalate to human review</span>
                  </label>
                </div>

                {watchAutoEscalate && (
                  <div className="ml-7">
                    <FormField
                      label="Escalate after rounds"
                      hint="Number of rounds before triggering human escalation"
                    >
                      <Input
                        type="number"
                        min={1}
                        max={50}
                        {...agentForm.register('escalate_after')}
                      />
                    </FormField>
                  </div>
                )}
              </div>

              {/* Min Acceptable Price */}
              <FormField label="Min Acceptable Price" hint="Floor price below which the agent will not agree (optional)">
                <div className="flex items-center gap-2">
                  <TrendingUp className="h-4 w-4 text-muted-foreground shrink-0" />
                  <div className="relative flex-1">
                    <span className="absolute left-3 top-2.5 text-sm font-medium text-muted-foreground">INR</span>
                    <Input
                      type="number"
                      className="pl-12"
                      placeholder="0"
                      {...agentForm.register('min_acceptable_price')}
                    />
                  </div>
                </div>
              </FormField>

              <div className="flex justify-end">
                <Button
                  type="submit"
                  disabled={agentMutation.isPending}
                  className="w-full sm:w-auto bg-primary text-primary-foreground hover:bg-primary/90"
                >
                  {agentMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Save Agent Config
                </Button>
              </div>
            </form>
          </div>

          {/* Section 4: API Keys */}
          <div className="bg-card border border-border rounded-lg p-6">
            <SectionHeader title="API Keys" description="Machine-to-machine authentication keys for external integrations" />

            {/* Create key form */}
            <div className="flex flex-col sm:flex-row gap-2 sm:items-end mb-6">
              <div className="flex-1">
                <label className="text-sm font-medium text-foreground mb-1.5 block">Label</label>
                <Input
                  placeholder="ERP Integration"
                  value={newKeyLabel}
                  onChange={(e) => setNewKeyLabel(e.target.value)}
                />
              </div>
              <Button
                onClick={() => {
                  if (!newKeyLabel.trim()) {
                    toast.error('Enter a label for the API key');
                    return;
                  }
                  createKeyMutation.mutate(newKeyLabel.trim());
                }}
                disabled={createKeyMutation.isPending}
                className="bg-primary text-primary-foreground hover:bg-primary/90"
              >
                {createKeyMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Create Key
              </Button>
            </div>

            {/* Keys table */}
            <DataTable<ApiKeyRow>
              columns={[
                {
                  key: 'label',
                  label: 'Label',
                  render: (v) => <span className="text-sm font-medium text-foreground">{String(v)}</span>,
                },
                {
                  key: 'id',
                  label: 'Key ID',
                  render: (v) => <span className="font-mono text-xs text-muted-foreground">{String(v)}</span>,
                },
                {
                  key: 'created_at',
                  label: 'Created',
                  sortable: true,
                  render: (v) => <span className="text-muted-foreground text-xs">{formatDate(String(v))}</span>,
                },
                {
                  key: 'last_used',
                  label: 'Last Used',
                  render: (v) => (
                    <span className="text-muted-foreground text-xs">
                      {v ? formatDateTime(String(v)) : 'Never'}
                    </span>
                  ),
                },
                {
                  key: '_actions',
                  label: 'Actions',
                  width: '80px',
                  render: (_v, row) => (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        setRevokeTarget(row);
                      }}
                      className="text-muted-foreground hover:text-destructive hover:bg-red-50"
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  ),
                },
              ]}
              data={apiKeys}
              isLoading={apiKeysLoading}
              keyExtractor={(row) => row.id}
            />
          </div>

          {/* API Key Modal */}
          <ApiKeyModal
            open={keyModalOpen}
            onOpenChange={setKeyModalOpen}
            apiKey={newKeyData}
          />

          {/* Revoke Confirm Dialog */}
          <ConfirmDialog
            open={!!revokeTarget}
            onOpenChange={(open) => { if (!open) setRevokeTarget(null); }}
            title="Revoke API Key"
            description={`This will permanently revoke the key "${revokeTarget?.label}". This action cannot be undone. Are you sure?`}
            confirmLabel="Revoke"
            variant="destructive"
            onConfirm={() => {
              if (revokeTarget) revokeKeyMutation.mutate(revokeTarget.id);
            }}
            isLoading={revokeKeyMutation.isPending}
          />
        </div>
      </AuthGuard>
    </AppShell>
  );
}
