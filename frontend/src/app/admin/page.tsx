'use client';

import * as React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { 
  Building2, Users, Brain, Play, Landmark, TrendingUp, 
  Search, FileText, Cpu, User, Eye, Activity, CheckCircle, XCircle, Clock
} from 'lucide-react';
import { toast } from 'sonner';

import { AppShell } from '@/components/layout/AppShell';
import { StatCard } from '@/components/shared/StatCard';
import { AdminGuard } from '@/components/shared/AdminGuard';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { SectionHeader } from '@/components/shared/SectionHeader';
import { HealthBadge } from '@/components/shared/HealthBadge';
import { Button } from '@/components/ui/button';
import { FilterChips } from '@/components/shared/FilterChips';
import { ConfirmDialog } from '@/components/shared/ConfirmDialog';

import { AdminTabNav, AdminTab } from '@/components/shared/AdminTabNav';
import { KycReviewCard, AdminEnterprise } from '@/components/shared/KycReviewCard';
import { AgentMonitorRow, AdminAgent } from '@/components/shared/AgentMonitorRow';
import { LlmLogDrawer, LlmLog } from '@/components/shared/LlmLogDrawer';
import { BroadcastForm, BroadcastPayload } from '@/components/shared/BroadcastForm';

import { api } from '@/lib/api';
import { formatCurrency, formatDate } from '@/lib/utils';
import { ROUTES } from '@/lib/constants';
import type { PendingEscrowItem } from '@/types';

