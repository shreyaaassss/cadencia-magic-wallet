'use client';

import * as React from 'react';
import { ChevronUp, ChevronDown, ChevronsUpDown, type LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { EmptyState } from '@/components/shared/EmptyState';

interface Column<T> {
  key: keyof T | string;
  label: string;
  sortable?: boolean;
  render?: (value: unknown, row: T) => React.ReactNode;
  width?: string;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  isLoading?: boolean;
  emptyState?: { icon: LucideIcon; title: string; description?: string };
  onRowClick?: (row: T) => void;
  keyExtractor: (row: T) => string;
}

type SortDir = 'asc' | 'desc' | null;

export function DataTable<T>({ columns, data, isLoading, emptyState, onRowClick, keyExtractor }: DataTableProps<T>) {
  const [sortKey, setSortKey] = React.useState<string | null>(null);
  const [sortDir, setSortDir] = React.useState<SortDir>(null);

  const handleSort = (key: string) => {
    if (sortKey === key) {
      if (sortDir === 'asc') setSortDir('desc');
      else if (sortDir === 'desc') { setSortKey(null); setSortDir(null); }
      else setSortDir('asc');
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  };

  const sortedData = React.useMemo(() => {
    if (!sortKey || !sortDir) return data;
    return [...data].sort((a, b) => {
      const aVal = (a as Record<string, unknown>)[sortKey];
      const bVal = (b as Record<string, unknown>)[sortKey];
      if (aVal == null || bVal == null) return 0;
      const cmp = String(aVal).localeCompare(String(bVal));
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [data, sortKey, sortDir]);

  const skeletonWidths = ['w-24', 'w-32', 'w-20', 'w-16', 'w-28'];

  return (
    <div className="bg-card border border-border rounded-lg overflow-hidden">
      <div className="w-full overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="bg-muted border-b border-border">
            {columns.map((col) => (
              <th
                key={String(col.key)}
                className={cn(
                  'text-xs font-medium text-muted-foreground uppercase tracking-wide px-2 sm:px-4 py-3 text-left',
                  col.sortable && 'cursor-pointer select-none hover:text-foreground'
                )}
                style={col.width ? { width: col.width } : undefined}
                onClick={col.sortable ? () => handleSort(String(col.key)) : undefined}
              >
                <span className="inline-flex items-center gap-1">
                  {col.label}
                  {col.sortable && (
                    sortKey === String(col.key) ? (
                      sortDir === 'asc' ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />
                    ) : (
                      <ChevronsUpDown className="h-3 w-3 text-muted-foreground" />
                    )
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {isLoading ? (
            Array.from({ length: 5 }).map((_, rowIdx) => (
              <tr key={rowIdx} className="border-b border-border last:border-0">
                {columns.map((col, colIdx) => (
                  <td key={String(col.key)} className="px-2 sm:px-4 py-3">
                    <div className={cn('bg-muted animate-pulse rounded h-4', skeletonWidths[colIdx % skeletonWidths.length])} />
                  </td>
                ))}
              </tr>
            ))
          ) : sortedData.length === 0 ? (
            <tr>
              <td colSpan={columns.length}>
                {emptyState ? (
                  <EmptyState icon={emptyState.icon} title={emptyState.title} description={emptyState.description} />
                ) : (
                  <div className="py-12 text-center text-sm text-muted-foreground">No data</div>
                )}
              </td>
            </tr>
          ) : (
            sortedData.map((row) => (
              <tr
                key={keyExtractor(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={cn(
                  'border-b border-border last:border-0 hover:bg-accent/50 transition-colors',
                  onRowClick && 'cursor-pointer'
                )}
              >
                {columns.map((col) => {
                  const val = (row as Record<string, unknown>)[String(col.key)];
                  return (
                    <td key={String(col.key)} className="px-2 sm:px-4 py-3 text-sm text-foreground">
                      {col.render ? col.render(val, row) : (val != null ? String(val) : '\u2014')}
                    </td>
                  );
                })}
              </tr>
            ))
          )}
        </tbody>
      </table>
      </div>
    </div>
  );
}
