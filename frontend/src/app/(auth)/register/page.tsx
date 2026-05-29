'use client';

import * as React from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import * as z from 'zod';
import { useForm, Controller, Resolver } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { AlertCircle, Loader2, X, Pencil, Check, Mail, Wallet } from 'lucide-react';
import { toast } from 'sonner';
import algosdk from 'algosdk';

import { useAuth } from '@/hooks/useAuth';
import { useWallet as _useTxnLabWallet } from '@txnlab/use-wallet-react';
import { resetWalletManager } from '@/components/providers/WalletConnectProvider';

function useTxnLabWalletSafe() {
  try {
    return _useTxnLabWallet();
  } catch {
    return { activeAddress: null, wallets: [], signTransactions: async () => [] as any, activeWallet: null } as any;
  }
}
import { api } from '@/lib/api';
import { formatCurrency, cn } from '@/lib/utils';
import { ROUTES as AppRoutes } from '@/lib/constants';

import { FormField } from '@/components/shared/FormField';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

const INDIAN_STATES = [
  "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
  "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
  "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram",
  "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
  "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
  "Delhi", "Jammu and Kashmir", "Ladakh", "Chandigarh", "Puducherry",
];

const PAYMENT_TERM_SUGGESTIONS = [
  "Advance", "LC at Sight", "LC 30", "LC 60", "NET 30", "NET 60", "NET 90",
];

const CERT_SUGGESTIONS = ["ISO 9001", "BIS", "RDSO", "ISO 14001", "NABL"];

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-md p-3 text-sm text-red-700 mb-4">
      <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
      <span>{message}</span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Schemas
// ─────────────────────────────────────────────────────────────────────────────

const step1Schema = z.object({
  legal_name: z.string().min(2, 'Legal name must be at least 2 characters'),
  pan: z.string().regex(/^[A-Z]{5}[0-9]{4}[A-Z]{1}$/i, 'Enter a valid PAN (e.g. ABCDE1234F)'),
  gstin: z.string().regex(
    /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/i,
    'Enter a valid 15-character GSTIN'
  ),
  trade_role: z.enum(['BUYER', 'SELLER', 'BOTH'], { error: 'Select a trade role' }),
  industry_vertical: z.string().min(2, 'Industry is required'),
  geography: z.string().min(2, 'Geography is required'),
  commodities: z.array(z.string()).default([]),
  min_order_value: z.number({ error: 'Enter a valid amount' }).optional(),
  max_order_value: z.number({ error: 'Enter a valid amount' }).optional(),
}).superRefine((d, ctx) => {
  const isSeller = d.trade_role === 'SELLER' || d.trade_role === 'BOTH';
  if (isSeller) {
    if (!d.commodities || d.commodities.length < 1) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: 'Add at least one commodity', path: ['commodities'] });
    }
    if (d.min_order_value === undefined || d.min_order_value < 1000) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: 'Minimum order must be at least ₹1,000', path: ['min_order_value'] });
    }
    if (d.max_order_value === undefined) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: 'Enter a valid amount', path: ['max_order_value'] });
    }
    if (d.min_order_value !== undefined && d.max_order_value !== undefined && d.max_order_value <= d.min_order_value) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: 'Max order value must be greater than min order value', path: ['max_order_value'] });
    }
  }
});

const addressSchema = z.object({
  address_line1: z.string().min(5, 'Address must be at least 5 characters'),
  address_line2: z.string().optional(),
  city: z.string().min(2, 'City is required'),
  state: z.string().min(2, 'State is required'),
  pincode: z.string().regex(/^\d{6}$/, 'Enter a valid 6-digit pincode'),
});

const sellerFacilitySchema = addressSchema.extend({
  facility_type: z.enum(['MANUFACTURING_PLANT', 'WAREHOUSE', 'TRADING_OFFICE', 'INTEGRATED']),
});

const sellerCapacitySchema = z.object({
  monthly_production_capacity_mt: z.number().positive('Capacity must be > 0'),
  shift_pattern: z.enum(['SINGLE_SHIFT', 'DOUBLE_SHIFT', 'TRIPLE_SHIFT', 'CONTINUOUS']).default('SINGLE_SHIFT'),
  avg_dispatch_days: z.number().min(1).max(90).default(3),
  max_delivery_radius_km: z.number().min(50).max(5000).optional(),
  has_own_transport: z.boolean().default(false),
  preferred_transport_modes: z.array(z.string()).default([]),
  payment_terms_accepted: z.array(z.string()).min(1, 'Select at least one payment term'),
  quality_certifications: z.array(z.string()).default([]),
  years_in_operation: z.number().min(0).optional(),
});

const buyerLocationSchema = addressSchema.extend({
  site_type: z.enum(['CONSTRUCTION_SITE', 'FACTORY', 'WAREHOUSE', 'RETAIL_STORE', 'PROJECT_SITE']).default('FACTORY'),
});

const step2Schema = z.object({
  full_name: z.string().min(2, 'Full name must be at least 2 characters'),
  email: z.string().email('Enter a valid email address'),
});

type Step1Values = z.infer<typeof step1Schema>;
type SellerFacilityValues = z.infer<typeof sellerFacilitySchema>;
type SellerCapacityValues = z.infer<typeof sellerCapacitySchema>;
type BuyerLocationValues = z.infer<typeof buyerLocationSchema>;
type Step2Values = z.infer<typeof step2Schema>;
// Password fields removed — Magic handles authentication, no password needed

