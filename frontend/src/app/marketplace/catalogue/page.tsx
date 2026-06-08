'use client';

import * as React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, Plus, Pencil, Trash2, Package, AlertTriangle, Upload, FileDown } from 'lucide-react';
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
  specification_text: string | null;
  unit: string;
  price_per_unit_inr: number;
  bulk_pricing_tiers: any[] | null;
  moq: number;
  max_order_qty: number;
  lead_time_days: number;
  in_stock_qty: number;
  is_active: boolean;
  certifications: string[];
  floor_price_inr: number | null;
  max_discount_pct: number | null;
  negotiation_enabled: boolean;
  created_at: string;
}

// Industry-agnostic: well-known categories as suggestions, free-form input allowed
const CATEGORY_SUGGESTIONS = [
  'HR_COIL', 'CR_COIL', 'TMT_BAR', 'WIRE_ROD', 'BILLET', 'SLAB',
  'PLATE', 'PIPE', 'SHEET', 'ANGLE', 'CHANNEL', 'BEAM',
  'DSLR_CAMERA', 'LENS', 'TRIPOD', 'ELECTRONICS', 'TEXTILE', 'CHEMICAL',
  'CUSTOM',
];

const UNITS = ['MT', 'KG', 'PIECE', 'BUNDLE', 'COIL', 'LITRE', 'METRE', 'DOZEN', 'UNIT', 'BOX'];

const CERT_SUGGESTIONS = ['ISO 9001', 'BIS', 'RDSO', 'ISO 14001', 'NABL', 'CE', 'FCC', 'FSSAI'];

function formatCategory(cat: string) {
  return cat.replace(/_/g, ' ');
}

