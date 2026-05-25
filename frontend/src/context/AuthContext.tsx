'use client';

import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { api, setAccessToken } from '@/lib/api';
import { magic, getMagicAddress } from '@/lib/magic';
import type { User, Enterprise } from '@/types';
import { ROUTES } from '@/lib/constants';

export type AuthMethod = 'magic' | 'web3' | null;

interface AuthContextValue {
  user: User | null;
  enterprise: Enterprise | null;
  walletAddress: string | null;
  isLoading: boolean;
  authMethod: AuthMethod;
  /** Magic OTP login — email only, no password */
  login: (email: string) => Promise<void>;
  /** Password-based admin backdoor — kept for platform admin use */
  adminLogin: (email: string, password: string) => Promise<void>;
  /** Magic-based registration — submits enterprise data + authenticates via Magic */
  register: (payload: Record<string, unknown>) => Promise<void>;
  /** Web3 wallet login — wallet address + challenge signature */
  web3Login: (walletAddress: string, challengeId: string, signedTxn: string) => Promise<void>;
  /** Web3 wallet registration — wallet + enterprise data + challenge signature */
  web3Register: (payload: Record<string, unknown>, walletAddress: string, challengeId: string, signedTxn: string) => Promise<void>;
  logout: () => Promise<void>;
  setUser: (user: User) => void;
  setEnterprise: (enterprise: Enterprise) => void;
  refreshProfile: () => Promise<void>;
  isAdmin: boolean;
  isBuyer: boolean;
  isSeller: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const AUTH_METHOD_KEY = 'cadencia_auth_method';

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [enterprise, setEnterprise] = useState<Enterprise | null>(null);
  const [walletAddress, setWalletAddress] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [authMethod, setAuthMethod] = useState<AuthMethod>(null);

  const persistAuthMethod = (method: AuthMethod) => {
    setAuthMethod(method);
    if (method) {
      localStorage.setItem(AUTH_METHOD_KEY, method);
    } else {
      localStorage.removeItem(AUTH_METHOD_KEY);
    }
  };

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
   */
  const _hydrateFromMagic = useCallback(async () => {
    if (!magic) throw new Error('Magic SDK not available');

    const info = await (magic.user as any).getInfo();
    const metadata = { email: info.email };
    let address: string | null = null;
    try {
      address = (info as any).publicAddress as string ?? null;
      if (address) setWalletAddress(address);
    } catch {}

    const didToken = await magic.user.getIdToken();

    try {
      const { data } = await api.post('/v1/auth/magic-login', {
        did_token: didToken,
        email: metadata.email,
        algo_address: address ?? '',
      });
      setAccessToken(data.data.access_token);
      persistAuthMethod('magic');
      await fetchProfile();
    } catch (err: any) {
      try { await magic.user.logout(); } catch {}
      setWalletAddress(null);

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

  // On mount: restore session based on persisted auth method
  useEffect(() => {
    const init = async () => {
      const savedMethod = localStorage.getItem(AUTH_METHOD_KEY) as AuthMethod;

      try {
        if (savedMethod === 'magic' || !savedMethod) {
          // Try Magic session restore
          if (magic) {
            const isLoggedIn = await magic.user.isLoggedIn();
            if (isLoggedIn) {
              await _hydrateFromMagic();
              setIsLoading(false);
              return;
            }
          }
        }

        // Fallback: silent refresh for admin users or web3 users (cookie-based)
        const { data } = await api.post('/v1/auth/refresh');
        setAccessToken(data.data.access_token);
        if (savedMethod) setAuthMethod(savedMethod);
        await fetchProfile();
      } catch {
        setAccessToken(null);
        setUser(null);
        setEnterprise(null);
        setWalletAddress(null);
        persistAuthMethod(null);
        if (magic) {
          try { await magic.user.logout(); } catch {}
        }
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
      persistAuthMethod(null);
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

  /** Password-based admin backdoor */
  const adminLogin = async (email: string, password: string) => {
    const { data } = await api.post('/v1/auth/admin-login', { email, password });
    setAccessToken(data.data.access_token);
    persistAuthMethod(null);
    try { await fetchProfile(); } catch {}
    router.push(ROUTES.ADMIN);
  };

  /** Magic-based registration */
  const register = async (payload: Record<string, unknown>) => {
    if (!magic) throw new Error('Magic SDK not available');

    const userPayload = payload.user as { email: string; full_name: string };
    setIsLoading(true);
    try {
      await magic.auth.loginWithEmailOTP({ email: userPayload.email });
      const didToken = await magic.user.getIdToken();
      let algoAddress = '';
      try {
        algoAddress = await getMagicAddress();
        setWalletAddress(algoAddress);
      } catch {}

      const { data } = await api.post('/v1/auth/magic-register', {
        did_token: didToken,
        algo_address: algoAddress,
        enterprise: payload.enterprise,
        user: { email: userPayload.email, full_name: userPayload.full_name },
      });
      setAccessToken(data.data.access_token);
      persistAuthMethod('magic');
      await fetchProfile();
      router.push(ROUTES.DASHBOARD);
    } finally {
      setIsLoading(false);
    }
  };

  /** Web3 wallet login — Pera/Defly/Lute */
  const web3Login = async (address: string, challengeId: string, signedTxn: string) => {
    setIsLoading(true);
    try {
      const { data } = await api.post('/v1/auth/web3-login', {
        wallet_address: address,
        challenge_id: challengeId,
        signed_txn: signedTxn,
      });
      setAccessToken(data.data.access_token);
      setWalletAddress(address);
      persistAuthMethod('web3');
      await fetchProfile();
      router.push(ROUTES.DASHBOARD);
    } finally {
      setIsLoading(false);
    }
  };

  /** Web3 wallet registration — Pera/Defly/Lute */
  const web3Register = async (
    payload: Record<string, unknown>,
    address: string,
    challengeId: string,
    signedTxn: string,
  ) => {
    setIsLoading(true);
    try {
      const userPayload = payload.user as { email: string; full_name: string };
      const { data } = await api.post('/v1/auth/web3-register', {
        wallet_address: address,
        challenge_id: challengeId,
        signed_txn: signedTxn,
        enterprise: payload.enterprise,
        user: { email: userPayload.email, full_name: userPayload.full_name },
      });
      setAccessToken(data.data.access_token);
      setWalletAddress(address);
      persistAuthMethod('web3');
      await fetchProfile();
      router.push(ROUTES.DASHBOARD);
    } finally {
      setIsLoading(false);
    }
  };

  const logout = async () => {
    const method = authMethod;
    if (method === 'magic' || !method) {
      if (magic) {
        try { await magic.user.logout(); } catch {}
      }
    }
    try { await api.post('/v1/auth/logout'); } catch {}
    setAccessToken(null);
    setUser(null);
    setEnterprise(null);
    setWalletAddress(null);
    persistAuthMethod(null);
    router.push(ROUTES.LOGIN);
  };

  const isAdmin = user?.role === 'ADMIN';
  const isBuyer = enterprise?.trade_role === 'BUYER' || enterprise?.trade_role === 'BOTH';
  const isSeller = enterprise?.trade_role === 'SELLER' || enterprise?.trade_role === 'BOTH';

  return (
    <AuthContext.Provider value={{
      user, enterprise, walletAddress, isLoading, authMethod,
      login, adminLogin, register, web3Login, web3Register, logout,
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
