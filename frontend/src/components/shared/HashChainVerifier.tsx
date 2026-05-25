import * as React from 'react';
import { CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';

interface VerificationResult {
  is_valid: boolean;
  chain_length: number;
}

interface HashChainVerifierProps {
  onVerify: () => void;
  isVerifying: boolean;
  verification: VerificationResult | null;
}

export function HashChainVerifier({ onVerify, isVerifying, verification }: HashChainVerifierProps) {
  if (isVerifying) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium bg-muted/30 text-muted-foreground border border-border">
        <Loader2 className="h-3 w-3 animate-spin" />
        Verifying cryptographic chain...
      </div>
    );
  }

  if (verification) {
    if (verification.is_valid) {
      return (
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium bg-green-50 text-green-600 border border-green-200">
          <CheckCircle2 className="h-3 w-3" />
          Chain Valid ({verification.chain_length} entries)
        </div>
      );
    } else {
      return (
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium bg-red-50 text-destructive border border-red-200">
          <AlertCircle className="h-3 w-3" />
          Chain Invalid
        </div>
      );
    }
  }

  return (
    <button 
      onClick={onVerify}
      className="flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium hover:bg-accent text-primary border border-primary/20 transition-colors"
    >
      <CheckCircle2 className="h-3 w-3" />
      Verify Chain
    </button>
  );
}
