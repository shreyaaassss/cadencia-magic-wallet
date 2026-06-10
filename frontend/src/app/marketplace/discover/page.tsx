'use client';

import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Building2, Users, Factory, Package, MapPin, Award } from 'lucide-react';

import { AppShell } from '@/components/layout/AppShell';
import { SectionHeader } from '@/components/shared/SectionHeader';
import { StatCard } from '@/components/shared/StatCard';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';

interface PlatformStats {
  total_sellers: number;
  total_buyers: number;
  industries_represented: string[];
}

interface Supplier {
  supplier_id: string;
  industry: string | null;
  categories: string[];
  geographies: string[];
  certifications: string[];
  years_in_operation_bucket: string;
}

export default function DiscoverPage() {
  const { data: stats } = useQuery<PlatformStats>({
    queryKey: ['marketplace-stats'],
    queryFn: () => api.get('/v1/marketplace/stats').then(r => r.data.data),
  });

  const { data: suppliers = [] } = useQuery<Supplier[]>({
    queryKey: ['suppliers'],
    queryFn: () => api.get('/v1/marketplace/suppliers?page_size=50').then(r => r.data.data || []),
  });

  const { data: industries = [] } = useQuery<any[]>({
    queryKey: ['industries'],
    queryFn: () => api.get('/v1/marketplace/industries').then(r => r.data.data || []),
  });

  // Aggregate: sellers per industry + products per industry
  const industryAggregates = React.useMemo(() => {
    const agg: Record<string, { count: number; products: Set<string>; geos: Set<string>; certs: Set<string> }> = {};
    for (const s of suppliers) {
      const ind = s.industry || 'Others';
      if (!agg[ind]) agg[ind] = { count: 0, products: new Set(), geos: new Set(), certs: new Set() };
      agg[ind].count++;
      s.categories.forEach(c => agg[ind].products.add(c));
      s.geographies.forEach(g => agg[ind].geos.add(g));
      s.certifications.forEach(c => agg[ind].certs.add(c));
    }
    return Object.entries(agg)
      .map(([industry, data]) => ({
        industry,
        sellerCount: data.count,
        products: Array.from(data.products).slice(0, 8),
        geos: Array.from(data.geos).slice(0, 5),
        certs: Array.from(data.certs).slice(0, 5),
      }))
      .sort((a, b) => b.sellerCount - a.sellerCount);
  }, [suppliers]);

  return (
    <AppShell>
      <div className="space-y-8">
        <SectionHeader
          title="Platform Discovery"
          description="Explore the supplier ecosystem on Cadencia. See what industries, products, and sellers are available."
        />

        {/* Platform Overview */}
        {stats && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <StatCard icon={Building2} label="Verified Sellers" value={stats.total_sellers} />
            <StatCard icon={Factory} label="Industries" value={stats.industries_represented?.length || 0} />
          </div>
        )}

        {/* Industry Breakdown */}
        <div className="space-y-4">
          <h2 className="text-sm font-semibold text-foreground uppercase tracking-wide">Industries on Platform</h2>

          {industryAggregates.length === 0 ? (
            <div className="text-center py-12 border border-dashed border-border rounded-lg">
              <Factory className="h-10 w-10 mx-auto text-muted-foreground mb-3" />
              <p className="text-sm text-muted-foreground">No sellers registered yet. Check back soon.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {industryAggregates.map(ind => (
                <div key={ind.industry} className="border border-border rounded-lg p-5 bg-card hover:shadow-sm transition-shadow">
                  <div className="flex items-start justify-between mb-3">
                    <div>
                      <h3 className="text-sm font-semibold text-foreground">{ind.industry}</h3>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {ind.sellerCount} seller{ind.sellerCount !== 1 ? 's' : ''} available
                      </p>
                    </div>
                    <span className="text-lg font-bold text-primary">{ind.sellerCount}</span>
                  </div>

                  {/* Products available */}
                  {ind.products.length > 0 && (
                    <div className="mb-3">
                      <p className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1">
                        <Package className="h-3 w-3" /> Products Available
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {ind.products.map(p => (
                          <span key={p} className="text-xs bg-primary/10 text-primary px-2 py-0.5 rounded-full">
                            {p.replace(/_/g, ' ')}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Geography coverage */}
                  {ind.geos.length > 0 && (
                    <div className="mb-2">
                      <p className="text-xs text-muted-foreground flex items-center gap-1">
                        <MapPin className="h-3 w-3" />
                        {ind.geos.join(', ')}
                      </p>
                    </div>
                  )}

                  {/* Certifications */}
                  {ind.certs.length > 0 && (
                    <p className="text-xs text-muted-foreground flex items-center gap-1">
                      <Award className="h-3 w-3" />
                      {ind.certs.join(', ')}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Available Industries from Taxonomy */}
        {industries.length > 0 && (
          <div className="space-y-3">
            <h2 className="text-sm font-semibold text-foreground uppercase tracking-wide">
              All Supported Industries
            </h2>
            <div className="flex flex-wrap gap-2">
              {industries.map((ind: any) => (
                <div key={ind.industry_code} className="border border-border rounded-md px-3 py-2 bg-card text-xs">
                  <span className="font-medium text-foreground">{ind.display_name}</span>
                  {ind.is_manufacturing && (
                    <span className="ml-1.5 text-muted-foreground">(Manufacturing)</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
