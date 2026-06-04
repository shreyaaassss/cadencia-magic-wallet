'use client';

import * as React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, Plus, Pencil, Trash2, Package, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';

import { AppShell } from '@/components/layout/AppShell';
import { SellerRoleGuard } from '@/components/shared/SellerRoleGuard';
import { SectionHeader } from '@/components/shared/SectionHeader';
import { useAuth } from '@/hooks/useAuth';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

interface CatalogueItem {
  id: string;
  product_name: string;
  hsn_code: string;
  product_category: string;
  grade: string | null;
  unit: string;
  price_per_unit_inr: number;
  bulk_pricing_tiers: any[] | null;
  moq: number;
  max_order_qty: number;
  lead_time_days: number;
  in_stock_qty: number;
  is_active: boolean;
  certifications: string[];
  created_at: string;
}

const CATEGORIES = [
  'HR_COIL', 'CR_COIL', 'TMT_BAR', 'WIRE_ROD', 'BILLET', 'SLAB',
  'PLATE', 'PIPE', 'SHEET', 'ANGLE', 'CHANNEL', 'BEAM', 'CUSTOM',
];

const UNITS = ['MT', 'KG', 'PIECE', 'BUNDLE', 'COIL'];

function formatCategory(cat: string) {
  return cat.replace(/_/g, ' ');
}

