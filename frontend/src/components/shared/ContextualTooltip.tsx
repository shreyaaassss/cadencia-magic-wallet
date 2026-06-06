'use client';

import * as React from 'react';
import { HelpCircle } from 'lucide-react';
import { cn } from '@/lib/utils';

interface ContextualTooltipProps {
  text: string;
  className?: string;
}

/**
 * Contextual help tooltip — renders a ? icon that shows explanatory text on hover.
 * Used next to technical terms like "ALGO Balance", "Merkle Root", "FEMA Record".
 */
export function ContextualTooltip({ text, className }: ContextualTooltipProps) {
  const [isOpen, setIsOpen] = React.useState(false);

  return (
    <span className={cn('relative inline-flex items-center', className)}>
      <button
        type="button"
        onMouseEnter={() => setIsOpen(true)}
        onMouseLeave={() => setIsOpen(false)}
        onClick={() => setIsOpen(!isOpen)}
        className="p-0.5 rounded-full hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
        aria-label="Help"
      >
        <HelpCircle className="h-3.5 w-3.5" />
      </button>
      {isOpen && (
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-50 w-64 max-w-xs">
          <div className="bg-popover border border-border rounded-md shadow-md px-3 py-2 text-xs text-popover-foreground">
            {text}
          </div>
          <div className="absolute top-full left-1/2 -translate-x-1/2 w-2 h-2 bg-popover border-r border-b border-border rotate-45 -mt-1" />
        </div>
      )}
    </span>
  );
}
