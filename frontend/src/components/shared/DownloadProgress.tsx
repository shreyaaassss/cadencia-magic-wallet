import * as React from 'react';
import { Download, Loader2, AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface DownloadProgressProps {
  status: 'idle' | 'queued' | 'processing' | 'ready' | 'failed';
  progress?: number;
  downloadUrl?: string;
  onRetry?: () => void;
  onExport: () => void;
}

export function DownloadProgress({ status, progress, downloadUrl, onRetry, onExport }: DownloadProgressProps) {
  if (status === 'idle') {
    return (
      <Button onClick={onExport} className="bg-primary text-primary-foreground min-w-[140px]">
        Export All (Admin)
      </Button>
    );
  }

  if (status === 'failed') {
    return (
      <div className="flex items-center gap-3">
        <span className="text-sm text-destructive flex items-center gap-1">
          <AlertCircle className="h-4 w-4" /> Failed
        </span>
        <Button variant="outline" size="sm" onClick={onRetry}>Retry</Button>
      </div>
    );
  }

  if (status === 'ready' && downloadUrl) {
    return (
      <div className="flex items-center gap-3">
        <span className="text-sm text-green-600 flex items-center gap-1">
          <Download className="h-4 w-4" /> Ready
        </span>
        <Button onClick={() => window.open(downloadUrl, '_blank')} className="bg-primary text-primary-foreground hover:opacity-90 transition-all duration-200 hover:-translate-y-[1px] hover:shadow-[0_4px_16px_hsl(var(--primary)/0.3)] min-w-[140px]">
          Download Latest
        </Button>
      </div>
    );
  }

  // queued or processing
  const displayProgress = progress ?? 0;
  
  return (
    <div className="flex items-center gap-4 min-w-[250px]">
      <div className="flex-1">
        <div className="flex justify-between text-xs mb-1 font-medium">
          <span className="text-muted-foreground capitalize">{status}...</span>
          <span className="text-primary">{displayProgress}%</span>
        </div>
        <div className="w-full bg-muted/50 rounded-full h-2 overflow-hidden">
          <div 
            className="bg-primary h-full transition-all duration-300"
            style={{ width: `${displayProgress}%` }}
          />
        </div>
      </div>
      <Loader2 className="h-4 w-4 text-primary animate-spin shrink-0" />
    </div>
  );
}
