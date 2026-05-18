'use client';

import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { api, setAccessToken } from '@/lib/api';
import { magic, getMagicAddress } from '@/lib/magic';
import type { User, Enterprise } from '@/types';
import { ROUTES } from '@/lib/constants';

interface AuthContextValue {
  user: User | null;
  enterprise: Enterprise | null;
  walletAddress: string | null;
  isLoading: boolean;
  /** Magic OTP login — email only, no password */
  login: (email: string) => Promise<void>;
  /** Password-based admin backdoor — kept for platform admin use */
  adminLogin: (email: string, password: string) => Promise<void>;
  /** Magic-based registration — submits enterprise data + authenticates via Magic */
  register: (payload: Record<string, unknown>) => Promise<void>;
  logout: () => Promise<void>;
  setUser: (user: User) => void;
  setEnterprise: (enterprise: Enterprise) => void;
  refreshProfile: () => Promise<void>;
  isAdmin: boolean;
  isBuyer: boolean;
  isSeller: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [enterprise, setEnterprise] = useState<Enterprise | null>(null);
  const [walletAddress, setWalletAddress] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  /** Fetch Cadencia user profile + enterprise after we have an access token */
  const fetchProfile = useCallback(async () => {
    const { data: meRes } = await api.get('/v1/auth/me');
    const me: User = meRes.data;
    setUser(me);

    if (me.enterprise_id) {
      try {
        const { data: entRes } = await api.get(`/v1/enterprises/${me.enterprise_id}`);
        setEnterprise(entRes.data);
      } catch {
        setEnterprise(null);
      }
    }
  }, []);

  /**
   * Exchange a Magic DID token for a Cadencia JWT, then load the profile.
   * Called after Magic OTP succeeds (login) and on session restore.
   *
   * If the backend rejects the user (not registered, network error, etc.)
   * we log them out of Magic immediately so they aren't stuck in a half-authed
   * state where every subsequent page load triggers another failed hydration.
   */
  const _hydrateFromMagic = useCallback(async () => {
    if (!magic) throw new Error('Magic SDK not available');

    const metadata = await magic.user.getMetadata();
    let address: string | null = null;
    try {
      address = await getMagicAddress();
      setWalletAddress(address);
    } catch {
      // Non-fatal — wallet address may be unavailable if Algorand not enabled
    }

    const didToken = await magic.user.getIdToken();

    try {
      const { data } = await api.post('/v1/auth/magic-login', {
        did_token: didToken,
        email: metadata.email,
        algo_address: address ?? '',
      });
      setAccessToken(data.data.access_token);
      await fetchProfile();
    } catch (err: any) {
      // Backend rejected — log out of Magic so the user doesn't get stuck
      try { await magic.user.logout(); } catch {}
      setWalletAddress(null);

      // Surface the backend's detail message if available
      const detail = err?.response?.data?.detail;
      const status = err?.response?.status;
      if (status === 401 || status === 404) {
        throw new Error(
          typeof detail === 'string'
            ? detail
            : 'No account found for this email. Please register first.'
        );
      }
      throw new Error(
        typeof detail === 'string'
          ? detail
          : err?.message || 'Login failed. Please try again.'
      );
    }
  }, [fetchProfile]);

  // On mount: try Magic session first, then fall back to refresh-cookie session
  useEffect(() => {
    const init = async () => {
      try {
        if (magic) {
          const isLoggedIn = await magic.user.isLoggedIn();
          if (isLoggedIn) {
            await _hydrateFromMagic();
            setIsLoading(false);
            return;
          }
        }
        // Fallback: silent refresh for admin users (password-based sessions)
        const { data } = await api.post('/v1/auth/refresh');
        setAccessToken(data.data.access_token);
        await fetchProfile();
      } catch {
        setAccessToken(null);
        setUser(null);
        setEnterprise(null);
        setWalletAddress(null);
      } finally {
        setIsLoading(false);
      }
    };
    init();
  }, [_hydrateFromMagic, fetchProfile]);

  // Listen for session-expired events from the 401 interceptor
  useEffect(() => {
    const handleSessionExpired = () => {
      setAccessToken(null);
      setUser(null);
      setEnterprise(null);
      setWalletAddress(null);
    };
    window.addEventListener('auth:session-expired', handleSessionExpired);
    return () => window.removeEventListener('auth:session-expired', handleSessionExpired);
  }, []);

  /** Magic OTP login — email only */
  const login = async (email: string) => {
    if (!magic) throw new Error('Magic SDK not available');
    setIsLoading(true);
    try {
      await magic.auth.loginWithEmailOTP({ email });
      await _hydrateFromMagic();
      router.push(ROUTES.DASHBOARD);
    } finally {
      setIsLoading(false);
    }
  };

  /** Password-based admin backdoor — unchanged */
  const adminLogin = async (email: string, password: string) => {
    const { data } = await api.post('/v1/auth/admin-login', { email, password });
    setAccessToken(data.data.access_token);
    try {
      await fetchProfile();
    } catch {
      // Admin user may have no enterprise — keep authenticated
    }
    router.push(ROUTES.ADMIN);
  };

  /**
   * Magic-based registration.
   *
   * The payload includes enterprise data + user { email, full_name }.
   * We first authenticate via Magic OTP, then submit everything to
   * POST /v1/auth/magic-register which creates the enterprise without a password.
   */
  const register = async (payload: Record<string, unknown>) => {
    if (!magic) throw new Error('Magic SDK not available');

    const userPayload = payload.user as { email: string; full_name: string };
    setIsLoading(true);
    try {
      // 1. Authenticate via Magic OTP
      await magic.auth.loginWithEmailOTP({ email: userPayload.email });

      // 2. Get DID token + ALGO address
      const didToken = await magic.user.getIdToken();
      let algoAddress = '';
      try {
        algoAddress = await getMagicAddress();
        setWalletAddress(algoAddress);
      } catch {
        // Non-fatal
      }

      // 3. Submit enterprise data to magic-register endpoint
      const { data } = await api.post('/v1/auth/magic-register', {
        did_token: didToken,
        algo_address: algoAddress,
        enterprise: payload.enterprise,
        user: {
          email: userPayload.email,
          full_name: userPayload.full_name,
        },
      });
      setAccessToken(data.data.access_token);
      await fetchProfile();
      router.push(ROUTES.DASHBOARD);
    } finally {
      setIsLoading(false);
    }
  };

  const logout = async () => {
    if (magic) {
      try { await magic.user.logout(); } catch {}
    }
    try { await api.post('/v1/auth/logout'); } catch {}
    setAccessToken(null);
    setUser(null);
    setEnterprise(null);
    setWalletAddress(null);
    router.push(ROUTES.LOGIN);
  };

  const isAdmin = user?.role === 'ADMIN';
  const isBuyer = enterprise?.trade_role === 'BUYER' || enterprise?.trade_role === 'BOTH';
  const isSeller = enterprise?.trade_role === 'SELLER' || enterprise?.trade_role === 'BOTH';

  return (
    <AuthContext.Provider value={{
      user, enterprise, walletAddress, isLoading,
      login, adminLogin, register, logout,
      setUser, setEnterprise,
      refreshProfile: fetchProfile,
      isAdmin, isBuyer, isSeller,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
