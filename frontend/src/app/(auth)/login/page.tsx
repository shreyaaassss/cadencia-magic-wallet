'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import algosdk from 'algosdk';
import { Building2, AlertCircle, Loader2, ShieldCheck, Wallet, Mail } from 'lucide-react';

import { useAuth } from '@/hooks/useAuth';
import { useWallet as _useWallet } from '@txnlab/use-wallet-react';

function useWalletSafe() {
  try {
    return _useWallet();
  } catch {
    return { activeAddress: null, wallets: [], signTransactions: async () => [] as any, activeWallet: null } as any;
  }
}
import { ROUTES } from '@/lib/constants';
import { api } from '@/lib/api';
import { FormField } from '@/components/shared/FormField';
import { PasswordInput } from '@/components/shared/PasswordInput';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const loginSchema = z.object({
  email: z.string().email('Enter a valid email address'),
});

type LoginFormValues = z.infer<typeof loginSchema>;

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900 rounded-md p-3 text-sm text-red-700 dark:text-red-400 mb-4">
      <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
      <span>{message}</span>
    </div>
  );
}

type AuthTab = 'magic' | 'web3';

export default function LoginPage() {
  const router = useRouter();
  const { user, isLoading, login, adminLogin, web3Login } = useAuth();
  const txnLab = useWalletSafe();

  const [activeTab, setActiveTab] = React.useState<AuthTab>('magic');
  const [globalError, setGlobalError] = React.useState<string | null>(null);
  const [showAdminForm, setShowAdminForm] = React.useState(false);
  const [adminError, setAdminError] = React.useState<string | null>(null);
  const [adminSubmitting, setAdminSubmitting] = React.useState(false);
  const [web3Status, setWeb3Status] = React.useState<'idle' | 'connecting' | 'signing' | 'verifying'>('idle');

  const {
    register,
    handleSubmit,
    formState: { errors, touchedFields, isSubmitting },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    mode: 'onTouched',
  });

  React.useEffect(() => {
    if (!isLoading && user) {
      router.replace(ROUTES.DASHBOARD);
    }
  }, [user, isLoading, router]);

  const onSubmit = async (data: LoginFormValues) => {
    setGlobalError(null);
    try {
      await login(data.email);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      const msg =
        err.message ||
        (typeof detail === 'string' ? detail : null) ||
        'Login failed. Please try again.';
      setGlobalError(msg);
    }
  };

  const handleWeb3Connect = async (walletId: string) => {
    setGlobalError(null);
    setWeb3Status('connecting');
    try {
      // Find the wallet provider and connect
      const wallet = txnLab.wallets?.find((w: any) => w.id === walletId);
      if (!wallet) throw new Error('Wallet not found');
      await wallet.connect();
    } catch (err: any) {
      setGlobalError(err?.message || 'Failed to connect wallet');
      setWeb3Status('idle');
    }
  };

  const handleWeb3Login = async () => {
    if (!txnLab.activeAddress) return;
    setGlobalError(null);
    setWeb3Status('signing');

    try {
      // 1. Get challenge from backend
      const { data: challengeRes } = await api.get('/v1/auth/web3-challenge');
      const challenge = challengeRes.data;

      // 2. Build a zero-value self-payment transaction with challenge in the note
      const server = process.env.NEXT_PUBLIC_ALGOD_SERVER || 'https://testnet-api.4160.nodely.dev';
      const algod = new algosdk.Algodv2('', server, '');
      const sp = await algod.getTransactionParams().do();

      const txn = algosdk.makePaymentTxnWithSuggestedParamsFromObject({
        sender: txnLab.activeAddress,
        receiver: txnLab.activeAddress,
        amount: 0,
        note: new TextEncoder().encode(challenge.message_to_sign),
        suggestedParams: sp,
      });

      // 3. Sign with external wallet
      const encoded = [algosdk.encodeUnsignedTransaction(txn)];
      const signed = await txnLab.signTransactions(encoded);
      if (!signed[0]) throw new Error('Wallet did not return a signed transaction');
      const signedB64 = Buffer.from(signed[0] as Uint8Array).toString('base64');

      // 4. Verify with backend
      setWeb3Status('verifying');
      await web3Login(txnLab.activeAddress, challenge.challenge_id, signedB64);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      const msg =
        typeof detail === 'string' ? detail :
        err?.message || 'Web3 login failed';
      setGlobalError(msg);
      setWeb3Status('idle');
    }
  };

  // Auto-trigger login flow when wallet connects
  React.useEffect(() => {
    if (txnLab.activeAddress && web3Status === 'connecting') {
      handleWeb3Login();
    }
  }, [txnLab.activeAddress, web3Status]);

  if (isLoading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="relative h-10 w-10">
            <div className="absolute inset-0 rounded-full border-2 border-hairline" />
            <div className="absolute inset-0 rounded-full border-2 border-t-primary animate-spin" />
          </div>
          <p className="text-sm text-muted-foreground animate-pulse">Loading Cadencia...</p>
        </div>
      </div>
    );
  }

  if (user) return null;

  return (
    <div className="min-h-screen bg-surface-soft flex flex-col items-center justify-center p-4">
      <div className="w-full max-w-sm mb-4">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-ink transition-colors"
        >
          <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          Back to Cadencia
        </Link>
      </div>

      <div className="bg-card border border-hairline rounded-lg p-6 sm:p-8 w-full max-w-sm">
        <div className="flex flex-col items-center mb-6">
          <div className="bg-surface-soft border border-hairline rounded-lg p-3 mb-4">
            <Building2 className="h-6 w-6 text-ink" />
          </div>
          <h1 className="text-xl font-medium text-ink mb-1">Cadencia</h1>
          <p className="text-sm text-muted-foreground">AI-powered B2B trade platform</p>
        </div>

        {/* Tab Toggle */}
        <div className="flex rounded-lg border border-hairline overflow-hidden mb-6">
          <button
            type="button"
            onClick={() => { setActiveTab('magic'); setGlobalError(null); }}
            className={`flex-1 flex items-center justify-center gap-2 py-2.5 text-sm font-medium transition-colors ${
              activeTab === 'magic'
                ? 'bg-primary text-primary-foreground'
                : 'bg-card text-muted-foreground hover:text-ink'
            }`}
          >
            <Mail className="h-3.5 w-3.5" />
            Email & Wallet
          </button>
          <button
            type="button"
            onClick={() => { setActiveTab('web3'); setGlobalError(null); }}
            className={`flex-1 flex items-center justify-center gap-2 py-2.5 text-sm font-medium transition-colors ${
              activeTab === 'web3'
                ? 'bg-primary text-primary-foreground'
                : 'bg-card text-muted-foreground hover:text-ink'
            }`}
          >
            <Wallet className="h-3.5 w-3.5" />
            Connect Wallet
          </button>
        </div>

        {globalError && <ErrorBanner message={globalError} />}

        {/* ── Magic (Web2) Tab ── */}
        {activeTab === 'magic' && (
          <>
            <h2 className="text-base font-medium text-ink mb-2">Sign in with email</h2>
            <p className="text-xs text-muted-foreground mb-6">
              Enter your email — we&apos;ll send you a one-time code to sign in instantly.
            </p>

            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              <FormField
                label="Email address"
                required
                error={touchedFields.email ? errors.email?.message : undefined}
              >
                <Input
                  type="email"
                  placeholder="you@company.com"
                  className={touchedFields.email && errors.email ? 'border-destructive ring-destructive' : ''}
                  {...register('email')}
                />
              </FormField>

              <Button type="submit" disabled={isSubmitting} className="w-full mt-2">
                {isSubmitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Sending code...
                  </>
                ) : (
                  'Continue with Email'
                )}
              </Button>
            </form>
          </>
        )}

        {/* ── Web3 Tab ── */}
        {activeTab === 'web3' && (
          <>
            <h2 className="text-base font-medium text-ink mb-2">Sign in with wallet</h2>
            <p className="text-xs text-muted-foreground mb-6">
              Connect your Algorand wallet to sign in. You&apos;ll sign a message to verify ownership.
            </p>

            {web3Status !== 'idle' ? (
              <div className="flex flex-col items-center gap-3 py-6">
                <Loader2 className="h-6 w-6 animate-spin text-primary" />
                <p className="text-sm text-muted-foreground">
                  {web3Status === 'connecting' && 'Connecting wallet...'}
                  {web3Status === 'signing' && 'Sign the message in your wallet app...'}
                  {web3Status === 'verifying' && 'Verifying ownership...'}
                </p>
              </div>
            ) : txnLab.activeAddress ? (
              <div className="space-y-4">
                <div className="bg-surface-soft border border-hairline rounded-md p-3">
                  <p className="text-xs text-muted-foreground mb-1">Connected</p>
                  <p className="text-sm font-mono text-ink truncate">{txnLab.activeAddress}</p>
                </div>
                <Button onClick={handleWeb3Login} className="w-full">
                  Sign & Verify
                </Button>
              </div>
            ) : (
              <div className="space-y-2">
                {txnLab.wallets?.map((wallet: any) => (
                  <button
                    key={wallet.id}
                    onClick={() => handleWeb3Connect(wallet.id)}
                    className="w-full flex items-center gap-3 p-3 rounded-md border border-hairline bg-card hover:bg-surface-soft transition-colors text-left"
                  >
                    {wallet.metadata?.icon && (
                      <img src={wallet.metadata.icon} alt="" className="h-6 w-6 rounded" />
                    )}
                    <span className="text-sm font-medium text-ink">{wallet.metadata?.name || wallet.id}</span>
                  </button>
                ))}
              </div>
            )}
          </>
        )}

        <div className="border-t border-hairline w-full my-6" />

        <p className="text-center text-sm text-muted-foreground mb-3">
          New to Cadencia? Register as:
        </p>
        <div className="flex gap-3">
          <Link
            href="/register?role=buyer"
            className="flex-1 text-center py-2.5 px-4 rounded-lg text-sm font-medium transition-all duration-200 border border-primary bg-primary text-on-primary"
          >
            Buyer
          </Link>
          <Link
            href="/register?role=seller"
            className="flex-1 text-center py-2.5 px-4 rounded-lg text-sm font-medium transition-all duration-200 border border-hairline bg-card text-ink hover:bg-surface-soft"
          >
            Seller
          </Link>
        </div>

        {/* Admin Login */}
        {activeTab === 'magic' && (
          <>
            <div className="border-t border-hairline w-full my-6" />

            {!showAdminForm ? (
              <button
                type="button"
                onClick={() => setShowAdminForm(true)}
                className="w-full flex items-center justify-center gap-2 py-2 px-4 rounded-lg text-xs font-medium transition-all border border-hairline text-muted-foreground hover:text-ink hover:border-border-strong hover:bg-surface-soft"
              >
                <ShieldCheck className="h-3.5 w-3.5" />
                Admin Login
              </button>
            ) : (
              <AdminLoginForm
                onSubmit={async (email, password) => {
                  setAdminError(null);
                  setAdminSubmitting(true);
                  try {
                    await adminLogin(email, password);
                  } catch (err: any) {
                    const detail = err.response?.data?.detail;
                    const msg = typeof detail === 'string'
                      ? detail
                      : Array.isArray(detail)
                        ? detail.map((e: any) => e.msg || e.message || JSON.stringify(e)).join('; ')
                        : 'Invalid admin credentials.';
                    setAdminError(msg);
                    setAdminSubmitting(false);
                  }
                }}
                error={adminError}
                isSubmitting={adminSubmitting}
                onCancel={() => { setShowAdminForm(false); setAdminError(null); }}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}

function AdminLoginForm({
  onSubmit,
  error,
  isSubmitting,
  onCancel,
}: {
  onSubmit: (email: string, password: string) => Promise<void>;
  error: string | null;
  isSubmitting: boolean;
  onCancel: () => void;
}) {
  const [email, setEmail] = React.useState('');
  const [password, setPassword] = React.useState('');

  return (
    <div className="space-y-3 animate-in fade-in slide-in-from-bottom-2 duration-200">
      <div className="flex items-center gap-2 mb-2">
        <ShieldCheck className="h-4 w-4 text-amber-600" />
        <span className="text-sm font-medium text-ink">Platform Admin</span>
      </div>

      {error && (
        <div className="flex items-start gap-2 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900 rounded-md p-3 text-sm text-red-700 dark:text-red-400">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit(email, password);
        }}
        className="space-y-3"
      >
        <Input
          type="email"
          placeholder="Admin email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          className="text-sm"
        />
        <PasswordInput
          placeholder="Admin password"
          value={password}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => setPassword(e.target.value)}
          required
        />
        <div className="flex gap-2">
          <Button
            type="button"
            variant="ghost"
            onClick={onCancel}
            className="flex-1 text-sm"
            disabled={isSubmitting}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            disabled={isSubmitting || !email || !password}
            className="flex-1 bg-amber-600 text-white hover:bg-amber-700 text-sm"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                Signing in...
              </>
            ) : (
              'Sign In as Admin'
            )}
          </Button>
        </div>
      </form>
    </div>
  );
}