export default function CataloguePage() {
  const { enterprise } = useAuth();
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = React.useState(false);
  const [editingId, setEditingId] = React.useState<string | null>(null);
  const [searchQuery, setSearchQuery] = React.useState('');
  const [filterActive, setFilterActive] = React.useState<'all' | 'active' | 'inactive'>('all');
  const [sortBy, setSortBy] = React.useState<'name' | 'price' | 'stock'>('name');

  // ─── Bulk Import state ──────────────────────────────────────────────────
  const [showBulkImport, setShowBulkImport] = React.useState(false);
  const [bulkStep, setBulkStep] = React.useState<'upload' | 'validate' | 'import'>('upload');
  const [bulkRows, setBulkRows] = React.useState<any[]>([]);
  const [bulkErrors, setBulkErrors] = React.useState<Record<number, string>>({});
  const [bulkSelected, setBulkSelected] = React.useState<Set<number>>(new Set());

  const { data: items = [], isLoading } = useQuery<CatalogueItem[]>({
    queryKey: ['catalogue'],
    queryFn: () => api.get('/v1/marketplace/catalogue?active_only=false').then(r => r.data.data || []),
  });

  const { data: embeddingStatus } = useQuery<{ embedding_status: string; last_embedded_at: string | null }>({
    queryKey: ['embedding-status'],
    queryFn: () => api.get('/v1/marketplace/task-status/embedding').then(r => r.data.data),
    refetchInterval: 5000,  // poll every 5s while COMPUTING
  });

  const { data: profile } = useQuery<{ min_order_value: number }>({
    queryKey: ['capability-profile'],
    queryFn: () => api.get('/v1/marketplace/capability-profile').then(r => r.data.data),
  });

  // Filter + search + sort
  const filteredItems = React.useMemo(() => {
    let result = items;
    if (filterActive === 'active') result = result.filter(i => i.is_active);
    if (filterActive === 'inactive') result = result.filter(i => !i.is_active);
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      result = result.filter(i =>
        i.product_name.toLowerCase().includes(q) ||
        i.hsn_code.includes(q) ||
        i.product_category.toLowerCase().includes(q)
      );
    }
    if (sortBy === 'price') result = [...result].sort((a, b) => a.price_per_unit_inr - b.price_per_unit_inr);
    else if (sortBy === 'stock') result = [...result].sort((a, b) => a.in_stock_qty - b.in_stock_qty);
    else result = [...result].sort((a, b) => a.product_name.localeCompare(b.product_name));
    return result;
  }, [items, filterActive, searchQuery, sortBy]);

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
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setShowBulkImport(true)} className="border-border">
                <Upload className="h-4 w-4 mr-1.5" /> Bulk Import
              </Button>
              <Button onClick={() => { setEditingId(null); setShowForm(true); }} className="bg-primary text-primary-foreground">
                <Plus className="h-4 w-4 mr-1.5" /> Add Product
              </Button>
            </div>
          </div>

          {/* Embedding status banner */}
          {embeddingStatus?.embedding_status === 'COMPUTING' && (
            <div className="flex items-center gap-2 rounded-lg border border-blue-300 bg-blue-50 px-4 py-3 dark:border-blue-500/40 dark:bg-blue-950/30">
              <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
              <p className="text-sm text-blue-800 dark:text-blue-300">
                Profile embedding updating — your new products will be visible to buyers shortly.
              </p>
            </div>
          )}
          {embeddingStatus?.embedding_status === 'FAILED' && (
            <div className="flex items-start gap-2 rounded-lg border border-red-300 bg-red-50 px-4 py-3 dark:border-red-500/40 dark:bg-red-950/30">
              <AlertTriangle className="h-5 w-5 shrink-0 text-red-600 mt-0.5" />
              <p className="text-sm text-red-800 dark:text-red-300">
                Profile embedding failed. Your latest products may not appear in buyer searches.
                Try adding or updating a product to trigger a retry.
              </p>
            </div>
          )}

          {/* Search + Filter bar */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex-1 min-w-[200px]">
              <Input
                placeholder="Search products, HSN codes, categories..."
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                className="h-9"
              />
            </div>
            <div className="flex gap-1.5">
              {(['all', 'active', 'inactive'] as const).map(f => (
                <button key={f} onClick={() => setFilterActive(f)}
                  className={cn('px-3 py-1.5 rounded-md text-xs font-medium transition-colors',
                    filterActive === f ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:bg-accent')}>
                  {f === 'all' ? 'All' : f === 'active' ? 'Active' : 'Inactive'}
                </button>
              ))}
            </div>
            <Select value={sortBy} onValueChange={v => setSortBy(v as 'name' | 'price' | 'stock')}>
              <SelectTrigger className="w-[140px] h-9"><SelectValue placeholder="Sort by" /></SelectTrigger>
              <SelectContent className="bg-popover border-border">
                <SelectItem value="name">Name</SelectItem>
                <SelectItem value="price">Price</SelectItem>
                <SelectItem value="stock">Stock</SelectItem>
              </SelectContent>
            </Select>
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
          ) : filteredItems.length === 0 && items.length === 0 ? (
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
                    <th className="text-right px-4 py-3 font-medium text-muted-foreground">Stock</th>
                    <th className="text-right px-4 py-3 font-medium text-muted-foreground">Lead Time</th>
                    <th className="text-center px-4 py-3 font-medium text-muted-foreground">Status</th>
                    <th className="text-right px-4 py-3 font-medium text-muted-foreground">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredItems.map((item) => (
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
                      <td className="px-4 py-3 text-right">
                        <span className={cn('inline-flex items-center gap-1 text-xs font-medium',
                          item.in_stock_qty <= 0 ? 'text-red-600' :
                          item.in_stock_qty < item.moq ? 'text-amber-600' : 'text-green-600'
                        )}>
                          <span className={cn('h-1.5 w-1.5 rounded-full',
                            item.in_stock_qty <= 0 ? 'bg-red-500' :
                            item.in_stock_qty < item.moq ? 'bg-amber-500' : 'bg-green-500'
                          )} />
                          {item.in_stock_qty} {item.unit}
                        </span>
                      </td>
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

          {/* ── Bulk Import Modal ──────────────────────────────────────────── */}
          {showBulkImport && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
              <div className="bg-card border border-border rounded-xl shadow-xl w-full max-w-3xl max-h-[85vh] overflow-y-auto p-6">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-lg font-semibold text-foreground">Bulk Import Products</h2>
                  <Button variant="ghost" size="sm" onClick={() => { setShowBulkImport(false); setBulkStep('upload'); setBulkRows([]); }}>✕</Button>
                </div>

                {/* Step 1: Upload */}
                {bulkStep === 'upload' && (
                  <div className="space-y-4">
                    <p className="text-sm text-muted-foreground">Upload a CSV file with your product catalogue. Max 200 items per import.</p>
                    <div className="flex gap-3">
                      <Button variant="outline" size="sm" onClick={() => {
                        const hdr = ['product_name','hsn_code','product_category','unit','price_per_unit_inr','moq','max_order_qty','lead_time_days','in_stock_qty','grade','specification_text','certifications','floor_price_inr','max_discount_pct'];
                        const example = ['HR Coil IS2062','7209','HR_COIL','MT','45000','50','500','14','200','E250','IS 2062 Grade E250','BIS,ISO 9001','40000','10'];
                        const csv = [hdr.join(','), example.join(',')].join('\n');
                        const blob = new Blob([csv], { type: 'text/csv' });
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a'); a.href = url; a.download = 'cadencia_catalogue_template.csv'; a.click();
                        URL.revokeObjectURL(url);
                      }}>
                        <FileDown className="h-3.5 w-3.5 mr-1" /> Download Template
                      </Button>
                    </div>
                    <label className="flex flex-col items-center justify-center w-full h-32 border-2 border-dashed border-border rounded-lg cursor-pointer hover:border-primary/50 transition-colors">
                      <Upload className="h-8 w-8 text-muted-foreground mb-2" />
                      <span className="text-sm text-muted-foreground">Click to upload CSV</span>
                      <input type="file" accept=".csv" className="hidden" onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (!file) return;
                        const reader = new FileReader();
                        reader.onload = (ev) => {
                          const text = ev.target?.result as string;
                          const lines = text.split('\n').filter(l => l.trim());
                          if (lines.length < 2) { toast.error('CSV must have a header row and at least one data row'); return; }
                          const headers = lines[0].split(',').map(h => h.trim());
                          const rows = lines.slice(1).map((line, idx) => {
                            const vals = line.split(',').map(v => v.trim());
                            const row: Record<string, string> = {};
                            headers.forEach((h, i) => { row[h] = vals[i] || ''; });
                            row._idx = String(idx);
                            return row;
                          });
                          if (rows.length > 200) { toast.error('Maximum 200 items per import'); return; }
                          // Validate
                          const errors: Record<number, string> = {};
                          const selected = new Set<number>();
                          rows.forEach((r, i) => {
                            const errs: string[] = [];
                            if (!r.product_name) errs.push('product_name required');
                            if (r.hsn_code && !/^\d{4,8}$/.test(r.hsn_code)) errs.push('hsn_code must be 4-8 digits');
                            if (!r.price_per_unit_inr || Number(r.price_per_unit_inr) <= 0) errs.push('price must be positive');
                            if (r.lead_time_days && (Number(r.lead_time_days) < 1 || Number(r.lead_time_days) > 180)) errs.push('lead_time 1-180');
                            if (r.moq && r.max_order_qty && Number(r.max_order_qty) < Number(r.moq)) errs.push('max_qty >= moq');
                            if (errs.length) errors[i] = errs.join('; ');
                            else selected.add(i);
                          });
                          setBulkRows(rows);
                          setBulkErrors(errors);
                          setBulkSelected(selected);
                          setBulkStep('validate');
                        };
                        reader.readAsText(file);
                      }} />
                    </label>
                  </div>
                )}

                {/* Step 2: Validate */}
                {bulkStep === 'validate' && (
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <p className="text-sm">
                        <span className="text-green-600 font-medium">{bulkSelected.size} valid</span>
                        {Object.keys(bulkErrors).length > 0 && <span className="text-amber-600 font-medium"> · {Object.keys(bulkErrors).length} invalid</span>}
                      </p>
                      <Button variant="outline" size="sm" onClick={() => setBulkStep('upload')}>Back</Button>
                    </div>
                    <div className="overflow-x-auto max-h-80 border border-border rounded-lg">
                      <table className="w-full text-xs">
                        <thead className="bg-muted sticky top-0">
                          <tr>
                            <th className="px-2 py-1.5 text-left w-8"></th>
                            <th className="px-2 py-1.5 text-left">Product</th>
                            <th className="px-2 py-1.5 text-left">HSN</th>
                            <th className="px-2 py-1.5 text-left">Unit</th>
                            <th className="px-2 py-1.5 text-right">Price</th>
                            <th className="px-2 py-1.5 text-right">MOQ</th>
                            <th className="px-2 py-1.5 text-left">Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {bulkRows.map((r, i) => (
                            <tr key={i} className={cn(bulkErrors[i] ? 'bg-amber-50 dark:bg-amber-900/10' : 'bg-green-50/50 dark:bg-green-900/5')}>
                              <td className="px-2 py-1">
                                <input type="checkbox" checked={bulkSelected.has(i)} onChange={() => {
                                  const s = new Set(bulkSelected);
                                  if (s.has(i)) s.delete(i); else if (!bulkErrors[i]) s.add(i);
                                  setBulkSelected(s);
                                }} disabled={!!bulkErrors[i]} />
                              </td>
                              <td className="px-2 py-1 font-medium">{r.product_name}</td>
                              <td className="px-2 py-1 font-mono">{r.hsn_code}</td>
                              <td className="px-2 py-1">{r.unit}</td>
                              <td className="px-2 py-1 text-right">₹{Number(r.price_per_unit_inr || 0).toLocaleString('en-IN')}</td>
                              <td className="px-2 py-1 text-right">{r.moq || '—'}</td>
                              <td className="px-2 py-1">{bulkErrors[i] ? <span className="text-amber-600">{bulkErrors[i]}</span> : <span className="text-green-600">✓</span>}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <Button
                      onClick={async () => {
                        const items = bulkRows.filter((_, i) => bulkSelected.has(i)).map(r => ({
                          product_name: r.product_name,
                          hsn_code: r.hsn_code || null,
                          product_category: r.product_category || r.product_name,
                          unit: r.unit || 'PIECE',
                          price_per_unit_inr: Number(r.price_per_unit_inr),
                          moq: Number(r.moq) || 1,
                          max_order_qty: Number(r.max_order_qty) || 10000,
                          lead_time_days: Number(r.lead_time_days) || 14,
                          in_stock_qty: Number(r.in_stock_qty) || 0,
                          grade: r.grade || null,
                          specification_text: r.specification_text || null,
                          certifications: r.certifications ? r.certifications.split(',').map((c: string) => c.trim()).filter(Boolean) : [],
                          floor_price_inr: r.floor_price_inr ? Number(r.floor_price_inr) : null,
                          max_discount_pct: r.max_discount_pct ? Number(r.max_discount_pct) : null,
                        }));
                        try {
                          await api.post('/v1/marketplace/catalogue/bulk', { items });
                          toast.success(`${items.length} products imported`);
                          queryClient.invalidateQueries({ queryKey: ['catalogue'] });
                          setShowBulkImport(false); setBulkStep('upload'); setBulkRows([]);
                        } catch (err: any) {
                          toast.error(err.response?.data?.detail || 'Bulk import failed');
                        }
                      }}
                      disabled={bulkSelected.size === 0}
                      className="w-full bg-primary text-primary-foreground"
                    >
                      Import {bulkSelected.size} item{bulkSelected.size !== 1 ? 's' : ''}
                    </Button>
                  </div>
                )}
              </div>
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
    specification_text: '',
    unit: 'MT',
    price_per_unit_inr: '',
    moq: '',
    max_order_qty: '',
    lead_time_days: '',
    in_stock_qty: '0',
    certifications: [] as string[],
    floor_price_inr: '',
    max_discount_pct: '10',
    negotiation_enabled: true,
    bulk_pricing_tiers: [] as { min_qty: string; price_per_unit_inr: string }[],
  });
  const [certInput, setCertInput] = React.useState('');
  const [customCategory, setCustomCategory] = React.useState('');

  const { data: editItemData } = useQuery({
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
        specification_text: d.specification_text || '',
        unit: d.unit || 'MT',
        price_per_unit_inr: String(d.price_per_unit_inr || ''),
        moq: String(d.moq || ''),
        max_order_qty: String(d.max_order_qty || ''),
        lead_time_days: String(d.lead_time_days || ''),
        in_stock_qty: String(d.in_stock_qty || '0'),
        certifications: d.certifications || [],
        floor_price_inr: d.floor_price_inr ? String(d.floor_price_inr) : '',
        max_discount_pct: d.max_discount_pct != null ? String(d.max_discount_pct) : '10',
        negotiation_enabled: d.negotiation_enabled ?? true,
        bulk_pricing_tiers: (d.bulk_pricing_tiers || []).map((t: any) => ({
          min_qty: String(t.min_qty || ''),
          price_per_unit_inr: String(t.price_per_unit_inr || ''),
        })),
      });
      // If category is not in suggestions, it's a custom value
      if (d.product_category && !CATEGORY_SUGGESTIONS.includes(d.product_category)) {
        setCustomCategory(d.product_category);
      }
    }
  }, [editItemData]);

  const saveMutation = useMutation({
    mutationFn: (body: Record<string, any>) => {
      if (editingId) return api.put(`/v1/marketplace/catalogue/${editingId}`, body);
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
    const category = form.product_category === '__CUSTOM__' ? customCategory : form.product_category;
    const body: Record<string, any> = {
      product_name: form.product_name,
      hsn_code: form.hsn_code,
      product_category: category,
      grade: form.grade || null,
      specification_text: form.specification_text || null,
      unit: form.unit,
      price_per_unit_inr: parseFloat(form.price_per_unit_inr),
      moq: parseFloat(form.moq),
      max_order_qty: parseFloat(form.max_order_qty),
      lead_time_days: parseInt(form.lead_time_days),
      in_stock_qty: parseFloat(form.in_stock_qty || '0'),
      certifications: form.certifications,
      negotiation_enabled: form.negotiation_enabled,
      max_discount_pct: form.max_discount_pct ? parseFloat(form.max_discount_pct) : null,
    };
    if (form.floor_price_inr) body.floor_price_inr = parseFloat(form.floor_price_inr);
    if (form.bulk_pricing_tiers.length > 0) {
      body.bulk_pricing_tiers = form.bulk_pricing_tiers
        .filter(t => t.min_qty && t.price_per_unit_inr)
        .map(t => ({
          min_qty: parseFloat(t.min_qty),
          max_qty: null,
          price_per_unit_inr: parseFloat(t.price_per_unit_inr),
        }));
    }
    saveMutation.mutate(body);
  };

  const update = (field: string, value: any) => setForm(f => ({ ...f, [field]: value }));

  const addCert = (cert: string) => {
    const trimmed = cert.trim();
    if (trimmed && !form.certifications.includes(trimmed)) {
      update('certifications', [...form.certifications, trimmed]);
    }
    setCertInput('');
  };

  const removeCert = (cert: string) => update('certifications', form.certifications.filter(c => c !== cert));

  const addBulkTier = () => update('bulk_pricing_tiers', [...form.bulk_pricing_tiers, { min_qty: '', price_per_unit_inr: '' }]);
  const removeBulkTier = (idx: number) => update('bulk_pricing_tiers', form.bulk_pricing_tiers.filter((_, i) => i !== idx));
  const updateBulkTier = (idx: number, field: string, value: string) => {
    const tiers = [...form.bulk_pricing_tiers];
    tiers[idx] = { ...tiers[idx], [field]: value };
    update('bulk_pricing_tiers', tiers);
  };

  return (
    <div className="border border-border rounded-lg p-5 bg-card">
      <h3 className="text-sm font-semibold text-foreground mb-4">{editingId ? 'Edit Product' : 'Add Product'}</h3>
      <form onSubmit={handleSubmit} className="space-y-5">

        {/* Section 1: Product Identity */}
        <div className="space-y-3">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Product Identity</p>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">Product Name *</label>
              <Input value={form.product_name} onChange={e => update('product_name', e.target.value)} required minLength={3} />
            </div>
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">HSN Code *</label>
              <Input value={form.hsn_code} onChange={e => update('hsn_code', e.target.value)} required pattern="\d{4,8}" placeholder="4-8 digits" />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">Category *</label>
              <Select value={CATEGORY_SUGGESTIONS.includes(form.product_category) ? form.product_category : '__CUSTOM__'} onValueChange={v => update('product_category', v)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent className="bg-popover border-border max-h-60">
                  {CATEGORY_SUGGESTIONS.map(c => <SelectItem key={c} value={c}>{formatCategory(c)}</SelectItem>)}
                  <SelectItem value="__CUSTOM__">Other (type below)</SelectItem>
                </SelectContent>
              </Select>
              {(form.product_category === '__CUSTOM__' || (!CATEGORY_SUGGESTIONS.includes(form.product_category) && form.product_category !== '__CUSTOM__')) && (
                <Input className="mt-2" placeholder="Enter custom category" value={customCategory} onChange={e => setCustomCategory(e.target.value)} required />
              )}
            </div>
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">Grade</label>
              <Input value={form.grade} onChange={e => update('grade', e.target.value)} placeholder="e.g. Fe500D" />
            </div>
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">Unit *</label>
              <Select value={form.unit} onValueChange={v => update('unit', v)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent className="bg-popover border-border max-h-60">
                  {UNITS.map(u => <SelectItem key={u} value={u}>{u}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">Specification / Description</label>
            <textarea
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring min-h-[80px] resize-y"
              value={form.specification_text}
              onChange={e => update('specification_text', e.target.value)}
              maxLength={2000}
              placeholder="Technical specs, dimensions, material composition (improves search matching)"
            />
            <p className="text-xs text-muted-foreground mt-1">{form.specification_text.length}/2000</p>
          </div>
        </div>

        {/* Section 2: Pricing & Availability */}
        <div className="space-y-3">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Pricing & Availability</p>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">Price per {form.unit} (INR) *</label>
              <Input type="number" step="0.01" value={form.price_per_unit_inr} onChange={e => update('price_per_unit_inr', e.target.value)} required />
            </div>
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">Floor Price (INR)</label>
              <Input type="number" step="0.01" value={form.floor_price_inr} onChange={e => update('floor_price_inr', e.target.value)} placeholder="Min acceptable price" />
              <p className="text-xs text-muted-foreground mt-0.5">AI agent won't go below this</p>
            </div>
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">Max Discount %</label>
              <Input type="number" step="0.5" min="0" max="50" value={form.max_discount_pct} onChange={e => update('max_discount_pct', e.target.value)} />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">MOQ ({form.unit}) *</label>
              <Input type="number" step="0.01" value={form.moq} onChange={e => update('moq', e.target.value)} required />
            </div>
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">Max Order ({form.unit}) *</label>
              <Input type="number" step="0.01" value={form.max_order_qty} onChange={e => update('max_order_qty', e.target.value)} required />
            </div>
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">In-Stock Qty</label>
              <Input type="number" step="0.01" value={form.in_stock_qty} onChange={e => update('in_stock_qty', e.target.value)} />
            </div>
          </div>

          <div className="flex items-center gap-3">
            <label className="text-xs font-medium text-muted-foreground">AI Negotiation</label>
            <button
              type="button"
              onClick={() => update('negotiation_enabled', !form.negotiation_enabled)}
              className={cn(
                'relative inline-flex h-5 w-9 items-center rounded-full transition-colors',
                form.negotiation_enabled ? 'bg-primary' : 'bg-muted-foreground/30'
              )}
            >
              <span className={cn('inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform', form.negotiation_enabled ? 'translate-x-4.5' : 'translate-x-0.5')} />
            </button>
            <span className="text-xs text-muted-foreground">{form.negotiation_enabled ? 'Enabled' : 'Fixed price (no negotiation)'}</span>
          </div>
        </div>

        {/* Section 3: Bulk Pricing Tiers */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Bulk Pricing Tiers</p>
            <Button type="button" variant="ghost" size="sm" onClick={addBulkTier} className="text-xs h-7">
              <Plus className="h-3 w-3 mr-1" /> Add Tier
            </Button>
          </div>
          {form.bulk_pricing_tiers.length === 0 ? (
            <p className="text-xs text-muted-foreground">No bulk tiers. Base price applies to all quantities.</p>
          ) : (
            <div className="space-y-2">
              {form.bulk_pricing_tiers.map((tier, idx) => (
                <div key={idx} className="flex items-center gap-3">
                  <div className="flex-1">
                    <Input type="number" step="0.01" placeholder={`Min qty (${form.unit})`} value={tier.min_qty} onChange={e => updateBulkTier(idx, 'min_qty', e.target.value)} />
                  </div>
                  <span className="text-xs text-muted-foreground">and above</span>
                  <div className="flex-1">
                    <Input type="number" step="0.01" placeholder="Price/unit (INR)" value={tier.price_per_unit_inr} onChange={e => updateBulkTier(idx, 'price_per_unit_inr', e.target.value)} />
                  </div>
                  <button type="button" onClick={() => removeBulkTier(idx)} className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Section 4: Logistics & Compliance */}
        <div className="space-y-3">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Logistics & Compliance</p>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">Lead Time (days) *</label>
              <Input type="number" value={form.lead_time_days} onChange={e => update('lead_time_days', e.target.value)} required min={1} max={180} />
            </div>
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">Certifications</label>
              <div className="flex gap-2">
                <Select value="" onValueChange={v => { if (v) addCert(v); }}>
                  <SelectTrigger className="flex-1"><SelectValue placeholder="Add certification" /></SelectTrigger>
                  <SelectContent className="bg-popover border-border">
                    {CERT_SUGGESTIONS.filter(c => !form.certifications.includes(c)).map(c => (
                      <SelectItem key={c} value={c}>{c}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Input
                  className="flex-1"
                  placeholder="Or type custom"
                  value={certInput}
                  onChange={e => setCertInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addCert(certInput); } }}
                />
              </div>
              {form.certifications.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {form.certifications.map(c => (
                    <span key={c} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-muted text-foreground">
                      {c}
                      <button type="button" onClick={() => removeCert(c)} className="hover:text-destructive">&times;</button>
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="flex gap-3 pt-2 border-t border-border">
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
