import { type LucideIcon, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { cn } from '@/lib/utils';

interface StatCardProps {
  label: string;
  value: string | number;
  icon: LucideIcon;
  trend?: {
    value: string;
    direction: 'up' | 'down' | 'neutral';
  };
  isLoading?: boolean;
  onClick?: () => void;
}

const trendConfig = {
  up:      { Icon: TrendingUp,   className: 'text-green-600' },
  down:    { Icon: TrendingDown,  className: 'text-destructive' },
  neutral: { Icon: Minus,         className: 'text-muted-foreground' },
};

export function StatCard({ label, value, icon: Icon, trend, isLoading, onClick }: StatCardProps) {
  return (
    <div
      onClick={onClick}
      className={cn(
        'bg-card border border-border rounded-lg p-5 transition-colors',
        onClick && 'cursor-pointer hover:bg-accent'
      )}
    >
      <div className="flex items-start justify-between">
        <div className="bg-muted rounded-md p-2">
          <Icon className="h-4 w-4 text-primary" />
        </div>
        {isLoading ? (
          <div className="bg-muted animate-pulse rounded h-8 w-16" />
        ) : (
          <span className="text-2xl font-semibold text-foreground">{value}</span>
        )}
      </div>
      <p className="text-sm text-muted-foreground mt-3">{label}</p>
      {isLoading ? (
        <div className="bg-muted animate-pulse rounded h-3 w-20 mt-1.5" />
      ) : (
        trend && (
          <div className={cn('flex items-center gap-1 mt-1', trendConfig[trend.direction].className)}>
            {(() => { const TIcon = trendConfig[trend.direction].Icon; return <TIcon className="h-3 w-3" />; })()}
            <span className="text-xs">{trend.value}</span>
          </div>
        )
      )}
    </div>
  );
}
