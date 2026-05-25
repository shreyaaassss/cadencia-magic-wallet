import * as React from 'react';
import { Check, Play, Unlock, AlertCircle, Rocket } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { TxExplorerLink } from './TxExplorerLink';
import { cn } from '@/lib/utils';
import type { EscrowStatus } from '@/types';

interface EscrowStepperProps {
  status: EscrowStatus;
  appId?: number | null;
  isSeller?: boolean;
  onAction: (action: 'deploy' | 'fund' | 'release' | 'refund' | 'freeze') => void;
}

export function EscrowStepper({ status, appId, isSeller, onAction }: EscrowStepperProps) {
  const steps = [
    { key: 'APPROVED', label: 'Approved' },
    { key: 'DEPLOYED', label: 'Deployed' },
    { key: 'FUNDED', label: 'Funded' },
    { key: 'RELEASED', label: 'Released' },
  ];

  const getStepIndex = () => {
    switch (status) {
      case 'APPROVED':  return 0;
      case 'DEPLOYED':  return 1;
      case 'FUNDED':    return 2;
      case 'RELEASED':  return 3;
      case 'REFUNDED':  return 4; // Beyond normal path
      case 'FROZEN':    return -1;
      default:          return -1;
    }
  };

  const currentIndex = getStepIndex();
  const isError = status === 'REFUNDED' || status === 'FROZEN';

  return (
    <div className="flex flex-col items-center">
      <div className="flex items-center w-full max-w-3xl justify-between relative mb-6">
        {/* Progress line */}
        <div className="absolute left-0 right-0 top-1/2 -translate-y-1/2 h-0.5 bg-muted z-0">
          <div
            className="h-full bg-primary transition-all duration-500"
            style={{ width: currentIndex > 0 ? `${(Math.min(currentIndex, 3) / 3) * 100}%` : '0%' }}
          />
        </div>

        {/* Step Nodes */}
        {steps.map((step, idx) => {
          const isCompleted = currentIndex > idx && !isError;
          const isCurrent = currentIndex === idx && !isError;

          return (
            <div key={step.key} className="flex flex-col items-center relative z-10 w-24">
              <div
                className={cn(
                  'h-8 w-8 rounded-full flex items-center justify-center text-sm font-bold bg-background transition-colors',
                  isCompleted ? 'bg-primary text-primary-foreground border-2 border-primary' :
                  isCurrent   ? 'border-2 border-primary text-primary ring-4 ring-primary/20' :
                                'bg-muted text-muted-foreground border-2 border-border'
                )}
              >
                {isCompleted ? <Check className="h-4 w-4" /> : idx + 1}
              </div>
              <span
                className={cn(
                  'mt-3 text-xs font-medium',
                  isCompleted || isCurrent ? 'text-foreground' : 'text-muted-foreground'
                )}
              >
                {step.label}
              </span>
            </div>
          );
        })}
      </div>

      {isError && (
        <div className="mb-6 flex items-center gap-2 text-destructive bg-red-50 px-4 py-2 rounded-md border border-red-200">
          <AlertCircle className="h-4 w-4" />
          <span className="text-sm font-medium">Escrow State: {status}</span>
        </div>
      )}

      {/* Contract Details */}
      <div className="text-sm text-muted-foreground flex items-center gap-2 mb-6 bg-accent px-4 py-2 rounded-full">
        <span>
          Current Status: <strong className={cn(isError ? 'text-destructive' : 'text-foreground')}>{status}</strong>
        </span>
        {appId && appId > 0 && (
          <>
            <span>&bull;</span>
            <span>Contract:</span>
            <TxExplorerLink txId={appId} type="app" />
          </>
        )}
      </div>

      {/* Action Buttons */}
      <div className="flex gap-3 justify-center min-h-[40px]">
        {status === 'APPROVED' && (
          <Button onClick={() => onAction('deploy')} className="bg-primary text-primary-foreground hover:opacity-90 transition-all duration-200 hover:-translate-y-[1px] hover:shadow-[0_4px_16px_hsl(var(--primary)/0.3)]">
            <Rocket className="h-4 w-4 mr-2" />
            Deploy Smart Contract
          </Button>
        )}
        {status === 'DEPLOYED' && (
          <Button onClick={() => onAction('fund')} className="bg-primary text-primary-foreground hover:opacity-90 transition-all duration-200 hover:-translate-y-[1px] hover:shadow-[0_4px_16px_hsl(var(--primary)/0.3)]">
            <Play className="h-4 w-4 mr-2" />
            Fund Escrow
          </Button>
        )}
        {status === 'FUNDED' && (
          <Button onClick={() => onAction('release')} className="bg-primary text-primary-foreground hover:opacity-90 transition-all duration-200 hover:-translate-y-[1px] hover:shadow-[0_4px_16px_hsl(var(--primary)/0.3)]">
            <Unlock className="h-4 w-4 mr-2" />
            {isSeller ? 'Order Complete' : 'Release to Seller'}
          </Button>
        )}
      </div>
    </div>
  );
}
