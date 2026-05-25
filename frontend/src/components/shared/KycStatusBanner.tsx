'use client';

import * as React from 'react';
import { Loader2, ShieldCheck, ShieldAlert, ShieldX, Shield } from 'lucide-react';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { FileUploadButton } from '@/components/shared/FileUploadButton';
import { Button } from '@/components/ui/button';
import { formatDateTime } from '@/lib/utils';

interface KycStatusBannerProps {
  status: 'NOT_SUBMITTED' | 'PENDING' | 'ACTIVE' | 'REJECTED';
  onUpload: (files: File[]) => Promise<void>;
  isUploading: boolean;
}

export function KycStatusBanner({ status, onUpload, isUploading }: KycStatusBannerProps) {
  const [selectedFiles, setSelectedFiles] = React.useState<File[]>([]);
  const now = formatDateTime(new Date().toISOString());

  const handleSubmit = async () => {
    if (selectedFiles.length === 0) return;
    await onUpload(selectedFiles);
    setSelectedFiles([]);
  };

  if (status === 'ACTIVE') {
    return (
      <div className="flex items-start gap-4 p-4 bg-card border border-border rounded-lg">
        <div className="bg-green-50 rounded-md p-2 shrink-0">
          <ShieldCheck className="h-5 w-5 text-green-700" />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-sm font-medium text-foreground">KYC Status</span>
            <StatusBadge status="ACTIVE" />
          </div>
          <p className="text-sm text-muted-foreground">Verified on {now}</p>
          <p className="text-xs text-muted-foreground mt-1">Documents up to date</p>
        </div>
      </div>
    );
  }

  if (status === 'PENDING') {
    return (
      <div className="flex items-start gap-4 p-4 bg-card border border-border rounded-lg">
        <div className="bg-amber-50 rounded-md p-2 shrink-0">
          <ShieldAlert className="h-5 w-5 text-amber-600" />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-sm font-medium text-foreground">KYC Status</span>
            <StatusBadge status="PENDING" />
          </div>
          <p className="text-sm text-muted-foreground">Documents received on {now}</p>
          <p className="text-xs text-muted-foreground mt-1">Status: Processing...</p>
        </div>
      </div>
    );
  }

  const isRejected = status === 'REJECTED';
  const IconComp = isRejected ? ShieldX : Shield;
  const iconBg = isRejected ? 'bg-red-50' : 'bg-muted';
  const iconColor = isRejected ? 'text-destructive' : 'text-muted-foreground';

  return (
    <div className="flex items-start gap-4 p-4 bg-card border border-border rounded-lg">
      <div className={`${iconBg} rounded-md p-2 shrink-0`}>
        <IconComp className={`h-5 w-5 ${iconColor}`} />
      </div>
      <div className="flex-1">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-sm font-medium text-foreground">KYC Status</span>
          <StatusBadge status={status} />
        </div>
        <p className="text-sm text-muted-foreground mb-3">
          {isRejected ? 'Resubmit your documents' : 'Upload your KYC documents to activate your account'}
        </p>

        {selectedFiles.length > 0 && (
          <div className="mb-3 space-y-1">
            {selectedFiles.map((f, i) => (
              <p key={i} className="text-xs text-muted-foreground">
                {f.name} ({(f.size / 1024).toFixed(0)} KB)
              </p>
            ))}
          </div>
        )}

        <div className="flex items-center gap-2">
          <FileUploadButton
            onFilesSelected={(files) => setSelectedFiles(prev => [...prev, ...files])}
          />
          <Button
            onClick={handleSubmit}
            disabled={isUploading || selectedFiles.length === 0}
            className="bg-primary text-primary-foreground hover:bg-primary/90"
          >
            {isUploading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {isRejected ? 'Resubmit KYC' : 'Submit KYC'}
          </Button>
        </div>
      </div>
    </div>
  );
}
