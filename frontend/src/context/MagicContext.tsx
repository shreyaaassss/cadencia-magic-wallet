'use client';

/**
 * MagicContext — React context for Magic.link embedded Algorand wallet.
 *
 * Coexists with the existing AuthContext (session-based login). Magic is
 * additive: it handles wallet-related features only.
 *
 * Provider must be added inside layout.tsx wrapping wallet-dependent children.
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from 'react';
import { magic, getMagicWallet } from '@/lib/magic';

// ── Types ─────────────────────────────────────────────────────────────────────

interface MagicContextValue {
  /** Magic auth metadata (null when not logged in or SDK unavailable) */
  user: Record<string, unknown> | null;
  /** Algorand public address from the Magic wallet */
  walletAddress: string | null;
  /** True while a login/logout call is in flight */
  isLoading: boolean;
  /** Authenticate with Magic using an email OTP */
  loginWithMagic: (email: string) => Promise<void>;
  /** Terminate the Magic session */
  logoutFromMagic: () => Promise<void>;
}

// ── Context ───────────────────────────────────────────────────────────────────

const MagicContext = createContext<MagicContextValue | null>(null);

// ── Provider ──────────────────────────────────────────────────────────────────

export function MagicProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<Record<string, unknown> | null>(null);
  const [walletAddress, setWalletAddress] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  /** Restore Magic session on mount */
  useEffect(() => {
    const restore = async () => {
      if (!magic) {
        setIsLoading(false);
        return;
      }
      try {
        const isLoggedIn = await magic.user.isLoggedIn();
        if (isLoggedIn) {
          const metadata = await magic.user.getMetadata();
          setUser(metadata as unknown as Record<string, unknown>);
          const address = await getMagicWallet();
          setWalletAddress(address);
        }
      } catch {
        // No active session — silently proceed
        setUser(null);
        setWalletAddress(null);
      } finally {
        setIsLoading(false);
      }
    };
    restore();
  }, []);

  const loginWithMagic = useCallback(async (email: string) => {
    if (!magic) throw new Error('[magic] Magic SDK is not initialised');
    setIsLoading(true);
    try {
      await magic.auth.loginWithEmailOTP({ email });
      const metadata = await magic.user.getMetadata();
      setUser(metadata as unknown as Record<string, unknown>);
      const address = await getMagicWallet();
      setWalletAddress(address);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const logoutFromMagic = useCallback(async () => {
    if (!magic) return;
    setIsLoading(true);
    try {
      await magic.user.logout();
      setUser(null);
      setWalletAddress(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  return (
    <MagicContext.Provider
      value={{ user, walletAddress, isLoading, loginWithMagic, logoutFromMagic }}
    >
      {children}
    </MagicContext.Provider>
  );
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useMagic(): MagicContextValue {
  const ctx = useContext(MagicContext);
  if (!ctx) throw new Error('useMagic must be used inside MagicProvider');
  return ctx;
}
