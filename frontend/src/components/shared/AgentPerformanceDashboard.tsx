'use client';

import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Brain, TrendingUp, Target, Clock } from 'lucide-react';

import { api } from '@/lib/api';
import { cn } from '@/lib/utils';

interface NegotiationInsights {
  total_negotiations: number;
  success_rate: number;
  avg_rounds_to_close: number;
  avg_discount_achieved_pct: number;
  dominant_style: string | null;
  style_distribution: Record<string, number> | null;
  top_products: any[] | null;
}

/**
 * Agent performance dashboard showing negotiation insights.
 * Data sourced from GET /v1/insights/enterprise endpoint.
 */
export function AgentPerformanceDashboard({ enterpriseId }: { enterpriseId: string }) {
  const { data: insights } = useQuery<NegotiationInsights>({
    queryKey: ['agent-insights', enterpriseId],
    queryFn: () => api.get(`/v1/insights/${enterpriseId}`).then(r => r.data?.data),
    enabled: !!enterpriseId,
  });

  if (!insights || insights.total_negotiations === 0) {
    return (
      <div className="border border-dashed border-border rounded-lg p-6 text-center">
        <Brain className="h-8 w-8 mx-auto text-muted-foreground mb-2" />
        <p className="text-sm text-muted-foreground">Your AI agent hasn't completed any negotiations yet.</p>
        <p className="text-xs text-muted-foreground mt-1">Performance metrics will appear here after your first deal.</p>
      </div>
    );
  }

  const successPct = Math.round(insights.success_rate * 100);

  return (
    <div className="border border-border rounded-lg bg-card p-4 space-y-4">
      <div className="flex items-center gap-2">
        <Brain className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-semibold text-foreground">AI Agent Performance</h3>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-muted/50 rounded-md p-3">
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
            <Target className="h-3 w-3" /> Win Rate
          </div>
          <p className={cn('text-lg font-bold', successPct >= 60 ? 'text-green-600' : successPct >= 40 ? 'text-amber-600' : 'text-red-600')}>
            {successPct}%
          </p>
        </div>

        <div className="bg-muted/50 rounded-md p-3">
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
            <TrendingUp className="h-3 w-3" /> Total Deals
          </div>
          <p className="text-lg font-bold text-foreground">{insights.total_negotiations}</p>
        </div>

        <div className="bg-muted/50 rounded-md p-3">
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
            <Clock className="h-3 w-3" /> Avg Rounds
          </div>
          <p className="text-lg font-bold text-foreground">{insights.avg_rounds_to_close.toFixed(1)}</p>
        </div>

        <div className="bg-muted/50 rounded-md p-3">
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
            <TrendingUp className="h-3 w-3" /> Avg Savings
          </div>
          <p className="text-lg font-bold text-foreground">{insights.avg_discount_achieved_pct.toFixed(1)}%</p>
        </div>
      </div>

      {insights.dominant_style && (
        <p className="text-xs text-muted-foreground">
          Dominant negotiation style: <span className="font-medium text-foreground">{insights.dominant_style}</span>
        </p>
      )}

      {insights.style_distribution && Object.keys(insights.style_distribution).length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-muted-foreground">Strategy Distribution</p>
          {Object.entries(insights.style_distribution).map(([style, count]) => (
            <div key={style} className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground w-24 truncate">{style}</span>
              <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary rounded-full"
                  style={{ width: `${Math.min((count / insights.total_negotiations) * 100, 100)}%` }}
                />
              </div>
              <span className="text-xs text-muted-foreground w-8 text-right">{count}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
