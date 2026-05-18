'use client';

import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { api, setAccessToken } from '@/lib/api';
import { destroyWalletManager, clearForeignWalletSession } from '@/lib/wallet-config';
import type { User, Enterprise } from '@/types';
import { ROUTES } from '@/lib/constants';

interface AuthContextValue {
  user: User | null;
  enterprise: Enterprise | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  adminLogin: (email: string, password: string) => Promise<void>;
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
  const [isLoading, setIsLoading] = useState(true);

  /** Fetch user profile + enterprise using current access token */
  const fetchProfile = useCallback(async () => {
    const { data: meRes } = await api.get('/v1/auth/me');
    const me: User = meRes.data;
    setUser(me);

    if (me.enterprise_id) {
      try {
        const { data: entRes } = await api.get(`/v1/enterprises/${me.enterprise_id}`);
        const ent = entRes.data;
        setEnterprise(ent);
        // Allow same-user wallet auto-reconnect; purge session only if a
        // different enterprise is logging in on this device.
        clearForeignWalletSession(String(ent.id));
      } catch {
        // Enterprise fetch failed — admin backdoor user has no real enterprise.
        // Keep user authenticated, just clear enterprise.
        setEnterprise(null);
      }
    }
  }, []);

  // Silent refresh on mount
  useEffect(() => {
    const init = async () => {
      try {
        const { data } = await api.post('/v1/auth/refresh');
        setAccessToken(data.data.access_token);
        await fetchProfile();
      } catch {
        setAccessToken(null);
        setUser(null);
        setEnterprise(null);
      } finally {
        setIsLoading(false);
      }
    };
    init();
  }, [fetchProfile]);

  // Listen for session-expired events from the 401 interceptor
  useEffect(() => {
    const handleSessionExpired = () => {
      setAccessToken(null);
      setUser(null);
      setEnterprise(null);
    };
    window.addEventListener('auth:session-expired', handleSessionExpired);
    return () => window.removeEventListener('auth:session-expired', handleSessionExpired);
  }, []);

  const login = async (email: string, password: string) => {
    const { data } = await api.post('/v1/auth/login', { email, password });
    setAccessToken(data.data.access_token);
    try {
      await fetchProfile();
    } catch {
      // Profile fetch failed after successful auth — clear token and surface error
      setAccessToken(null);
      throw new Error('Logged in but failed to load your profile. Please try again.');
    }
    router.push(ROUTES.DASHBOARD);
  };

  const adminLogin = async (email: string, password: string) => {
    const { data } = await api.post('/v1/auth/admin-login', { email, password });
    setAccessToken(data.data.access_token);
    try {
      await fetchProfile();
    } catch {
      // Admin backdoor user has no real enterprise — profile fetch may fail.
      // Keep authenticated, just skip profile.
    }
    router.push(ROUTES.ADMIN);
  };

  const register = async (payload: Record<string, unknown>) => {
    const { data } = await api.post('/v1/auth/register', payload);
    setAccessToken(data.data.access_token);
    try {
      await fetchProfile();
    } catch {
      // Profile fetch failed after successful auth — clear token and surface error
      setAccessToken(null);
      throw new Error('Registered but failed to load your profile. Please try again.');
    }
    router.push(ROUTES.DASHBOARD);
  };

  const logout = async () => {
    // 1. Disconnect wallet and record enterprise ID as session owner.
    //    Session keys are preserved so the same user can auto-reconnect
    //    on next login. Cross-user bleed is handled by clearForeignWalletSession()
    //    which fires during the next login's fetchProfile().
    await destroyWalletManager(enterprise?.id ? String(enterprise.id) : undefined);

    // 2. Clear the httpOnly refresh token cookie on the server so page refresh
    //    cannot silently re-authenticate.
    try {
      await api.post('/v1/auth/logout');
    } catch {
      // Non-fatal — still clear local state
    }

    setAccessToken(null);
    setUser(null);
    setEnterprise(null);

    router.push(ROUTES.LOGIN);
  };

  const isAdmin = user?.role === 'ADMIN';
  const isBuyer = enterprise?.trade_role === 'BUYER' || enterprise?.trade_role === 'BOTH';
  const isSeller = enterprise?.trade_role === 'SELLER' || enterprise?.trade_role === 'BOTH';

  return (
    <AuthContext.Provider value={{
      user, enterprise, isLoading,
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
