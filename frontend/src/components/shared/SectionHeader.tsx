import { type LucideIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface SectionHeaderProps {
  title: string;
  description?: string;
  action?: {
    label: string;
    icon?: LucideIcon;
    onClick: () => void;
  };
}

export function SectionHeader({ title, description, action }: SectionHeaderProps) {
  return (
    <div className="flex items-center justify-between border-b border-border pb-3 mb-4">
      <div>
        <h3 className="text-base font-semibold text-foreground">{title}</h3>
        {description && <p className="text-sm text-muted-foreground mt-0.5">{description}</p>}
      </div>
      {action && (
        <Button
          variant="ghost"
          size="sm"
          onClick={action.onClick}
          className="text-primary hover:bg-secondary"
        >
          {action.icon && (() => { const AIcon = action.icon; return <AIcon className="h-3.5 w-3.5 mr-1.5" />; })()}
          {action.label}
        </Button>
      )}
    </div>
  );
}