interface RegistrationState {
  step: number;
  enterprise: Step1Values | null;
  sellerFacility: SellerFacilityValues | null;
  sellerCapacity: SellerCapacityValues | null;
  buyerLocation: BuyerLocationValues | null;
  user: Step2Values | null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Main page
// ─────────────────────────────────────────────────────────────────────────────

type RegisterAuthTab = 'magic' | 'web3';

export default function RegisterPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const auth = useAuth();
  const { user, isLoading } = auth;
  const txnLab = useTxnLabWalletSafe();

  const roleParam = searchParams.get('role')?.toUpperCase();
  const defaultTradeRole = roleParam === 'BUYER' ? 'BUYER' : roleParam === 'SELLER' ? 'SELLER' : undefined;

  const [authTab, setAuthTab] = React.useState<RegisterAuthTab>('magic');
  const [web3Address, setWeb3Address] = React.useState<string | null>(null);
  const [web3Status, setWeb3Status] = React.useState<'idle' | 'connecting'>('idle');

  // On mount: nuke any stale WC sessions
  React.useEffect(() => { resetWalletManager(); }, []);

  const [state, setState] = React.useState<RegistrationState>({
    step: 1,
    enterprise: null,
    sellerFacility: null,
    sellerCapacity: null,
    buyerLocation: null,
    user: null,
  });

  const [globalError, setGlobalError] = React.useState<string | null>(null);
  const [isSubmittingForm, setIsSubmittingForm] = React.useState(false);

  // Track wallet connection for web3 tab
  React.useEffect(() => {
    if (txnLab.activeAddress && web3Status === 'connecting') {
      setWeb3Address(txnLab.activeAddress);
      setWeb3Status('idle');
    }
  }, [txnLab.activeAddress, web3Status]);

  const isSeller = state.enterprise?.trade_role === 'SELLER' || state.enterprise?.trade_role === 'BOTH';
  const isBuyer = state.enterprise?.trade_role === 'BUYER';

  const totalSteps = isSeller ? 5 : isBuyer ? 4 : 3;

  React.useEffect(() => {
    if (!isLoading && user) {
      router.replace(AppRoutes.DASHBOARD);
    }
  }, [user, isLoading, router]);

  const goToStep = (step: number) => {
    setGlobalError(null);
    setState(s => ({ ...s, step }));
  };

  const handleStep1Submit = (data: Step1Values) => {
    setState(s => ({ ...s, enterprise: data, step: 2 }));
  };

  const handleSellerFacilitySubmit = (data: SellerFacilityValues) => {
    setState(s => ({ ...s, sellerFacility: data, step: 3 }));
  };

  const handleSellerCapacitySubmit = (data: SellerCapacityValues) => {
    setState(s => ({ ...s, sellerCapacity: data, step: 4 }));
  };

  const handleBuyerLocationSubmit = (data: BuyerLocationValues) => {
    setState(s => ({ ...s, buyerLocation: data, step: 3 }));
  };

  const handleAccountSubmit = (data: Step2Values) => {
    setState(s => ({ ...s, user: data, step: s.step + 1 }));
  };

  const submitRegistration = async () => {
    setGlobalError(null);
    setIsSubmittingForm(true);

    if (!state.enterprise || !state.user) {
      setIsSubmittingForm(false);
      return;
    }

    const addressData = isSeller && state.sellerFacility
      ? { address_type: 'FACILITY' as const, ...state.sellerFacility }
      : !isSeller && state.buyerLocation
      ? { address_type: 'DELIVERY' as const, ...state.buyerLocation }
      : null;

    const payload = {
      enterprise: {
        ...state.enterprise,
        pan: state.enterprise.pan.toUpperCase(),
        gstin: state.enterprise.gstin.toUpperCase(),
        address: addressData,
        facility_type: state.sellerFacility?.facility_type || null,
        payment_terms_accepted: state.sellerCapacity?.payment_terms_accepted || [],
        quality_certifications: state.sellerCapacity?.quality_certifications || [],
        years_in_operation: state.sellerCapacity?.years_in_operation || null,
      },
      user: {
        email: state.user.email,
        full_name: state.user.full_name,
        // No password — Magic is the authentication provider
      }
    };

    try {
      if (authTab === 'web3' && web3Address) {
        // Web3 registration: challenge → sign → register
        const { data: challengeRes } = await api.get('/v1/auth/web3-challenge');
        const challenge = challengeRes.data;

        const server = process.env.NEXT_PUBLIC_ALGOD_SERVER || 'https://testnet-api.4160.nodely.dev';
        const algod = new algosdk.Algodv2('', server, '');
        const sp = await algod.getTransactionParams().do();

        const txn = algosdk.makePaymentTxnWithSuggestedParamsFromObject({
          sender: web3Address,
          receiver: web3Address,
          amount: 0,
          note: new TextEncoder().encode(challenge.message_to_sign),
          suggestedParams: sp,
        });

        const encoded = [algosdk.encodeUnsignedTransaction(txn)];
        const signed = await txnLab.signTransactions(encoded);
        if (!signed[0]) throw new Error('Wallet did not return a signed transaction');
        const signedB64 = Buffer.from(signed[0] as Uint8Array).toString('base64');

        await auth.web3Register(payload, web3Address, challenge.challenge_id, signedB64);
      } else {
        await auth.register(payload);
      }
      toast.success('Account created successfully. Welcome to Cadencia.');
    } catch (err: any) {
      if (err.response?.status === 409) {
        setGlobalError('An account with this email or PAN already exists.');
      } else if (err.response?.status === 422) {
        setGlobalError('Validation failed on server. Please check your data.');
      } else {
        setGlobalError(err?.message || 'Registration failed. Please try again.');
      }
      setIsSubmittingForm(false);
    }
  };

  if (isLoading || user) {
    return null;
  }

