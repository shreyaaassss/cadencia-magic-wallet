import * as React from 'react';
import { LucideIcon } from 'lucide-react';

interface PlatformMetricRowProps {
  label: string;
  value: string | number;
  icon: LucideIcon;
  unit?: string;
  trend?: 'up' | 'down' | 'neutral';
}

export function PlatformMetricRow({ label, value, icon: Icon, unit, trend }: PlatformMetricRowProps) {
  return (
    <div className="flex items-center gap-4 py-3 border-b border-border last:border-0 hover:bg-muted/30 transition-colors px-2 rounded-md">
      <div className="bg-muted rounded-md p-2 h-10 w-10 flex items-center justify-center text-primary shrink-0">
        <Icon className="h-5 w-5" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-muted-foreground truncate">{label}</p>
        <div className="flex items-baseline gap-1 mt-0.5">
          <span className="text-lg font-semibold text-foreground">{value}</span>
          {unit && <span className="text-xs text-muted-foreground">{unit}</span>}
        </div>
      </div>
      {trend && (
        <div className={`shrink-0 text-xs font-medium px-2 py-1 rounded ${
          trend === 'up' ? 'text-green-600 bg-green-50' :
          trend === 'down' ? 'text-destructive bg-destructive/10' :
          'text-muted-foreground bg-muted'
        }`}>
          {trend === 'up' ? '↑' : trend === 'down' ? '↓' : '—'}
        </div>
      )}
    </div>
  );
}