export default function AdminPage() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = React.useState<AdminTab>('overview');

  // Search/Filter states
  const [entKycFilter, setEntKycFilter] = React.useState('All');
  const [entRoleFilter, setEntRoleFilter] = React.useState('All');
  const [entSearch, setEntSearch] = React.useState('');

  const [userStatusFilter, setUserStatusFilter] = React.useState('All');
  const [userRoleFilter, setUserRoleFilter] = React.useState('All');
  const [userSearch, setUserSearch] = React.useState('');

  const [llmSessionSearch, setLlmSessionSearch] = React.useState('');

  // UI States
  const [selectedUserAction, setSelectedUserAction] = React.useState<{ id: string; action: 'suspend' | 'reinstate'; name: string } | null>(null);
  const [selectedLog, setSelectedLog] = React.useState<LlmLog | null>(null);
  const [broadcastResult, setBroadcastResult] = React.useState<{ message_id: string; recipients: number } | null>(null);

  // ─── Queries ─────────────────────────────────────────────────────────────
  
  const { data: stats } = useQuery({
    queryKey: ['admin-stats'],
    queryFn: () => api.get('/v1/admin/stats').then(r => r.data.data),
    staleTime: 60_000,
  });

  const { data: enterprises = [] } = useQuery({
    queryKey: ['admin-enterprises'],
    queryFn: () => api.get('/v1/admin/enterprises').then(r => r.data.data),
    enabled: activeTab === 'overview' || activeTab === 'enterprises',
  });

  const { data: users = [] } = useQuery({
    queryKey: ['admin-users'],
    queryFn: () => api.get('/v1/admin/users').then(r => r.data.data),
    enabled: activeTab === 'users',
  });

  const { data: agents = [] } = useQuery({
    queryKey: ['admin-agents'],
    queryFn: () => api.get('/v1/admin/agents').then(r => r.data.data as AdminAgent[]),
    enabled: activeTab === 'agents',
    refetchInterval: activeTab === 'agents' ? 10_000 : false,
  });

  const { data: llmLogs = [] } = useQuery({
    queryKey: ['admin-llm-logs'],
    queryFn: () => api.get('/v1/admin/llm-logs').then(r => r.data.data as LlmLog[]),
    enabled: activeTab === 'llm-logs',
  });

  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: () => api.get('/health').then(r => r.data.data),
    enabled: activeTab === 'overview',
  });

  const { data: recentActivity = [] } = useQuery<{ id: string; event_type: string; title: string; detail: string; actor?: string; amount?: string; created_at: string }[]>({
    queryKey: ['admin-activity'],
    queryFn: () => api.get('/v1/admin/activity?limit=5').then(r => r.data.data),
    enabled: activeTab === 'overview',
  });

  const { data: pendingEscrows = [] } = useQuery<PendingEscrowItem[]>({
    queryKey: ['admin-pending-escrows'],
    queryFn: () => api.get('/v1/admin/pending-escrows').then(r => r.data.data),
    enabled: activeTab === 'overview' || activeTab === 'escrows',
    refetchInterval: activeTab === 'escrows' ? 10_000 : false,
  });

  // ─── Mutations ───────────────────────────────────────────────────────────

  const kycMutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'approve' | 'reject' | 'revoke' }) =>
      api.patch(`/v1/admin/enterprises/${id}/kyc`, { action }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-enterprises'] });
      toast.success('KYC status updated successfully.');
    },
    onError: () => toast.error('Failed to update KYC status.'),
  });

  const suspendMutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'suspend' | 'reinstate' }) =>
      api.patch(`/v1/admin/users/${id}/suspend`, { action }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['admin-users'] });
      toast.success(`User successfully ${variables.action === 'suspend' ? 'suspended' : 'reinstated'}.`);
      setSelectedUserAction(null);
    },
    onError: () => {
      toast.error('Operation failed.');
      setSelectedUserAction(null);
    },
  });

  const agentMutation = useMutation({
    mutationFn: ({ sessionId, action }: { sessionId: string; action: 'pause' | 'resume' }) =>
      api.post(`/v1/admin/agents/${sessionId}/${action}`),
    onSuccess: (_, v) => {
      queryClient.invalidateQueries({ queryKey: ['admin-agents'] });
      toast.success(`Agent ${v.action}d successfully.`);
    },
    onError: () => toast.error('Agent operation failed.'),
  });

  const broadcastMutation = useMutation({
    mutationFn: (payload: BroadcastPayload) => api.post('/v1/admin/broadcast', payload),
    onSuccess: (r) => {
      const result = r.data.data;
      toast.success(`Broadcast delivered to ${result.recipients} users`);
      setBroadcastResult(result);
    },
    onError: () => toast.error('Broadcast failed to send.'),
  });

  const approveMutation = useMutation({
    mutationFn: (escrowId: string) => api.post(`/v1/escrow/${escrowId}/approve`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-pending-escrows'] });
      queryClient.invalidateQueries({ queryKey: ['admin-stats'] });
      toast.success('Escrow approved and smart contract deployed on-chain!');
    },
    onError: () => toast.error('Failed to approve escrow.'),
  });

  const rejectMutation = useMutation({
    mutationFn: ({ escrowId, reason }: { escrowId: string; reason: string }) =>
      api.post(`/v1/escrow/${escrowId}/reject`, { reason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-pending-escrows'] });
      queryClient.invalidateQueries({ queryKey: ['admin-stats'] });
      toast.success('Escrow rejected.');
    },
    onError: () => toast.error('Failed to reject escrow.'),
  });

  // ─── Derived Data & Filters ──────────────────────────────────────────────
  
  const pendingEnterprises = enterprises.filter((e: AdminEnterprise) => e.kyc_status === 'PENDING').slice(0, 3);
  
  const filteredEnterprises = enterprises.filter((e: AdminEnterprise) => {
    if (entKycFilter !== 'All' && e.kyc_status !== entKycFilter) return false;
    if (entRoleFilter !== 'All' && e.trade_role !== entRoleFilter) return false;
    if (entSearch && !e.legal_name.toLowerCase().includes(entSearch.toLowerCase())) return false;
    return true;
  });

  const filteredUsers = users.filter((u: { id: string; full_name: string; email: string; role: string; enterprise_name: string; status: string; last_login: string }) => {
    if (userStatusFilter !== 'All' && u.status !== userStatusFilter) return false;
    if (userRoleFilter !== 'All' && u.role !== userRoleFilter) return false;
    if (userSearch && !u.full_name.toLowerCase().includes(userSearch.toLowerCase()) && !u.email.toLowerCase().includes(userSearch.toLowerCase())) return false;
    return true;
  });

  const filteredLogs = llmLogs.filter((l: LlmLog) => {
    if (llmSessionSearch && !l.session_id.toLowerCase().includes(llmSessionSearch.toLowerCase())) return false;
    return true;
  });

  const handleUserConfirm = () => {
    if (selectedUserAction) {
      suspendMutation.mutate(selectedUserAction);
    }
  };

  return (
    <AppShell>
      <AdminGuard>
        <div className="p-6">
          
          {/* Header Card */}
          <div className="bg-gradient-to-r from-secondary/80 to-accent/80 border border-border rounded-lg p-8 mb-8">
            <h1 className="text-2xl font-semibold text-foreground">Platform Administration</h1>
            <p className="text-sm text-muted-foreground mt-1">Cadencia Super Admin &bull; {formatDate(new Date().toISOString())}</p>
            <div className="flex gap-6 mt-6">
              <div className="text-sm">
                <span className="text-muted-foreground mr-2">Total Value Locked:</span>
                <span className="text-primary font-semibold">{stats ? formatCurrency(stats.total_escrow_value) : '...'}</span>
              </div>
              <div className="text-sm">
                <span className="text-muted-foreground mr-2">Active Negotiations:</span>
                <span className="text-primary font-semibold">{stats ? stats.active_sessions : '...'}</span>
              </div>
            </div>
          </div>

          {/* Section 1: Platform Stat Cards */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
            <StatCard label="Total Enterprises" value={stats?.total_enterprises ?? '-'} icon={Building2} trend={{ direction: 'up', value: "+3 this month"}} />
            <StatCard label="Total Users" value={stats?.total_users ?? '-'} icon={Users} trend={{ direction: 'up', value: "+8 this month"}} />
            <StatCard label="Active Sessions" value={stats?.active_sessions ?? '-'} icon={Play} />
            <StatCard label="Total Escrow" value={stats ? formatCurrency(stats.total_escrow_value) : '-'} icon={Landmark} />
            <StatCard label="LLM Calls Today" value={stats?.llm_calls_today ?? '-'} icon={Brain} trend={{ direction: 'up', value: "+12%"}} />
            <StatCard label="Success Rate" value={stats ? `${stats.success_rate}%` : '-'} icon={TrendingUp} trend={{ direction: 'up', value: "+2.1%"}} />
          </div>

          {/* Section 2: Tab Navigation */}
          <AdminTabNav activeTab={activeTab} onChange={setActiveTab} pendingEscrows={stats?.pending_escrows || pendingEscrows.length} />

          {/* TAB: Overview */}
          {activeTab === 'overview' && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              
              {/* Column 1: System Health */}
              <div className="bg-card border border-border rounded-lg p-6">
                <SectionHeader title="System Health" />
                <div className="space-y-4">
                  <div className="flex justify-between items-center py-2 border-b border-border">
                    <span className="text-sm font-medium text-muted-foreground flex items-center gap-2"><Activity className="h-4 w-4" /> Database</span>
                    <HealthBadge status={health?.services?.database === 'healthy' ? 'healthy' : 'degraded'} />
                  </div>
                  <div className="flex justify-between items-center py-2 border-b border-border">
                    <span className="text-sm font-medium text-muted-foreground flex items-center gap-2"><Activity className="h-4 w-4" /> Redis Cache</span>
                    <HealthBadge status={health?.services?.redis === 'healthy' ? 'healthy' : 'degraded'} />
                  </div>
                  <div className="flex justify-between items-center py-2 border-b border-border">
                    <span className="text-sm font-medium text-muted-foreground flex items-center gap-2"><Activity className="h-4 w-4" /> Algorand Service</span>
                    <HealthBadge status={health?.services?.algorand === 'healthy' ? 'healthy' : 'degraded'} />
                  </div>
                  <div className="flex justify-between items-center py-2 border-b border-border">
                    <span className="text-sm font-medium text-muted-foreground flex items-center gap-2"><Activity className="h-4 w-4" /> LLM Engine</span>
                    <HealthBadge status={health?.services?.llm === 'healthy' ? 'healthy' : 'degraded'} />
                  </div>
                </div>
              </div>

              {/* Column 2: KYC Queue */}
              <div className="bg-card border border-border rounded-lg p-6 flex flex-col">
                <SectionHeader title={`Pending KYC (${stats?.pending_kyc || 0})`} />
                <div className="flex-1">
                  {pendingEnterprises.length > 0 ? (
                    pendingEnterprises.map((ent: AdminEnterprise) => (
                      <KycReviewCard 
                        key={ent.id} 
                        enterprise={ent} 
                        onApprove={(id) => kycMutation.mutate({ id, action: 'approve' })}
                        onReject={(id) => kycMutation.mutate({ id, action: 'reject' })}
                        isLoading={kycMutation.isPending}
                      />
                    ))
                  ) : (
                    <div className="text-sm text-muted-foreground py-8 text-center bg-muted/20 rounded-lg border border-border/50">No pending KYC documents</div>
                  )}
                </div>
                {pendingEnterprises.length > 0 && (
                  <Button variant="ghost" className="w-full mt-4 text-xs text-muted-foreground" onClick={() => setActiveTab('enterprises')}>
                    View all pending queue &rarr;
                  </Button>
                )}
              </div>

              {/* Column 3: Recent Activity */}
              <div className="bg-card border border-border rounded-lg p-6">
                <SectionHeader title="Recent Activity" />
                <div className="space-y-4">
                  {recentActivity.length > 0 ? (
                    recentActivity.map((item, idx) => (
                      <div key={item.id} className={`flex gap-3 items-start py-2 ${idx < recentActivity.length - 1 ? 'border-b border-border' : ''}`}>
                        <div className={`p-2 rounded-md ${item.event_type === 'escrow' ? 'bg-surface-soft' : 'bg-blue-50'}`}>
                          {item.event_type === 'escrow' ? <Landmark className="h-4 w-4 text-primary" /> : <Cpu className="h-4 w-4 text-blue-500" />}
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-foreground">{item.title}</p>
                          <p className="text-xs text-muted-foreground truncate">{item.detail} &bull; {formatDate(item.created_at)}</p>
                        </div>
                        {item.amount && (
                          <span className="text-xs font-mono text-primary font-medium shrink-0">{item.amount}</span>
                        )}
                      </div>
                    ))
                  ) : (
                    <div className="text-sm text-muted-foreground py-8 text-center bg-muted/20 rounded-lg border border-border/50">No recent activity</div>
                  )}
                </div>
                <Button variant="ghost" className="w-full mt-4 text-xs text-muted-foreground" onClick={() => setActiveTab('llm-logs')}>
                  View all logs &rarr;
                </Button>
              </div>

            </div>
          )}

          {/* TAB: Enterprises */}
          {activeTab === 'enterprises' && (
            <div className="space-y-4">
              <div className="bg-card border border-border rounded-lg p-4 flex flex-wrap gap-4 items-end">
                <div>
                  <label className="text-xs font-semibold text-muted-foreground uppercase mb-1.5 block">KYC Status</label>
                  <FilterChips options={[{value: 'All', label: 'All'}, {value: 'ACTIVE', label: 'ACTIVE'}, {value: 'PENDING', label: 'PENDING'}, {value: 'REJECTED', label: 'REJECTED'}]} selected={entKycFilter} onChange={setEntKycFilter} />
                </div>
                <div>
                  <label className="text-xs font-semibold text-muted-foreground uppercase mb-1 block">Trade Role</label>
                  <select 
                    className="bg-muted border border-border rounded-md text-sm px-3 py-1.5 outline-none min-w-[120px]"
                    value={entRoleFilter}
                    onChange={(e) => setEntRoleFilter(e.target.value)}
                  >
                    <option value="All">All</option>
                    <option value="BUYER">BUYER</option>
                    <option value="SELLER">SELLER</option>
                    <option value="BOTH">BOTH</option>
                  </select>
                </div>
                <div className="flex-1 min-w-[200px]">
                  <label className="text-xs font-semibold text-muted-foreground uppercase mb-1 block">Search</label>
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <input 
                      type="text" 
                      placeholder="Search company name..." 
                      className="bg-muted border border-border rounded-md text-sm pl-9 pr-3 py-1.5 outline-none w-full text-foreground max-w-sm"
                      value={entSearch}
                      onChange={(e) => setEntSearch(e.target.value)}
                    />
                  </div>
                </div>
              </div>

              <div className="bg-card border border-border rounded-lg overflow-hidden w-full overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-xs font-semibold text-muted-foreground text-left uppercase tracking-wider bg-muted/20">
                      <th className="px-6 py-4">Enterprise</th>
                      <th className="px-6 py-4">Trade Role</th>
                      <th className="px-6 py-4">KYC</th>
                      <th className="px-6 py-4 text-center">Users</th>
                      <th className="px-6 py-4 truncate">Created</th>
                      <th className="px-6 py-4 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredEnterprises.map((ent: AdminEnterprise) => (
                      <tr key={ent.id} className="border-b border-border hover:bg-muted/30">
                        <td className="px-6 py-4">
                          <p className="font-medium text-foreground">{ent.legal_name}</p>
                          <p className="text-xs text-muted-foreground font-mono mt-0.5">{ent.id}</p>
                        </td>
                        <td className="px-6 py-4">
                          <StatusBadge status={ent.trade_role} size="sm" />
                        </td>
                        <td className="px-6 py-4">
                          <StatusBadge status={ent.kyc_status} size="sm" />
                        </td>
                        <td className="px-6 py-4 text-center font-mono text-muted-foreground">
                          {ent.user_count}
                        </td>
                        <td className="px-6 py-4 text-xs text-muted-foreground whitespace-nowrap">
                          {formatDate(ent.created_at)}
                        </td>
                        <td className="px-6 py-4 text-right">
                          <div className="flex justify-end gap-2 items-center">
                            {ent.kyc_status === 'PENDING' && (
                              <>
                                <Button size="sm" className="h-7 text-xs bg-primary text-primary-foreground" onClick={() => kycMutation.mutate({ id: ent.id, action: 'approve' })}>Approve</Button>
                                <Button size="sm" variant="outline" className="h-7 text-xs border-destructive text-destructive" onClick={() => kycMutation.mutate({ id: ent.id, action: 'reject' })}>Reject</Button>
                              </>
                            )}
                            {ent.kyc_status === 'ACTIVE' && (
                              <Button size="sm" variant="ghost" className="h-7 text-xs text-destructive hover:text-destructive hover:bg-destructive/10" onClick={() => kycMutation.mutate({ id: ent.id, action: 'revoke' })}>Revoke</Button>
                            )}
                            {ent.kyc_status === 'REJECTED' && (
                              <Button size="sm" variant="ghost" className="h-7 text-xs">Re-review</Button>
                            )}
                            <Button size="icon" variant="ghost" className="h-7 w-7 text-muted-foreground"><Eye className="h-4 w-4" /></Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                    {filteredEnterprises.length === 0 && (
                      <tr><td colSpan={6} className="px-6 py-8 text-center text-muted-foreground">No enterprises found matching criteria.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* TAB: Users */}
          {activeTab === 'users' && (
            <div className="space-y-4">
              <div className="bg-card border border-border rounded-lg p-4 flex flex-wrap gap-4 items-end">
                <div>
                  <label className="text-xs font-semibold text-muted-foreground uppercase mb-1.5 block">Status</label>
                  <FilterChips options={[{value: 'All', label: 'All'}, {value: 'ACTIVE', label: 'ACTIVE'}, {value: 'SUSPENDED', label: 'SUSPENDED'}]} selected={userStatusFilter} onChange={setUserStatusFilter} />
                </div>
                <div>
                  <label className="text-xs font-semibold text-muted-foreground uppercase mb-1.5 block">Role</label>
                  <FilterChips options={[{value: 'All', label: 'All'}, {value: 'ADMIN', label: 'ADMIN'}, {value: 'MEMBER', label: 'MEMBER'}]} selected={userRoleFilter} onChange={setUserRoleFilter} />
                </div>
                <div className="flex-1 min-w-[200px]">
                  <label className="text-xs font-semibold text-muted-foreground uppercase mb-1 block">Search</label>
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <input 
                      type="text" 
                      placeholder="Search name or email..." 
                      className="bg-muted border border-border rounded-md text-sm pl-9 pr-3 py-1.5 outline-none w-full text-foreground max-w-sm"
                      value={userSearch}
                      onChange={(e) => setUserSearch(e.target.value)}
                    />
                  </div>
                </div>
              </div>

              <div className="bg-card border border-border rounded-lg overflow-hidden w-full overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-xs font-semibold text-muted-foreground text-left uppercase tracking-wider bg-muted/20">
                      <th className="px-6 py-4">User</th>
                      <th className="px-6 py-4">Enterprise</th>
                      <th className="px-6 py-4">Role</th>
                      <th className="px-6 py-4">Status</th>
                      <th className="px-6 py-4 truncate">Last Login</th>
                      <th className="px-6 py-4 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredUsers.map((user: { id: string; full_name: string; email: string; role: string; enterprise_name: string; status: string; last_login: string }) => (
                      <tr key={user.id} className="border-b border-border hover:bg-muted/30">
                        <td className="px-6 py-4">
                          <p className="font-medium text-foreground">{user.full_name}</p>
                          <p className="text-xs text-muted-foreground mt-0.5 truncate max-w-[150px]">{user.email}</p>
                        </td>
                        <td className="px-6 py-4 text-xs text-muted-foreground">
                          {user.enterprise_name}
                        </td>
                        <td className="px-6 py-4">
                          <StatusBadge status={user.role} size="sm" />
                        </td>
                        <td className="px-6 py-4">
                          <StatusBadge status={user.status} size="sm" />
                        </td>
                        <td className="px-6 py-4 text-xs text-muted-foreground whitespace-nowrap">
                          {formatDate(user.last_login)}
                        </td>
                        <td className="px-6 py-4 text-right">
                          <div className="flex justify-end gap-2 items-center">
                            {user.status === 'ACTIVE' ? (
                              <Button 
                                size="sm" 
                                variant="ghost" 
                                className="h-7 text-xs text-destructive hover:bg-destructive/10 hover:text-destructive"
                                onClick={() => setSelectedUserAction({ id: user.id, action: 'suspend', name: user.full_name })}
                              >
                                Suspend
                              </Button>
                            ) : (
                              <Button 
                                size="sm" 
                                variant="outline" 
                                className="h-7 text-xs text-primary border-primary/50 hover:bg-primary/10"
                                onClick={() => setSelectedUserAction({ id: user.id, action: 'reinstate', name: user.full_name })}
                              >
                                Reinstate
                              </Button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                    {filteredUsers.length === 0 && (
                      <tr><td colSpan={6} className="px-6 py-8 text-center text-muted-foreground">No users found matching criteria.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>

              <ConfirmDialog
                open={!!selectedUserAction}
                onOpenChange={(v) => !v && setSelectedUserAction(null)}
                title={selectedUserAction?.action === 'suspend' ? 'Suspend User' : 'Reinstate User'}
                description={
                  selectedUserAction?.action === 'suspend'
                    ? `Suspend ${selectedUserAction?.name}? They will be locked out immediately.`
                    : `Reinstate ${selectedUserAction?.name}? They will regain full access.`
                }
                confirmLabel={selectedUserAction?.action === 'suspend' ? 'Suspend' : 'Reinstate'}
                variant={selectedUserAction?.action === 'suspend' ? 'destructive' : 'default'}
                onConfirm={handleUserConfirm}
                isLoading={suspendMutation.isPending}
              />
            </div>
          )}

          {/* TAB: Agents */}
          {activeTab === 'agents' && (
            <div className="bg-card border border-border rounded-lg overflow-hidden">
              <div className="flex items-center px-6 py-4 border-b border-border bg-muted/20">
                <div className="flex items-center gap-2">
                  <div className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
                  <span className="text-sm font-medium text-foreground">{agents.length} agents running centrally</span>
                </div>
              </div>
              <div className="w-full overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-xs font-semibold text-muted-foreground text-left uppercase tracking-wider bg-accent/20">
                      <th className="px-6 py-4">Monitor Panel</th>
                    </tr>
                  </thead>
                  <tbody>
                    {agents.map((agent: AdminAgent) => (
                      <tr key={agent.session_id} className="border-b border-border hover:bg-muted/10">
                        <td className="px-6 py-4">
                          <AgentMonitorRow 
                            agent={agent} 
                            onPause={(id) => agentMutation.mutate({ sessionId: id, action: 'pause' })} 
                            onResume={(id) => agentMutation.mutate({ sessionId: id, action: 'resume' })} 
                            isLoading={agentMutation.isPending} 
                          />
                        </td>
                      </tr>
                    ))}
                    {agents.length === 0 && (
                      <tr><td className="px-6 py-8 text-center text-muted-foreground">No active agent sessions.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* TAB: Escrow Queue */}
          {activeTab === 'escrows' && (
            <div className="space-y-4">
              <div className="bg-card border border-border rounded-lg p-4 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-primary/10">
                    <Landmark className="h-5 w-5 text-primary" />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-foreground">Pending Escrow Approvals</h3>
                    <p className="text-xs text-muted-foreground">Review and approve escrow deployments to deploy smart contracts on-chain</p>
                  </div>
                </div>
                <span className="text-2xl font-bold text-primary">{pendingEscrows.length}</span>
              </div>

              <div className="bg-card border border-border rounded-lg overflow-hidden">
                <div className="w-full overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-xs font-semibold text-muted-foreground text-left uppercase tracking-wider bg-muted/20">
                        <th className="px-6 py-4">Session</th>
                        <th className="px-6 py-4">Buyer</th>
                        <th className="px-6 py-4">Seller</th>
                        <th className="px-6 py-4">Price (INR)</th>
                        <th className="px-6 py-4">Amount (ALGO)</th>
                        <th className="px-6 py-4">Submitted</th>
                        <th className="px-6 py-4 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pendingEscrows.map((item) => (
                        <tr key={item.escrow_id} className="border-b border-border hover:bg-muted/30 transition-colors">
                          <td className="px-6 py-4">
                            <span className="font-mono text-xs text-primary">{item.session_id.slice(0, 12)}...</span>
                          </td>
                          <td className="px-6 py-4 font-medium text-foreground">{item.buyer_name}</td>
                          <td className="px-6 py-4 font-medium text-foreground">{item.seller_name}</td>
                          <td className="px-6 py-4">
                            <span className="font-semibold text-foreground">
                              {item.agreed_price_inr ? `₹${item.agreed_price_inr.toLocaleString()}` : '—'}
                            </span>
                          </td>
                          <td className="px-6 py-4">
                            <span className="font-mono text-sm text-primary font-semibold">{item.amount_algo.toFixed(3)} ALGO</span>
                          </td>
                          <td className="px-6 py-4 text-xs text-muted-foreground whitespace-nowrap">
                            {formatDate(item.created_at)}
                          </td>
                          <td className="px-6 py-4 text-right">
                            <div className="flex justify-end gap-2">
                              <Button
                                size="sm"
                                variant="default"
                                className="h-8 text-xs gap-1"
                                onClick={() => approveMutation.mutate(item.escrow_id)}
                                disabled={approveMutation.isPending || rejectMutation.isPending}
                              >
                                <CheckCircle className="h-3.5 w-3.5" />
                                Approve & Deploy
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-8 text-xs text-destructive hover:bg-destructive/10 hover:text-destructive gap-1"
                                onClick={() => {
                                  const reason = window.prompt('Reason for rejection (min 5 chars):');
                                  if (reason && reason.length >= 5) {
                                    rejectMutation.mutate({ escrowId: item.escrow_id, reason });
                                  } else if (reason) {
                                    toast.error('Reason must be at least 5 characters.');
                                  }
                                }}
                                disabled={approveMutation.isPending || rejectMutation.isPending}
                              >
                                <XCircle className="h-3.5 w-3.5" />
                                Reject
                              </Button>
                            </div>
                          </td>
                        </tr>
                      ))}
                      {pendingEscrows.length === 0 && (
                        <tr>
                          <td colSpan={7} className="px-6 py-12 text-center">
                            <div className="flex flex-col items-center gap-3">
                              <div className="p-3 rounded-full bg-muted">
                                <CheckCircle className="h-6 w-6 text-muted-foreground" />
                              </div>
                              <p className="text-sm text-muted-foreground">All caught up! No escrows pending approval.</p>
                            </div>
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* TAB: LLM Logs */}
          {activeTab === 'llm-logs' && (
            <div className="space-y-4">
              <div className="bg-card border border-border rounded-lg p-4 flex gap-4 items-center">
                <div className="flex-1 w-full max-w-md">
                  <label className="text-xs font-semibold text-muted-foreground uppercase mb-1 block">Session ID Search</label>
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <input 
                      type="text" 
                      placeholder="e.g. sess-001" 
                      className="bg-muted border border-border rounded-md text-sm pl-9 pr-3 py-1.5 outline-none w-full text-foreground"
                      value={llmSessionSearch}
                      onChange={(e) => setLlmSessionSearch(e.target.value)}
                    />
                  </div>
                </div>
              </div>

              <div className="bg-card border border-border rounded-lg overflow-hidden w-full overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-xs font-semibold text-muted-foreground text-left uppercase tracking-wider bg-muted/20">
                      <th className="px-6 py-4">Log ID / Session</th>
                      <th className="px-6 py-4 text-center">Round</th>
                      <th className="px-6 py-4">Agent</th>
                      <th className="px-6 py-4">Latency</th>
                      <th className="px-6 py-4">Tokens (P/C)</th>
                      <th className="px-6 py-4">Status</th>
                      <th className="px-6 py-4 text-right">View</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredLogs.map((log: LlmLog) => (
                      <tr key={log.id} className="border-b border-border hover:bg-muted/30">
                        <td className="px-6 py-4 flex flex-col gap-0.5">
                          <span className="font-mono text-[10px] text-muted-foreground">{log.id}</span>
                          <span className="font-mono text-xs text-primary">{log.session_id}</span>
                        </td>
                        <td className="px-6 py-4 text-center font-mono text-xs">{log.round}</td>
                        <td className="px-6 py-4"><StatusBadge status={log.agent} size="sm" /></td>
                        <td className="px-6 py-4">
                          <span className={`font-mono text-xs font-medium ${log.latency_ms < 500 ? 'text-green-600' : log.latency_ms < 2000 ? 'text-amber-500' : 'text-destructive'}`}>
                            {log.latency_ms}ms
                          </span>
                        </td>
                        <td className="px-6 py-4 font-mono text-xs text-muted-foreground">
                          {log.prompt_tokens} / {log.completion_tokens}
                        </td>
                        <td className="px-6 py-4">
                          <StatusBadge status={log.status} size="sm" />
                        </td>
                        <td className="px-6 py-4 text-right">
                          <Button size="icon" variant="ghost" className="h-7 w-7 text-muted-foreground hover:text-foreground" onClick={() => setSelectedLog(log)}>
                            <Eye className="h-4 w-4" />
                          </Button>
                        </td>
                      </tr>
                    ))}
                    {filteredLogs.length === 0 && (
                      <tr><td colSpan={7} className="px-6 py-8 text-center text-muted-foreground">No logs found matching criteria.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>

              <LlmLogDrawer open={!!selectedLog} log={selectedLog} onClose={() => setSelectedLog(null)} />
            </div>
          )}

          {/* TAB: Broadcast */}
          {activeTab === 'broadcast' && (
            <div className="flex justify-center mt-6">
              <div className="w-full flex flex-col max-w-2xl gap-8">
                <BroadcastForm 
                  onSend={(data) => broadcastMutation.mutate(data)} 
                  isSending={broadcastMutation.isPending}
                  lastResult={broadcastResult}
                />
              </div>
            </div>
          )}

        </div>
      </AdminGuard>
    </AppShell>
  );
}