  const stepLabels = isSeller
    ? ['Enterprise Info', 'Facility & Location', 'Production & Capacity', 'Account Details', 'Review & Submit']
    : isBuyer
    ? ['Enterprise Info', 'Delivery Location', 'Account Details', 'Review & Submit']
    : ['Enterprise Info', 'Account Details', 'Review & Submit'];

  // Determine which component to render per step
  const renderStep = () => {
    if (state.step === 1) {
      return (
        <Step1Form
          initialData={state.enterprise}
          onSubmit={handleStep1Submit}
          defaultTradeRole={defaultTradeRole as 'BUYER' | 'SELLER' | undefined}
        />
      );
    }

    if (isSeller) {
      if (state.step === 2) return <SellerFacilityForm initialData={state.sellerFacility} onSubmit={handleSellerFacilitySubmit} onBack={() => goToStep(1)} />;
      if (state.step === 3) return <SellerCapacityForm initialData={state.sellerCapacity} onSubmit={handleSellerCapacitySubmit} onBack={() => goToStep(2)} />;
      if (state.step === 4) return <Step2Form initialData={state.user} onSubmit={handleAccountSubmit} onBack={() => goToStep(3)} />;
      if (state.step === 5 && state.enterprise && state.user) {
        return <ReviewStep enterprise={state.enterprise} user={state.user} sellerFacility={state.sellerFacility} sellerCapacity={state.sellerCapacity} buyerLocation={null} onEdit={goToStep} onSubmit={submitRegistration} isSubmitting={isSubmittingForm} isSeller={true} />;
      }
    } else if (isBuyer) {
      if (state.step === 2) return <BuyerLocationForm initialData={state.buyerLocation} onSubmit={handleBuyerLocationSubmit} onBack={() => goToStep(1)} />;
      if (state.step === 3) return <Step2Form initialData={state.user} onSubmit={handleAccountSubmit} onBack={() => goToStep(2)} />;
      if (state.step === 4 && state.enterprise && state.user) {
        return <ReviewStep enterprise={state.enterprise} user={state.user} sellerFacility={null} sellerCapacity={null} buyerLocation={state.buyerLocation} onEdit={goToStep} onSubmit={submitRegistration} isSubmitting={isSubmittingForm} isSeller={false} />;
      }
    } else {
      // BOTH not yet selected — default flow
      if (state.step === 2) return <Step2Form initialData={state.user} onSubmit={handleAccountSubmit} onBack={() => goToStep(1)} />;
      if (state.step === 3 && state.enterprise && state.user) {
        return <ReviewStep enterprise={state.enterprise} user={state.user} sellerFacility={null} sellerCapacity={null} buyerLocation={null} onEdit={goToStep} onSubmit={submitRegistration} isSubmitting={isSubmittingForm} isSeller={false} />;
      }
    }
    return null;
  };