export default function CataloguePage() {
  const { enterprise } = useAuth();
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = React.useState(false);
  const [editingId, setEditingId] = React.useState<string | null>(null);

  const { data: items = [], isLoading } = useQuery<CatalogueItem[]>({
    queryKey: ['catalogue'],
    queryFn: () => api.get('/v1/marketplace/catalogue?active_only=false').then(r => r.data.data || []),
  });

  const { data: profile } = useQuery<{ min_order_value: number }>({
    queryKey: ['capability-profile'],
    queryFn: () => api.get('/v1/marketplace/capability-profile').then(r => r.data.data),
  });

  // Check for profile-catalogue inconsistency: items whose MOQ * price < profile min_order_value
  const inconsistentItems = React.useMemo(() => {
    if (!profile?.min_order_value || items.length === 0) return [];
    return items.filter(
      (item) => item.is_active && item.moq * item.price_per_unit_inr < profile.min_order_value,
    );
  }, [items, profile]);

  const deactivateMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/v1/marketplace/catalogue/${id}`),
    onSuccess: () => {
      toast.success('Item deactivated');
      queryClient.invalidateQueries({ queryKey: ['catalogue'] });
    },
    onError: () => toast.error('Failed to deactivate item'),
  });

  return (
    <AppShell>
      <SellerRoleGuard>
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <SectionHeader
              title="Product Catalogue"
              description="Manage your product listings, pricing tiers, and lead times."
            />
            <Button onClick={() => { setEditingId(null); setShowForm(true); }} className="bg-primary text-primary-foreground">
              <Plus className="h-4 w-4 mr-1.5" /> Add Product
            </Button>
          </div>

          {inconsistentItems.length > 0 && profile && (
            <div className="flex items-start gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 dark:border-amber-500/40 dark:bg-amber-950/30">
              <AlertTriangle className="h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400 mt-0.5" />
              <p className="text-sm text-amber-800 dark:text-amber-300">
                <span className="font-semibold">Profile-Catalogue Inconsistency:</span>{' '}
                {inconsistentItems.length} item{inconsistentItems.length > 1 ? 's' : ''} have MOQ
                value below your profile minimum order value of{' '}
                {new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(profile.min_order_value)}.
                This may reduce your match quality.
              </p>
            </div>
          )}

          {showForm && (
            <CatalogueForm
              editingId={editingId}
              onClose={() => { setShowForm(false); setEditingId(null); }}
              onSaved={() => {
                setShowForm(false);
                setEditingId(null);
                queryClient.invalidateQueries({ queryKey: ['catalogue'] });
              }}
            />
          )}

          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : items.length === 0 ? (
            <div className="text-center py-16 border border-dashed border-border rounded-lg">
              <Package className="h-10 w-10 mx-auto text-muted-foreground mb-3" />
              <p className="text-sm text-muted-foreground">No products in your catalogue yet.</p>
              <Button variant="ghost" className="mt-3" onClick={() => setShowForm(true)}>
                Add your first product
              </Button>
            </div>
          ) : (
            <div className="border border-border rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-muted/50">
                  <tr>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Product</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Category</th>
                    <th className="text-right px-4 py-3 font-medium text-muted-foreground">Price/Unit</th>
                    <th className="text-right px-4 py-3 font-medium text-muted-foreground">MOQ</th>
                    <th className="text-right px-4 py-3 font-medium text-muted-foreground">Lead Time</th>
                    <th className="text-center px-4 py-3 font-medium text-muted-foreground">Status</th>
                    <th className="text-right px-4 py-3 font-medium text-muted-foreground">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.id} className="border-t border-border hover:bg-muted/30 transition-colors">
                      <td className="px-4 py-3">
                        <div className="font-medium text-foreground">{item.product_name}</div>
                        {item.grade && <div className="text-xs text-muted-foreground">Grade: {item.grade}</div>}
                        <div className="text-xs text-muted-foreground">HSN: {item.hsn_code}</div>
                      </td>
                      <td className="px-4 py-3 text-foreground">{formatCategory(item.product_category)}</td>
                      <td className="px-4 py-3 text-right text-foreground font-medium">
                        {new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(item.price_per_unit_inr)}/{item.unit}
                      </td>
                      <td className="px-4 py-3 text-right text-foreground">{item.moq} {item.unit}</td>
                      <td className="px-4 py-3 text-right text-foreground">{item.lead_time_days}d</td>
                      <td className="px-4 py-3 text-center">
                        <span className={cn('inline-block px-2 py-0.5 rounded-full text-xs font-medium', item.is_active ? 'bg-green-50 text-green-600' : 'bg-muted text-muted-foreground')}>
                          {item.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            onClick={() => { setEditingId(item.id); setShowForm(true); }}
                            className="p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                          {item.is_active && (
                            <button
                              onClick={() => deactivateMutation.mutate(item.id)}
                              className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </SellerRoleGuard>
    </AppShell>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Catalogue Item Form (Create / Edit)
// ─────────────────────────────────────────────────────────────────────────────

function CatalogueForm({
  editingId,
  onClose,
  onSaved,
}: {
  editingId: string | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = React.useState({
    product_name: '',
    hsn_code: '',
    product_category: 'CUSTOM',
    grade: '',
    unit: 'MT',
    price_per_unit_inr: '',
    moq: '',
    max_order_qty: '',
    lead_time_days: '',
    in_stock_qty: '0',
    certifications: [] as string[],
  });

  // Load existing item for edit
  const { data: editItemData, isLoading: loadingItem } = useQuery({
    queryKey: ['catalogue-item', editingId],
    queryFn: () => api.get(`/v1/marketplace/catalogue/${editingId}`).then(r => r.data.data),
    enabled: !!editingId,
  });

  React.useEffect(() => {
    if (editItemData) {
      const d = editItemData as any;
      setForm({
        product_name: d.product_name || '',
        hsn_code: d.hsn_code || '',
        product_category: d.product_category || 'CUSTOM',
        grade: d.grade || '',
        unit: d.unit || 'MT',
        price_per_unit_inr: String(d.price_per_unit_inr || ''),
        moq: String(d.moq || ''),
        max_order_qty: String(d.max_order_qty || ''),
        lead_time_days: String(d.lead_time_days || ''),
        in_stock_qty: String(d.in_stock_qty || '0'),
        certifications: d.certifications || [],
      });
    }
  }, [editItemData]);

  const saveMutation = useMutation({
    mutationFn: (body: Record<string, any>) => {
      if (editingId) {
        return api.put(`/v1/marketplace/catalogue/${editingId}`, body);
      }
      return api.post('/v1/marketplace/catalogue', body);
    },
    onSuccess: () => {
      toast.success(editingId ? 'Product updated' : 'Product added to catalogue');
      onSaved();
    },
    onError: (err: any) => {
      const detail = err.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'Failed to save product');
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    saveMutation.mutate({
      product_name: form.product_name,
      hsn_code: form.hsn_code,
      product_category: form.product_category,
      grade: form.grade || null,
      unit: form.unit,
      price_per_unit_inr: parseFloat(form.price_per_unit_inr),
      moq: parseFloat(form.moq),
      max_order_qty: parseFloat(form.max_order_qty),
      lead_time_days: parseInt(form.lead_time_days),
      in_stock_qty: parseFloat(form.in_stock_qty || '0'),
      certifications: form.certifications,
    });
  };

  const update = (field: string, value: any) => setForm(f => ({ ...f, [field]: value }));

  return (
    <div className="border border-border rounded-lg p-5 bg-card">
      <h3 className="text-sm font-semibold text-foreground mb-4">{editingId ? 'Edit Product' : 'Add Product'}</h3>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">Product Name *</label>
            <Input value={form.product_name} onChange={e => update('product_name', e.target.value)} required minLength={3} />
          </div>
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">HSN Code *</label>
            <Input value={form.hsn_code} onChange={e => update('hsn_code', e.target.value)} required pattern="\d{4,8}" />
          </div>
        </div>

        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">Category *</label>
            <Select value={form.product_category} onValueChange={v => update('product_category', v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent className="bg-popover border-border max-h-60">
                {CATEGORIES.map(c => <SelectItem key={c} value={c}>{formatCategory(c)}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">Grade</label>
            <Input value={form.grade} onChange={e => update('grade', e.target.value)} placeholder="e.g. Fe500D" />
          </div>
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">Unit *</label>
            <Select value={form.unit} onValueChange={v => update('unit', v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent className="bg-popover border-border">
                {UNITS.map(u => <SelectItem key={u} value={u}>{u}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">Price per {form.unit} (INR) *</label>
            <Input type="number" step="0.01" value={form.price_per_unit_inr} onChange={e => update('price_per_unit_inr', e.target.value)} required />
          </div>
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">MOQ ({form.unit}) *</label>
            <Input type="number" step="0.01" value={form.moq} onChange={e => update('moq', e.target.value)} required />
          </div>
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">Max Order ({form.unit}) *</label>
            <Input type="number" step="0.01" value={form.max_order_qty} onChange={e => update('max_order_qty', e.target.value)} required />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">Lead Time (days) *</label>
            <Input type="number" value={form.lead_time_days} onChange={e => update('lead_time_days', e.target.value)} required min={1} max={180} />
          </div>
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">In-Stock Qty</label>
            <Input type="number" step="0.01" value={form.in_stock_qty} onChange={e => update('in_stock_qty', e.target.value)} />
          </div>
        </div>

        <div className="flex gap-3 pt-2">
          <Button type="button" variant="ghost" onClick={onClose} className="hover:bg-accent text-foreground">
            Cancel
          </Button>
          <Button type="submit" disabled={saveMutation.isPending} className="flex-1 bg-primary text-primary-foreground">
            {saveMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : editingId ? 'Update Product' : 'Add Product'}
          </Button>
        </div>
      </form>
    </div>
  );
}
