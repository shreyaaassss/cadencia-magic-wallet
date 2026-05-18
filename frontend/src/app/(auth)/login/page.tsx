'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { Building2, AlertCircle, Loader2, ShieldCheck } from 'lucide-react';

import { useAuth } from '@/hooks/useAuth';
import { ROUTES } from '@/lib/constants';
import { FormField } from '@/components/shared/FormField';
import { PasswordInput } from '@/components/shared/PasswordInput';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const loginSchema = z.object({
  email: z.string().email('Enter a valid email address'),
  password: z.string().min(1, 'Password is required'),
});

type LoginFormValues = z.infer<typeof loginSchema>;

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 bg-red-950 border border-destructive/40 rounded-lg p-3 text-sm text-destructive mb-4">
      <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
      <span>{message}</span>
    </div>
  );
}

export default function LoginPage() {
  const router = useRouter();
  const { user, isLoading, login, adminLogin } = useAuth();
  const [globalError, setGlobalError] = React.useState<string | null>(null);
  const [showAdminForm, setShowAdminForm] = React.useState(false);
  const [adminError, setAdminError] = React.useState<string | null>(null);
  const [adminSubmitting, setAdminSubmitting] = React.useState(false);

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
      await login(data.email, data.password);
    } catch (err: any) {
      const status = err.response?.status;
      const detail = err.response?.data?.detail;
      if (status === 401 || status === 422 || status === 404) {
        const msg = typeof detail === 'string' ? detail : 'Invalid email or password. Please try again.';
        setGlobalError(msg);
      } else {
        setGlobalError(err.message || 'Unable to connect. Please try again.');
      }
    }
  };

  // Show a subtle spinner while the silent-refresh is in progress
  if (isLoading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="relative h-10 w-10">
            <div className="absolute inset-0 rounded-full border-2 border-muted" />
            <div className="absolute inset-0 rounded-full border-2 border-t-primary animate-spin" />
          </div>
          <p className="text-sm text-muted-foreground animate-pulse">Loading Cadencia…</p>
        </div>
      </div>
    );
  }

  // User already authenticated — redirect handled by useEffect above
  if (user) return null;

  return (
    <div className="min-h-screen bg-background flex flex-col items-center justify-center p-4">
      {/* Back to landing */}
      <div className="w-full max-w-sm mb-4">
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

      <div className="bg-card border border-border rounded-lg p-6 sm:p-8 w-full max-w-sm">
        <div className="flex flex-col items-center mb-6">
          <div className="bg-muted border border-border rounded-lg p-3 mb-4">
            <Building2 className="h-6 w-6 text-primary" />
          </div>
          <h1 className="text-xl font-semibold text-foreground mb-1">Cadencia</h1>
          <p className="text-sm text-muted-foreground">AI-powered B2B trade platform</p>
        </div>

        <div className="border-t border-border w-full mb-6" />

        <h2 className="text-base font-semibold text-foreground mb-6">Sign in to your account</h2>

        {globalError && <ErrorBanner message={globalError} />}

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <FormField
            label="Email address"
            required
            error={touchedFields.email ? errors.email?.message : undefined}
          >
            <Input
              type="email"
              className={touchedFields.email && errors.email ? 'border-destructive ring-destructive' : ''}
              {...register('email')}
            />
          </FormField>

          <FormField
            label="Password"
            required
            error={touchedFields.password ? errors.password?.message : undefined}
          >
            <PasswordInput
              error={touchedFields.password && !!errors.password}
              {...register('password')}
            />
          </FormField>

          <Button type="submit" disabled={isSubmitting} className="w-full bg-primary text-primary-foreground hover:bg-primary/90 mt-2">
            {isSubmitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Signing in...
              </>
            ) : (
              'Sign In'
            )}
          </Button>
        </form>

        <div className="border-t border-border w-full my-6" />

        <p className="text-center text-sm text-muted-foreground mb-3">
          New to Cadencia? Register as:
        </p>
        <div className="flex gap-3">
          <Link
            href="/register?role=buyer"
            className="flex-1 text-center py-2.5 px-4 rounded-lg text-sm font-medium transition-all duration-200 border border-primary/30 bg-primary/10 text-primary hover:bg-primary/20 hover:-translate-y-[1px]"
          >
            Buyer
          </Link>
          <Link
            href="/register?role=seller"
            className="flex-1 text-center py-2.5 px-4 rounded-lg text-sm font-medium transition-all duration-200 border border-border bg-transparent text-foreground hover:bg-accent hover:border-muted-foreground hover:-translate-y-[1px]"
          >
            Seller
          </Link>
        </div>

        {/* Admin Login */}
        <div className="border-t border-border w-full my-6" />

        {!showAdminForm ? (
          <button
            type="button"
            onClick={() => setShowAdminForm(true)}
            className="w-full flex items-center justify-center gap-2 py-2 px-4 rounded-lg text-xs font-medium transition-all border border-border text-muted-foreground hover:text-foreground hover:border-primary/40 hover:bg-primary/5"
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
        <ShieldCheck className="h-4 w-4 text-amber-400" />
        <span className="text-sm font-medium text-foreground">Platform Admin</span>
      </div>

      {error && <ErrorBanner message={error} />}

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
