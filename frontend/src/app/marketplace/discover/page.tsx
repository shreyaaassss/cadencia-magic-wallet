'use client';

import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Search, Building2, MapPin, Award, TrendingUp, Users, ShieldCheck } from 'lucide-react';

import { AppShell } from '@/components/layout/AppShell';
import { SectionHeader } from '@/components/shared/SectionHeader';
import { StatCard } from '@/components/shared/StatCard';
import { api } from '@/lib/api';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface PlatformStats {
  total_sellers: number;
  total_buyers: number;
  negotiations_completed: number;
  escrows_released: number;
  total_value_settled_inr: number;
  industries_represented: string[];
}

interface Supplier {
  supplier_id: string;
  industry: string | null;
  categories: string[];
  geographies: string[];
  certifications: string[];
  years_in_operation_bucket: string;
  min_order_value_inr: number | null;
}

export default function DiscoverPage() {
  const [industryFilter, setIndustryFilter] = React.useState<string>('');
  const [searchQuery, setSearchQuery] = React.useState('');

  const { data: stats } = useQuery<PlatformStats>({
    queryKey: ['marketplace-stats'],
    queryFn: () => api.get('/v1/marketplace/stats').then(r => r.data.data),
  });

  const { data: suppliers = [], isLoading } = useQuery<Supplier[]>({
    queryKey: ['suppliers', industryFilter],
    queryFn: () => {
      const params = new URLSearchParams();
      if (industryFilter) params.set('industry', industryFilter);
      return api.get(`/v1/marketplace/suppliers?${params}`).then(r => r.data.data || []);
    },
  });

  const filteredSuppliers = searchQuery
    ? suppliers.filter(s =>
        s.categories.some(c => c.toLowerCase().includes(searchQuery.toLowerCase())) ||
        (s.industry || '').toLowerCase().includes(searchQuery.toLowerCase())
      )
    : suppliers;

  return (
    <AppShell>
      <div className="space-y-8">
        <SectionHeader
          title="Discover Suppliers"
          description="Browse verified suppliers across industries. Submit an RFQ to get matched."
        />

        {/* Platform Stats Banner */}
        {stats && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <StatCard icon={Building2} label="Sellers" value={stats.total_sellers} />
            <StatCard icon={Users} label="Buyers" value={stats.total_buyers} />
            <StatCard icon={TrendingUp} label="Deals Completed" value={stats.negotiations_completed} />
            <StatCard icon={ShieldCheck} label="Escrows Released" value={stats.escrows_released} />
          </div>
        )}

        {/* Industry Chips */}
        {stats?.industries_represented && stats.industries_represented.length > 0 && (
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setIndustryFilter('')}
              className={cn('px-3 py-1.5 rounded-full text-xs font-medium transition-colors',
                !industryFilter ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:bg-accent')}
            >
              All Industries
            </button>
            {stats.industries_represented.map(ind => (
              <button
                key={ind}
                onClick={() => setIndustryFilter(ind)}
                className={cn('px-3 py-1.5 rounded-full text-xs font-medium transition-colors',
                  industryFilter === ind ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:bg-accent')}
              >
                {ind}
              </button>
            ))}
          </div>
        )}

        {/* Search */}
        <div className="max-w-md">
          <div className="relative">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              className="pl-9"
              placeholder="Search by product or industry..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
            />
          </div>
        </div>

        {/* Supplier Cards */}
        {isLoading ? (
          <p className="text-sm text-muted-foreground py-8 text-center">Loading suppliers...</p>
        ) : filteredSuppliers.length === 0 ? (
          <div className="text-center py-16 border border-dashed border-border rounded-lg">
            <Building2 className="h-10 w-10 mx-auto text-muted-foreground mb-3" />
            <p className="text-sm text-muted-foreground">No suppliers found. Adjust your filters or check back later.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredSuppliers.map(supplier => (
              <div key={supplier.supplier_id} className="border border-border rounded-lg p-4 bg-card hover:shadow-sm transition-shadow">
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <p className="text-sm font-semibold text-foreground">{supplier.industry || 'General'}</p>
                    <p className="text-xs text-muted-foreground">ID: {supplier.supplier_id}</p>
                  </div>
                  <span className="text-xs bg-muted px-2 py-0.5 rounded-full text-muted-foreground">
                    {supplier.years_in_operation_bucket} yrs
                  </span>
                </div>

                {supplier.categories.length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-3">
                    {supplier.categories.slice(0, 4).map(cat => (
                      <span key={cat} className="text-xs bg-primary/10 text-primary px-2 py-0.5 rounded-full">{cat}</span>
                    ))}
                    {supplier.categories.length > 4 && (
                      <span className="text-xs text-muted-foreground">+{supplier.categories.length - 4} more</span>
                    )}
                  </div>
                )}

                <div className="space-y-1.5 text-xs text-muted-foreground">
                  {supplier.geographies.length > 0 && (
                    <div className="flex items-center gap-1">
                      <MapPin className="h-3 w-3" />
                      {supplier.geographies.slice(0, 3).join(', ')}
                    </div>
                  )}
                  {supplier.certifications.length > 0 && (
                    <div className="flex items-center gap-1">
                      <Award className="h-3 w-3" />
                      {supplier.certifications.join(', ')}
                    </div>
                  )}
                  {supplier.min_order_value_inr && (
                    <p>Min order: {new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(supplier.min_order_value_inr)}</p>
                  )}
                </div>

                <Button variant="outline" size="sm" className="w-full mt-3 text-xs">
                  Submit RFQ to Match
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}