  return (
    <div className="min-h-screen bg-surface-soft flex flex-col items-center justify-center py-8 px-4">
      {/* Back to landing */}
      <div className="w-full max-w-lg mb-4">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          Back to Cadencia
        </Link>
      </div>

      <div className="bg-card border border-hairline rounded-lg w-full max-w-lg shadow-sm flex flex-col">
        <div className="p-5 sm:p-8">
          {/* Auth Method Toggle */}
          <div className="flex rounded-lg border border-hairline overflow-hidden mb-6">
            <button
              type="button"
              onClick={() => { setAuthTab('magic'); setGlobalError(null); }}
              className={cn(
                'flex-1 flex items-center justify-center gap-2 py-2.5 text-sm font-medium transition-colors',
                authTab === 'magic'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-card text-muted-foreground hover:text-ink'
              )}
            >
              <Mail className="h-3.5 w-3.5" />
              Email & Wallet
            </button>
            <button
              type="button"
              onClick={() => { setAuthTab('web3'); setGlobalError(null); }}
              className={cn(
                'flex-1 flex items-center justify-center gap-2 py-2.5 text-sm font-medium transition-colors',
                authTab === 'web3'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-card text-muted-foreground hover:text-ink'
              )}
            >
              <Wallet className="h-3.5 w-3.5" />
              Connect Wallet
            </button>
          </div>

          {/* Web3: Wallet connection step (before the form) */}
          {authTab === 'web3' && !web3Address && (
            <div className="space-y-4">
              <h2 className="text-base font-medium text-ink">Connect your wallet</h2>
              <p className="text-xs text-muted-foreground mb-4">
                Connect your Algorand wallet first, then fill in your enterprise details.
              </p>
              {txnLab.wallets?.map((wallet: any) => (
                <button
                  key={wallet.id}
                  onClick={async () => {
                    setWeb3Status('connecting');
                    setGlobalError(null);
                    try {
                      await wallet.connect();
                    } catch (err: any) {
                      setGlobalError(err?.message || 'Failed to connect wallet');
                      setWeb3Status('idle');
                    }
                  }}
                  className="w-full flex items-center gap-3 p-3 rounded-md border border-hairline bg-card hover:bg-surface-soft transition-colors text-left"
                >
                  {wallet.metadata?.icon && (
                    <img src={wallet.metadata.icon} alt="" className="h-6 w-6 rounded" />
                  )}
                  <span className="text-sm font-medium text-ink">{wallet.metadata?.name || wallet.id}</span>
                </button>
              ))}
              {globalError && <ErrorBanner message={globalError} />}
            </div>
          )}

          {/* Web3: Show connected wallet badge */}
          {authTab === 'web3' && web3Address && (
            <div className="mb-4 bg-surface-soft border border-hairline rounded-md p-3 flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Connected Wallet</p>
                <p className="text-sm font-mono text-ink truncate max-w-[280px]">{web3Address}</p>
              </div>
              <button
                onClick={() => { setWeb3Address(null); txnLab.activeWallet?.disconnect(); }}
                className="text-xs text-muted-foreground hover:text-destructive"
              >
                Disconnect
              </button>
            </div>
          )}

          {/* Show form steps: always for magic, only after wallet connected for web3 */}
          {(authTab === 'magic' || web3Address) && (
            <>
              <StepIndicator currentStep={state.step} steps={stepLabels} />
              {globalError && <ErrorBanner message={globalError} />}
              {renderStep()}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Step Indicator
// ─────────────────────────────────────────────────────────────────────────────

function StepIndicator({ currentStep, steps }: { currentStep: number; steps: string[] }) {
  return (
    <div className="flex items-center justify-between mb-8 relative">
      {steps.slice(0, -1).map((_, i) => (
        <div
          key={i}
          className={cn(
            'absolute top-[15px] h-[2px] z-0',
            `left-[${Math.round((i / (steps.length - 1)) * 100)}%]`,
            currentStep > i + 1 ? 'bg-primary' : 'bg-border'
          )}
          style={{
            left: `${((i + 0.5) / steps.length) * 100}%`,
            width: `${(1 / steps.length) * 100}%`,
          }}
        />
      ))}
      {steps.map((label, i) => {
        const num = i + 1;
        const isCompleted = currentStep > num;
        const isCurrent = currentStep === num;

        return (
          <div key={num} className="relative z-10 flex flex-col items-center gap-2">
            <div
              className={cn(
                'flex items-center justify-center w-8 h-8 rounded-full text-sm font-medium transition-colors',
                isCompleted && 'bg-primary text-primary-foreground',
                isCurrent && 'bg-primary text-primary-foreground ring-2 ring-primary ring-offset-2 ring-offset-background',
                !isCompleted && !isCurrent && 'bg-muted text-muted-foreground border border-border'
              )}
            >
              {isCompleted ? <Check className="h-4 w-4" /> : num}
            </div>
            <span className={cn('text-[10px] whitespace-nowrap max-w-[70px] text-center leading-tight', isCurrent ? 'text-primary font-medium' : 'text-muted-foreground')}>
              {label}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tag Input Component (reused for commodities, payment terms, certifications)
// ─────────────────────────────────────────────────────────────────────────────

function TagInput({
  value,
  onChange,
  placeholder = 'Type and press Enter...',
  suggestions,
  error,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  suggestions?: string[];
  error?: boolean;
}) {
  const [input, setInput] = React.useState('');
  const [showSuggestions, setShowSuggestions] = React.useState(false);

  const addTag = (val: string) => {
    const trimmed = val.trim().replace(/,$/, '');
    if (trimmed && !value.includes(trimmed)) {
      onChange([...value, trimmed]);
    }
    setInput('');
    setShowSuggestions(false);
  };

  const filtered = suggestions?.filter(s => !value.includes(s) && s.toLowerCase().includes(input.toLowerCase()));

  return (
    <div className="relative">
      <div className={cn("flex flex-wrap items-center gap-2 p-2 border border-border bg-input rounded-md min-h-10", error && "border-destructive ring-1 ring-destructive")}>
        {value.map(c => (
          <span key={c} className="flex items-center gap-1 bg-secondary text-secondary-foreground rounded-md pl-2 pr-1 py-0.5 text-xs">
            {c}
            <button type="button" onClick={() => onChange(value.filter(v => v !== c))} className="hover:text-destructive transition-colors shrink-0 p-0.5">
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        <input
          type="text"
          className="flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground min-w-[120px]"
          placeholder={placeholder}
          value={input}
          onChange={e => { setInput(e.target.value); setShowSuggestions(true); }}
          onKeyDown={e => { if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); addTag(input); } }}
          onBlur={() => { if (input.trim()) addTag(input); setTimeout(() => setShowSuggestions(false), 150); }}
          onFocus={() => setShowSuggestions(true)}
        />
      </div>
      {showSuggestions && filtered && filtered.length > 0 && (
        <div className="absolute z-20 mt-1 w-full bg-popover border border-border rounded-md shadow-md max-h-32 overflow-auto">
          {filtered.map(s => (
            <button key={s} type="button" onMouseDown={() => addTag(s)} className="block w-full text-left px-3 py-1.5 text-sm hover:bg-accent text-foreground">
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 1: Enterprise Info (unchanged logic)
// ─────────────────────────────────────────────────────────────────────────────

function Step1Form({ initialData, onSubmit, defaultTradeRole }: { initialData: Step1Values | null; onSubmit: (data: Step1Values) => void; defaultTradeRole?: 'BUYER' | 'SELLER' }) {
  const { register, control, handleSubmit, formState: { errors, touchedFields }, setValue, watch } = useForm<Step1Values>({
    resolver: zodResolver(step1Schema) as Resolver<Step1Values>,
    defaultValues: initialData || { commodities: [], trade_role: defaultTradeRole },
    mode: 'onTouched',
  });

  const commodities = watch('commodities') || [];
  const tradeRole = watch('trade_role');
  const showSellerFields = tradeRole === 'SELLER' || tradeRole === 'BOTH';

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-5 animate-in fade-in slide-in-from-bottom-2">
      <FormField label="Legal Name" required error={touchedFields.legal_name ? errors.legal_name?.message : undefined}>
        <Input {...register('legal_name')} />
      </FormField>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <FormField label="PAN" required error={touchedFields.pan ? errors.pan?.message : undefined}>
          <Input {...register('pan')} className="uppercase" />
        </FormField>
        <FormField label="GSTIN" required error={touchedFields.gstin ? errors.gstin?.message : undefined}>
          <Input {...register('gstin')} className="uppercase" />
        </FormField>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <FormField label="Trade Role" required error={errors.trade_role?.message}>
          <Controller
            control={control}
            name="trade_role"
            render={({ field }) => (
              <Select onValueChange={field.onChange} defaultValue={field.value}>
                <SelectTrigger><SelectValue placeholder="Select role" /></SelectTrigger>
                <SelectContent position="popper" className="bg-popover border-border">
                  <SelectItem value="BUYER">Buyer</SelectItem>
                  <SelectItem value="SELLER">Seller</SelectItem>
                  <SelectItem value="BOTH">Buyer & Seller</SelectItem>
                </SelectContent>
              </Select>
            )}
          />
        </FormField>
        <FormField label="Industry Vertical" required error={touchedFields.industry_vertical ? errors.industry_vertical?.message : undefined}>
          <Input {...register('industry_vertical')} />
        </FormField>
      </div>

      <FormField label="Geography" hint="Primary state or region" required error={touchedFields.geography ? errors.geography?.message : undefined}>
        <Input {...register('geography')} />
      </FormField>

      {showSellerFields && (
        <>
          <FormField label="Commodities" required error={errors.commodities?.message}>
            <TagInput value={commodities} onChange={v => setValue('commodities', v, { shouldValidate: true, shouldDirty: true })} />
          </FormField>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <FormField label="Min Order Value" required error={errors.min_order_value?.message}>
              <div className="relative">
                <span className="absolute left-3 top-2.5 text-sm font-medium text-muted-foreground">INR</span>
                <Input type="number" className="pl-12" {...register('min_order_value', { valueAsNumber: true })} />
              </div>
            </FormField>
            <FormField label="Max Order Value" required error={errors.max_order_value?.message}>
              <div className="relative">
                <span className="absolute left-3 top-2.5 text-sm font-medium text-muted-foreground">INR</span>
                <Input type="number" className="pl-12" {...register('max_order_value', { valueAsNumber: true })} />
              </div>
            </FormField>
          </div>
        </>
      )}

      <div className="pt-2">
        <Button type="submit" className="w-full bg-primary text-primary-foreground hover:bg-primary/90">Next</Button>
      </div>
    </form>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 2a: Seller Facility & Location
// ─────────────────────────────────────────────────────────────────────────────

function SellerFacilityForm({ initialData, onSubmit, onBack }: { initialData: SellerFacilityValues | null; onSubmit: (data: SellerFacilityValues) => void; onBack: () => void }) {
  const { register, control, handleSubmit, formState: { errors, touchedFields } } = useForm<SellerFacilityValues>({
    resolver: zodResolver(sellerFacilitySchema),
    defaultValues: initialData || {},
    mode: 'onTouched',
  });

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-5 animate-in fade-in slide-in-from-bottom-2">
      <h3 className="text-sm font-semibold text-foreground">Facility & Location</h3>
      <p className="text-xs text-muted-foreground -mt-3">Enter your primary facility address for precise delivery matching.</p>

      <FormField label="Address Line 1" required error={touchedFields.address_line1 ? errors.address_line1?.message : undefined}>
        <Input {...register('address_line1')} placeholder="Street, building, area" />
      </FormField>
      <FormField label="Address Line 2" error={errors.address_line2?.message}>
        <Input {...register('address_line2')} placeholder="Landmark, floor (optional)" />
      </FormField>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <FormField label="City" required error={touchedFields.city ? errors.city?.message : undefined}>
          <Input {...register('city')} />
        </FormField>
        <FormField label="State" required error={errors.state?.message}>
          <Controller
            control={control}
            name="state"
            render={({ field }) => (
              <Select onValueChange={field.onChange} defaultValue={field.value}>
                <SelectTrigger><SelectValue placeholder="Select state" /></SelectTrigger>
                <SelectContent position="popper" className="bg-popover border-border max-h-60">
                  {INDIAN_STATES.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                </SelectContent>
              </Select>
            )}
          />
        </FormField>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <FormField label="Pincode" hint="6-digit" required error={touchedFields.pincode ? errors.pincode?.message : undefined}>
          <Input {...register('pincode')} maxLength={6} />
        </FormField>
        <FormField label="Facility Type" required error={errors.facility_type?.message}>
          <Controller
            control={control}
            name="facility_type"
            render={({ field }) => (
              <Select onValueChange={field.onChange} defaultValue={field.value}>
                <SelectTrigger><SelectValue placeholder="Select type" /></SelectTrigger>
                <SelectContent position="popper" className="bg-popover border-border">
                  <SelectItem value="MANUFACTURING_PLANT">Manufacturing Plant</SelectItem>
                  <SelectItem value="WAREHOUSE">Warehouse</SelectItem>
                  <SelectItem value="TRADING_OFFICE">Trading Office</SelectItem>
                  <SelectItem value="INTEGRATED">Integrated</SelectItem>
                </SelectContent>
              </Select>
            )}
          />
        </FormField>
      </div>

      <div className="flex gap-3 pt-2">
        <Button type="button" variant="ghost" onClick={onBack} className="w-1/3 hover:bg-accent text-foreground">Back</Button>
        <Button type="submit" className="flex-1 bg-primary text-primary-foreground hover:bg-primary/90">Next</Button>
      </div>
    </form>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 2b: Seller Production & Capacity
// ─────────────────────────────────────────────────────────────────────────────

function SellerCapacityForm({ initialData, onSubmit, onBack }: { initialData: SellerCapacityValues | null; onSubmit: (data: SellerCapacityValues) => void; onBack: () => void }) {
  const { register, control, handleSubmit, watch, setValue, formState: { errors } } = useForm<SellerCapacityValues>({
    resolver: zodResolver(sellerCapacitySchema) as Resolver<SellerCapacityValues>,
    defaultValues: initialData || { shift_pattern: 'SINGLE_SHIFT', avg_dispatch_days: 3, has_own_transport: false, preferred_transport_modes: [], payment_terms_accepted: [], quality_certifications: [] },
    mode: 'onTouched',
  });

  const paymentTerms = watch('payment_terms_accepted') || [];
  const certs = watch('quality_certifications') || [];
  const transportModes = watch('preferred_transport_modes') || [];

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-5 animate-in fade-in slide-in-from-bottom-2">
      <h3 className="text-sm font-semibold text-foreground">Production & Capacity</h3>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <FormField label="Monthly Capacity" hint="MT/month" required error={errors.monthly_production_capacity_mt?.message}>
          <Input type="number" step="0.01" {...register('monthly_production_capacity_mt', { valueAsNumber: true })} />
        </FormField>
        <FormField label="Shift Pattern" error={errors.shift_pattern?.message}>
          <Controller
            control={control}
            name="shift_pattern"
            render={({ field }) => (
              <Select onValueChange={field.onChange} defaultValue={field.value}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent position="popper" className="bg-popover border-border">
                  <SelectItem value="SINGLE_SHIFT">Single Shift</SelectItem>
                  <SelectItem value="DOUBLE_SHIFT">Double Shift</SelectItem>
                  <SelectItem value="TRIPLE_SHIFT">Triple Shift</SelectItem>
                  <SelectItem value="CONTINUOUS">Continuous</SelectItem>
                </SelectContent>
              </Select>
            )}
          />
        </FormField>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <FormField label="Avg Dispatch Days" error={errors.avg_dispatch_days?.message}>
          <Input type="number" {...register('avg_dispatch_days', { valueAsNumber: true })} />
        </FormField>
        <FormField label="Max Delivery Radius" hint="km (optional)" error={errors.max_delivery_radius_km?.message}>
          <Input type="number" {...register('max_delivery_radius_km', { valueAsNumber: true })} />
        </FormField>
      </div>

      <FormField label="Transport Modes">
        <div className="flex flex-wrap gap-3">
          {['ROAD', 'RAIL', 'SEA', 'AIR'].map(mode => (
            <label key={mode} className="flex items-center gap-1.5 text-sm text-foreground cursor-pointer">
              <input
                type="checkbox"
                className="rounded border-border"
                checked={transportModes.includes(mode)}
                onChange={e => {
                  const updated = e.target.checked ? [...transportModes, mode] : transportModes.filter(m => m !== mode);
                  setValue('preferred_transport_modes', updated);
                }}
              />
              {mode.charAt(0) + mode.slice(1).toLowerCase()}
            </label>
          ))}
        </div>
      </FormField>

      <label className="flex items-center gap-2 text-sm text-foreground cursor-pointer">
        <input type="checkbox" className="rounded border-border" {...register('has_own_transport')} />
        Has own transport fleet
      </label>

      <FormField label="Payment Terms Accepted" required error={errors.payment_terms_accepted?.message}>
        <TagInput value={paymentTerms} onChange={v => setValue('payment_terms_accepted', v, { shouldValidate: true })} suggestions={PAYMENT_TERM_SUGGESTIONS} placeholder="Add payment terms..." />
      </FormField>

      <FormField label="Quality Certifications">
        <TagInput value={certs} onChange={v => setValue('quality_certifications', v)} suggestions={CERT_SUGGESTIONS} placeholder="Add certifications..." />
      </FormField>

      <FormField label="Years in Operation" error={errors.years_in_operation?.message}>
        <Input type="number" {...register('years_in_operation', { valueAsNumber: true })} />
      </FormField>

      <div className="flex gap-3 pt-2">
        <Button type="button" variant="ghost" onClick={onBack} className="w-1/3 hover:bg-accent text-foreground">Back</Button>
        <Button type="submit" className="flex-1 bg-primary text-primary-foreground hover:bg-primary/90">Next</Button>
      </div>
    </form>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 2c: Buyer Delivery Location
// ─────────────────────────────────────────────────────────────────────────────

function BuyerLocationForm({ initialData, onSubmit, onBack }: { initialData: BuyerLocationValues | null; onSubmit: (data: BuyerLocationValues) => void; onBack: () => void }) {
  const { register, control, handleSubmit, formState: { errors, touchedFields } } = useForm<BuyerLocationValues>({
    resolver: zodResolver(buyerLocationSchema) as Resolver<BuyerLocationValues>,
    defaultValues: initialData || { site_type: 'FACTORY' },
    mode: 'onTouched',
  });

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-5 animate-in fade-in slide-in-from-bottom-2">
      <h3 className="text-sm font-semibold text-foreground">Delivery Location</h3>
      <p className="text-xs text-muted-foreground -mt-3">Enter your primary delivery address. This helps us match you with nearby sellers.</p>

      <FormField label="Address Line 1" required error={touchedFields.address_line1 ? errors.address_line1?.message : undefined}>
        <Input {...register('address_line1')} placeholder="Street, building, area" />
      </FormField>
      <FormField label="Address Line 2" error={errors.address_line2?.message}>
        <Input {...register('address_line2')} placeholder="Landmark, floor (optional)" />
      </FormField>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <FormField label="City" required error={touchedFields.city ? errors.city?.message : undefined}>
          <Input {...register('city')} />
        </FormField>
        <FormField label="State" required error={errors.state?.message}>
          <Controller
            control={control}
            name="state"
            render={({ field }) => (
              <Select onValueChange={field.onChange} defaultValue={field.value}>
                <SelectTrigger><SelectValue placeholder="Select state" /></SelectTrigger>
                <SelectContent position="popper" className="bg-popover border-border max-h-60">
                  {INDIAN_STATES.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                </SelectContent>
              </Select>
            )}
          />
        </FormField>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <FormField label="Pincode" hint="6-digit" required error={touchedFields.pincode ? errors.pincode?.message : undefined}>
          <Input {...register('pincode')} maxLength={6} />
        </FormField>
        <FormField label="Site Type" error={errors.site_type?.message}>
          <Controller
            control={control}
            name="site_type"
            render={({ field }) => (
              <Select onValueChange={field.onChange} defaultValue={field.value}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent position="popper" className="bg-popover border-border">
                  <SelectItem value="CONSTRUCTION_SITE">Construction Site</SelectItem>
                  <SelectItem value="FACTORY">Factory</SelectItem>
                  <SelectItem value="WAREHOUSE">Warehouse</SelectItem>
                  <SelectItem value="RETAIL_STORE">Retail Store</SelectItem>
                  <SelectItem value="PROJECT_SITE">Project Site</SelectItem>
                </SelectContent>
              </Select>
            )}
          />
        </FormField>
      </div>

      <div className="flex gap-3 pt-2">
        <Button type="button" variant="ghost" onClick={onBack} className="w-1/3 hover:bg-accent text-foreground">Back</Button>
        <Button type="submit" className="flex-1 bg-primary text-primary-foreground hover:bg-primary/90">Next</Button>
      </div>
    </form>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Account Details (Step 2 / varies by role) — Magic edition, no password
// ─────────────────────────────────────────────────────────────────────────────

function Step2Form({ initialData, onSubmit, onBack }: { initialData: Step2Values | null; onSubmit: (data: Step2Values) => void; onBack: () => void }) {
  const { register, handleSubmit, formState: { errors, touchedFields } } = useForm<Step2Values>({
    resolver: zodResolver(step2Schema),
    defaultValues: initialData || {},
    mode: 'onTouched',
  });

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-5 animate-in fade-in slide-in-from-bottom-2">
      <FormField label="Full Name" required error={touchedFields.full_name ? errors.full_name?.message : undefined}>
        <Input {...register('full_name')} />
      </FormField>
      <FormField label="Email address" required error={touchedFields.email ? errors.email?.message : undefined}>
        <Input type="email" {...register('email')} />
      </FormField>
      <p className="text-xs text-muted-foreground">
        No password needed. We&apos;ll send a one-time code to your email to verify your identity.
      </p>
      <div className="flex gap-3 pt-2">
        <Button type="button" variant="ghost" onClick={onBack} className="w-1/3 hover:bg-accent text-foreground">Back</Button>
        <Button type="submit" className="flex-1 bg-primary text-primary-foreground hover:bg-primary/90">Next</Button>
      </div>
    </form>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Review & Submit
// ─────────────────────────────────────────────────────────────────────────────

function ReviewStep({
  enterprise, user, sellerFacility, sellerCapacity, buyerLocation, onEdit, onSubmit, isSubmitting, isSeller,
}: {
  enterprise: Step1Values; user: Step2Values; sellerFacility: SellerFacilityValues | null; sellerCapacity: SellerCapacityValues | null; buyerLocation: BuyerLocationValues | null; onEdit: (step: number) => void; onSubmit: () => void; isSubmitting: boolean; isSeller: boolean;
}) {
  return (
    <div className="space-y-4 animate-in fade-in slide-in-from-bottom-2">
      {/* Enterprise Card */}
      <div className="bg-card border border-border rounded-lg p-4 relative">
        <button onClick={() => onEdit(1)} className="absolute top-3 right-3 p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"><Pencil className="h-3.5 w-3.5" /></button>
        <h3 className="text-sm font-semibold text-foreground mb-3">Enterprise Details</h3>
        <div className="grid grid-cols-2 gap-y-3 gap-x-2 text-sm">
          <div><p className="text-xs uppercase tracking-wide text-muted-foreground">Legal Name</p><p className="text-foreground">{enterprise.legal_name}</p></div>
          <div><p className="text-xs uppercase tracking-wide text-muted-foreground">Trade Role</p><p className="text-foreground">{enterprise.trade_role}</p></div>
          <div><p className="text-xs uppercase tracking-wide text-muted-foreground">PAN</p><p className="text-foreground uppercase">{enterprise.pan}</p></div>
          <div><p className="text-xs uppercase tracking-wide text-muted-foreground">GSTIN</p><p className="text-foreground uppercase">{enterprise.gstin}</p></div>
          <div><p className="text-xs uppercase tracking-wide text-muted-foreground">Industry</p><p className="text-foreground">{enterprise.industry_vertical}</p></div>
          <div><p className="text-xs uppercase tracking-wide text-muted-foreground">Geography</p><p className="text-foreground">{enterprise.geography}</p></div>
          {(enterprise.trade_role === 'SELLER' || enterprise.trade_role === 'BOTH') && enterprise.min_order_value && enterprise.max_order_value && (
            <div className="col-span-2 flex gap-4">
              <div><p className="text-xs uppercase tracking-wide text-muted-foreground mb-0.5">Min Order</p><p className="text-foreground">{formatCurrency(enterprise.min_order_value)}</p></div>
              <div><p className="text-xs uppercase tracking-wide text-muted-foreground mb-0.5">Max Order</p><p className="text-foreground">{formatCurrency(enterprise.max_order_value)}</p></div>
            </div>
          )}
          {(enterprise.trade_role === 'SELLER' || enterprise.trade_role === 'BOTH') && enterprise.commodities.length > 0 && (
            <div className="col-span-2">
              <p className="text-xs uppercase tracking-wide text-muted-foreground mb-1">Commodities</p>
              <div className="flex flex-wrap gap-1.5">{enterprise.commodities.map(c => <span key={c} className="bg-secondary text-secondary-foreground text-xs px-2 py-0.5 rounded-md">{c}</span>)}</div>
            </div>
          )}
        </div>
      </div>

      {/* Location Card */}
      {(sellerFacility || buyerLocation) && (
        <div className="bg-card border border-border rounded-lg p-4 relative">
          <button onClick={() => onEdit(2)} className="absolute top-3 right-3 p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"><Pencil className="h-3.5 w-3.5" /></button>
          <h3 className="text-sm font-semibold text-foreground mb-3">{isSeller ? 'Facility & Location' : 'Delivery Location'}</h3>
          {(() => {
            const addr = sellerFacility || buyerLocation;
            if (!addr) return null;
            return (
              <div className="grid grid-cols-2 gap-y-3 gap-x-2 text-sm">
                <div className="col-span-2"><p className="text-xs uppercase tracking-wide text-muted-foreground">Address</p><p className="text-foreground">{addr.address_line1}{addr.address_line2 ? `, ${addr.address_line2}` : ''}</p></div>
                <div><p className="text-xs uppercase tracking-wide text-muted-foreground">City</p><p className="text-foreground">{addr.city}</p></div>
                <div><p className="text-xs uppercase tracking-wide text-muted-foreground">State</p><p className="text-foreground">{addr.state}</p></div>
                <div><p className="text-xs uppercase tracking-wide text-muted-foreground">Pincode</p><p className="text-foreground">{addr.pincode}</p></div>
                <div><p className="text-xs uppercase tracking-wide text-muted-foreground">{isSeller ? 'Facility Type' : 'Site Type'}</p><p className="text-foreground">{(sellerFacility as any)?.facility_type?.replace(/_/g, ' ') || (buyerLocation as any)?.site_type?.replace(/_/g, ' ') || ''}</p></div>
              </div>
            );
          })()}
        </div>
      )}

      {/* Capacity Card (seller only) */}
      {sellerCapacity && (
        <div className="bg-card border border-border rounded-lg p-4 relative">
          <button onClick={() => onEdit(3)} className="absolute top-3 right-3 p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"><Pencil className="h-3.5 w-3.5" /></button>
          <h3 className="text-sm font-semibold text-foreground mb-3">Production & Capacity</h3>
          <div className="grid grid-cols-2 gap-y-3 gap-x-2 text-sm">
            <div><p className="text-xs uppercase tracking-wide text-muted-foreground">Monthly Capacity</p><p className="text-foreground">{sellerCapacity.monthly_production_capacity_mt} MT</p></div>
            <div><p className="text-xs uppercase tracking-wide text-muted-foreground">Shift Pattern</p><p className="text-foreground">{sellerCapacity.shift_pattern.replace(/_/g, ' ')}</p></div>
            <div><p className="text-xs uppercase tracking-wide text-muted-foreground">Dispatch Days</p><p className="text-foreground">{sellerCapacity.avg_dispatch_days} days</p></div>
            {sellerCapacity.max_delivery_radius_km && <div><p className="text-xs uppercase tracking-wide text-muted-foreground">Delivery Radius</p><p className="text-foreground">{sellerCapacity.max_delivery_radius_km} km</p></div>}
            {sellerCapacity.years_in_operation !== undefined && <div><p className="text-xs uppercase tracking-wide text-muted-foreground">Years in Operation</p><p className="text-foreground">{sellerCapacity.years_in_operation}</p></div>}
            <div className="col-span-2">
              <p className="text-xs uppercase tracking-wide text-muted-foreground mb-1">Payment Terms</p>
              <div className="flex flex-wrap gap-1.5">{sellerCapacity.payment_terms_accepted.map(t => <span key={t} className="bg-secondary text-secondary-foreground text-xs px-2 py-0.5 rounded-md">{t}</span>)}</div>
            </div>
            {sellerCapacity.quality_certifications.length > 0 && (
              <div className="col-span-2">
                <p className="text-xs uppercase tracking-wide text-muted-foreground mb-1">Certifications</p>
                <div className="flex flex-wrap gap-1.5">{sellerCapacity.quality_certifications.map(c => <span key={c} className="bg-secondary text-secondary-foreground text-xs px-2 py-0.5 rounded-md">{c}</span>)}</div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* User Card */}
      <div className="bg-card border border-border rounded-lg p-4 relative">
        <button onClick={() => onEdit(isSeller ? 4 : buyerLocation ? 3 : 2)} className="absolute top-3 right-3 p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"><Pencil className="h-3.5 w-3.5" /></button>
        <h3 className="text-sm font-semibold text-foreground mb-3">Account Details</h3>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between items-start">
            <div><p className="text-xs uppercase tracking-wide text-muted-foreground">Full Name</p><p className="text-foreground">{user.full_name}</p></div>
            <StatusBadge status={enterprise.trade_role} size="sm" />
          </div>
          <div><p className="text-xs uppercase tracking-wide text-muted-foreground">Email</p><p className="text-foreground">{user.email}</p></div>
          <div><p className="text-xs uppercase tracking-wide text-muted-foreground">Authentication</p><p className="text-foreground text-xs text-muted-foreground">Magic one-time code (no password)</p></div>
        </div>
      </div>

      <div className="pt-2">
        <Button onClick={onSubmit} disabled={isSubmitting} className="w-full bg-primary text-primary-foreground hover:bg-primary/90">
          {isSubmitting ? (<><Loader2 className="mr-2 h-4 w-4 animate-spin" />Creating account...</>) : 'Create Account'}
        </Button>
        <p className="text-xs text-muted-foreground text-center mt-3">By creating an account you agree to Cadencia&apos;s terms of service.</p>
      </div>
    </div>
  );
}
