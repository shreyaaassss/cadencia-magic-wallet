'use client';

import React, { createContext, useContext, useState, useCallback } from 'react';
import { toast } from 'sonner';
import algosdk from 'algosdk';
import { api } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';
import { useWalletReady } from '@/components/providers/AlgorandWalletProvider';
import { setLastWalletId } from '@/lib/wallet-config';
import type { WalletBalance } from '@/types';

type LinkStatus = 'idle' | 'signing' | 'submitting' | 'error';

interface CadenciaWalletContextValue {
  // Algorand wallet state (from use-wallet)
  activeAddress: string | null;
  wallets: any[];
  isWalletConnected: boolean;
  isReady: boolean;
  isConnecting: boolean;
  connectWallet: (walletId: string) => Promise<void>;
  disconnectWallet: () => Promise<void>;

  // Cadencia platform link state
  isLinked: boolean;
  linkedAddress: string | null;
  balance: WalletBalance | null;
  isLoadingBalance: boolean;
  linkStatus: LinkStatus;
  error: string | null;
  linkWallet: () => Promise<void>;
  unlinkWallet: () => Promise<void>;
  refreshBalance: () => Promise<void>;
  signAndSubmitFundTxn: (escrowId: string) => Promise<{ txid: string; confirmed_round: number; status: string }>;
  signAndSubmitDeployTxn: (sessionId: string, params: { buyerAddress: string; sellerAddress: string; amountMicroAlgo: number }) => Promise<{ escrow_id: string; app_id: number; app_address: string; tx_id: string; confirmed_round: number }>;
  signAndSubmitReleaseTxn: (escrowId: string) => Promise<{ txid: string; confirmed_round: number; status: string }>;
  signAndSubmitRefundTxn: (escrowId: string, reason: string) => Promise<{ txid: string; confirmed_round: number; status: string }>;
}

const CadenciaWalletContext = createContext<CadenciaWalletContextValue | null>(null);

/**
 * Build a zero-value self-payment transaction with the challenge message in the note field.
 * This transaction is never broadcast - it's only used for signature verification.
 */
function buildChallengeTxn(address: string, challengeMessage: string): algosdk.Transaction {
  const note = new TextEncoder().encode(challengeMessage);

  // Dummy suggested params — this txn is never broadcast, only signed for verification
  const params: algosdk.SuggestedParams = {
    fee: 0,
    minFee: 1000,
    firstValid: 1,
    lastValid: 1000,
    genesisHash: algosdk.base64ToBytes('SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI='),
    genesisID: 'testnet-v1.0',
  };

  return algosdk.makePaymentTxnWithSuggestedParamsFromObject({
    sender: address,
    receiver: address,
    amount: 0,
    note,
    suggestedParams: params,
  });
}

/**
 * Inner provider that uses useWallet() — only rendered when WalletProvider is available.
 */
function WalletEnabledProvider({ children }: { children: React.ReactNode }) {
  // Safe to import and call useWallet here — WalletProvider is guaranteed to be a parent.
  const { useWallet } = require('@txnlab/use-wallet-react');
  const { enterprise, refreshProfile } = useAuth();
  const {
    wallets,
    activeAddress,
    activeWallet,
    isReady,
    signTransactions,
  } = useWallet();

  const [balance, setBalance] = useState<WalletBalance | null>(null);
  const [isLoadingBalance, setIsLoadingBalance] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [linkStatus, setLinkStatus] = useState<LinkStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const prevEnterpriseIdRef = React.useRef<string | null>(null);

  const isWalletConnected = !!activeAddress;
  const isLinked = !!enterprise?.algorand_wallet;
  const linkedAddress = enterprise?.algorand_wallet ?? null;

  // Force disconnect on logout or enterprise change (prevents wallet bleed)
  React.useEffect(() => {
    const currentId = enterprise?.id?.toString() ?? null;
    const prevId = prevEnterpriseIdRef.current;

    // Disconnect when: user logs out (prevId→null) OR switches enterprise
    if (prevId && prevId !== currentId) {
      // Disconnect ALL wallet providers, not just activeWallet.
      // Pera WalletConnect sessions persist in the browser even after the active
      // wallet is "disconnected". If only activeWallet.disconnect() is called,
      // the next user to connect Pera may silently inherit the previous session,
      // causing fund/release transactions to be signed by the wrong account.
      for (const wallet of wallets) {
        wallet.disconnect().catch(() => {});
      }
      setBalance(null);
    }
    prevEnterpriseIdRef.current = currentId;
  }, [enterprise?.id, wallets]);

  // Warn if connected wallet address doesn't match linked enterprise wallet
  React.useEffect(() => {
    if (activeAddress && linkedAddress && activeAddress !== linkedAddress) {
      toast.error(
        `Connected wallet (${activeAddress.slice(0, 8)}...) does not match your linked enterprise wallet. Please disconnect and connect the correct wallet.`,
        { duration: 8000 }
      );
    }
  }, [activeAddress, linkedAddress]);

  const connectWallet = useCallback(async (walletId: string) => {
    if (isConnecting) return; // Prevent double-clicks
    setError(null);
    setIsConnecting(true);
    const wallet = wallets.find((w: any) => w.id === walletId);
    if (!wallet) {
      setError(`Wallet "${walletId}" not available`);
      setIsConnecting(false);
      return;
    }

    const MAX_RETRIES = 2;
    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      try {
        await wallet.connect();
        setLastWalletId(walletId);
        toast.success(`Connected to ${wallet.metadata.name}`);
        setIsConnecting(false);
        return;
      } catch (err: any) {
        const msg = err?.message || 'Failed to connect wallet';
        // If user explicitly cancelled, don't retry
        if (msg.toLowerCase().includes('cancel') || msg.toLowerCase().includes('reject') || msg.toLowerCase().includes('closed')) {
          setError(msg);
          toast.error(msg);
          setIsConnecting(false);
          return;
        }
        if (attempt < MAX_RETRIES) {
          // Brief pause before retry
          await new Promise(r => setTimeout(r, 1000));
        } else {
          setError(msg);
          toast.error(msg);
        }
      }
    }
    setIsConnecting(false);
  }, [wallets, isConnecting]);

  const disconnectWallet = useCallback(async () => {
    try {
      if (activeWallet) {
        await activeWallet.disconnect();
        toast.success('Wallet disconnected');
      }
    } catch {
      toast.error('Failed to disconnect wallet');
    }
  }, [activeWallet]);

  const linkWallet = useCallback(async () => {
    if (!activeAddress) {
      toast.error('Connect a wallet first');
      return;
    }
    setError(null);
    setLinkStatus('signing');

    try {
      const { data: challengeRes } = await api.get('/v1/wallet/challenge');
      const challenge = challengeRes.data;
      const txn = buildChallengeTxn(activeAddress, challenge.challenge);
      const signedTxns = await signTransactions([txn]);
      const signedTxn = signedTxns[0];
      if (!signedTxn) throw new Error('Transaction signing was cancelled');
      const signedTxnB64 = btoa(String.fromCharCode(...new Uint8Array(signedTxn)));

      setLinkStatus('submitting');
      await api.post('/v1/wallet/link', {
        algorand_address: activeAddress,
        signed_txn: signedTxnB64,
      });

      await refreshProfile();
      setLinkStatus('idle');
      toast.success('Wallet linked successfully');

      // Auto-fetch balance immediately after linking
      try {
        setIsLoadingBalance(true);
        const { data } = await api.get('/v1/wallet/balance');
        setBalance(data.data);
      } catch {
        // Non-fatal — the user can click refresh
      } finally {
        setIsLoadingBalance(false);
      }
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || 'Failed to link wallet';
      setError(msg);
      setLinkStatus('error');
      toast.error(msg);
    }
  }, [activeAddress, signTransactions, refreshProfile]);

  const unlinkWallet = useCallback(async () => {
    try {
      await api.delete('/v1/wallet/link');
      await refreshProfile();
      setBalance(null);
      toast.success('Wallet unlinked');
    } catch {
      toast.error('Failed to unlink wallet');
    }
  }, [refreshProfile]);

  const refreshBalance = useCallback(async () => {
    if (!isLinked) return;
    setIsLoadingBalance(true);
    try {
      const { data } = await api.get('/v1/wallet/balance');
      setBalance(data.data);
    } catch {
      toast.error('Failed to fetch wallet balance');
    } finally {
      setIsLoadingBalance(false);
    }
  }, [isLinked]);

  /**
   * Get an algod client pointing at the same TestNet that Pera Wallet uses.
   * Transactions built with these params will have the correct genesis hash/ID.
   */
  const getAlgod = useCallback(() => {
    const server = process.env.NEXT_PUBLIC_ALGOD_SERVER || 'https://testnet-api.4160.nodely.dev';
    const port = process.env.NEXT_PUBLIC_ALGOD_PORT || '';
    const token = process.env.NEXT_PUBLIC_ALGOD_TOKEN || '';
    return new algosdk.Algodv2(token, server, port);
  }, []);

  /** Decode a base64 string to Uint8Array. */
  const b64ToBytes = (b64: string) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));

  /**
   * Sign Transaction[] via use-wallet → base64 strings for backend submission.
   * Hard-blocks signing if the active wallet doesn't match the linked enterprise
   * wallet — prevents silent wrong-wallet transactions (Issue #5).
   */
  const signTxns = useCallback(async (txns: algosdk.Transaction[]): Promise<string[]> => {
    // Hard guard: connected wallet must match the enterprise's linked wallet
    if (linkedAddress && activeAddress && activeAddress !== linkedAddress) {
      throw new Error(
        `Wallet mismatch: Pera is connected to ${activeAddress.slice(0, 8)}... ` +
        `but your enterprise is linked to ${linkedAddress.slice(0, 8)}.... ` +
        `Go to Settings \u2192 Wallet, disconnect, then reconnect with the correct account.`
      );
    }
    const signedResults = await signTransactions(txns);
    const out: string[] = [];
    for (const s of signedResults) {
      if (!s) throw new Error('Transaction signing was cancelled');
      out.push(btoa(String.fromCharCode(...new Uint8Array(s))));
    }
    return out;
  }, [signTransactions, activeAddress, linkedAddress]);


  // ── Deploy ────────────────────────────────────────────────────────────────

  const signAndSubmitDeployTxn = useCallback(async (
    sessionId: string,
    params: { buyerAddress: string; sellerAddress: string; amountMicroAlgo: number },
  ) => {
    if (!activeAddress) throw new Error('No wallet connected');
    setError(null);

    try {
      // 1. Get raw components (TEAL + ABI args) from backend
      const query = new URLSearchParams({
        deployer_address: activeAddress,
        buyer_address: params.buyerAddress,
        seller_address: params.sellerAddress,
        amount_microalgo: String(params.amountMicroAlgo),
      });
      const { data: buildRes } = await api.get(`/v1/escrow/${sessionId}/build-deploy-txn?${query}`);
      const d = buildRes.data;

      // 2. Get suggested params from TestNet algod
      const algod = getAlgod();
      const sp = await algod.getTransactionParams().do();

      // 3. Build ApplicationCreateTxn locally with algosdk v3
      const txn = algosdk.makeApplicationCreateTxnFromObject({
        sender: activeAddress,
        suggestedParams: sp,
        approvalProgram: b64ToBytes(d.approval_program_b64),
        clearProgram: b64ToBytes(d.clear_program_b64),
        numGlobalInts: d.global_schema.num_uints,
        numGlobalByteSlices: d.global_schema.num_byte_slices,
        numLocalInts: d.local_schema.num_uints,
        numLocalByteSlices: d.local_schema.num_byte_slices,
        appArgs: d.app_args_b64.map(b64ToBytes),
        onComplete: algosdk.OnApplicationComplete.NoOpOC,
      });

      // 4. Sign via use-wallet (same path as linkWallet)
      const signedB64 = await signTxns([txn]);

      // 5. Submit signed bytes to backend
      const { data: submitRes } = await api.post(`/v1/escrow/${sessionId}/submit-signed-deploy`, {
        signed_transactions: signedB64,
      });

      toast.success(`Escrow deployed! App ID: ${submitRes.data.app_id}`);
      return submitRes.data;
    } catch (err: any) {
      const msg = err?.message || 'Deploy transaction failed';
      setError(msg);
      toast.error(msg);
      throw err;
    }
  }, [activeAddress, getAlgod, signTxns]);

  // ── Fund ──────────────────────────────────────────────────────────────────

  const signAndSubmitFundTxn = useCallback(async (escrowId: string) => {
    if (!activeAddress) throw new Error('No wallet connected');
    setError(null);

    try {
      // 1. Get fund components from backend
      const { data: buildRes } = await api.get(`/v1/escrow/${escrowId}/build-fund-txn`);
      const d = buildRes.data;

      // 2. Get suggested params from TestNet algod
      const algod = getAlgod();
      const sp = await algod.getTransactionParams().do();

      // 3. Build atomic group: [Fund payment, AppCallTxn(fund)]
      //    The shared escrow contract is already seeded with 0.1 ALGO MBR during
      //    deployment (seller-approve → _ensure_shared_app). Sending MBR again
      //    creates a redundant second payment visible to the user in Pera wallet,
      //    causing confusion ("two payments to a random wallet").
      //    ARC-4 fund(pay)void: the payment at GroupIndex-1 is the pay arg.
      const payTxn = algosdk.makePaymentTxnWithSuggestedParamsFromObject({
        sender: activeAddress,
        receiver: d.app_address,
        amount: d.amount_microalgo,
        suggestedParams: sp,
      });

      const callTxn = algosdk.makeApplicationCallTxnFromObject({
        sender: activeAddress,
        appIndex: d.app_id,
        onComplete: algosdk.OnApplicationComplete.NoOpOC,
        appArgs: [b64ToBytes(d.method_selector_b64)],
        suggestedParams: sp,
      });

      algosdk.assignGroupID([payTxn, callTxn]);

      // 4. Sign via use-wallet
      const signedB64 = await signTxns([payTxn, callTxn]);

      // 5. Submit
      const { data: submitRes } = await api.post(`/v1/escrow/${escrowId}/submit-signed-fund`, {
        signed_transactions: signedB64,
      });

      toast.success(`Escrow funded! TX: ${submitRes.data.txid.slice(0, 12)}...`);
      return submitRes.data;
    } catch (err: any) {
      const msg = err?.message || 'Fund transaction failed';
      setError(msg);
      toast.error(msg);
      throw err;
    }
  }, [activeAddress, getAlgod, signTxns]);

  // ── Release ───────────────────────────────────────────────────────────────

  const signAndSubmitReleaseTxn = useCallback(async (escrowId: string) => {
    if (!activeAddress) throw new Error('No wallet connected');
    setError(null);

    try {
      // 1. Get release components (incl. merkle_root ABI-encoded args)
      const { data: buildRes } = await api.get(
        `/v1/escrow/${escrowId}/build-release-txn?sender_address=${activeAddress}`
      );
      const d = buildRes.data;

      // 2. Get suggested params
      const algod = getAlgod();
      const sp = await algod.getTransactionParams().do();
      // Extra fee for inner payment txn
      const extraFee = BigInt(d.extra_fee || 2000);
      sp.fee = sp.fee > extraFee ? sp.fee : extraFee;
      sp.flatFee = true;

      // 3. Build atomic group: [MBR top-up, AppCallTxn(release)]
      //    The contract needs enough balance for the inner payment + MBR.
      const MBR = 100_000;
      const mbrTxn = algosdk.makePaymentTxnWithSuggestedParamsFromObject({
        sender: activeAddress,
        receiver: algosdk.getApplicationAddress(d.app_id),
        amount: MBR,
        suggestedParams: sp,
      });

      const txn = algosdk.makeApplicationCallTxnFromObject({
        sender: activeAddress,
        appIndex: d.app_id,
        onComplete: algosdk.OnApplicationComplete.NoOpOC,
        appArgs: d.app_args_b64.map(b64ToBytes),
        suggestedParams: sp,
      });

      algosdk.assignGroupID([mbrTxn, txn]);

      // 4. Sign and submit
      const signedB64 = await signTxns([mbrTxn, txn]);

      const { data: submitRes } = await api.post(`/v1/escrow/${escrowId}/submit-signed-release`, {
        signed_transactions: signedB64,
      });

      toast.success(`Escrow released! TX: ${submitRes.data.txid.slice(0, 12)}...`);
      return submitRes.data;
    } catch (err: any) {
      const msg = err?.message || 'Release transaction failed';
      setError(msg);
      toast.error(msg);
      throw err;
    }
  }, [activeAddress, getAlgod, signTxns]);

  // ── Refund ────────────────────────────────────────────────────────────────

  const signAndSubmitRefundTxn = useCallback(async (escrowId: string, reason: string) => {
    if (!activeAddress) throw new Error('No wallet connected');
    setError(null);

    try {
      // 1. Get refund components
      const query = new URLSearchParams({ sender_address: activeAddress, reason });
      const { data: buildRes } = await api.get(`/v1/escrow/${escrowId}/build-refund-txn?${query}`);
      const d = buildRes.data;

      // 2. Get suggested params
      const algod = getAlgod();
      const sp = await algod.getTransactionParams().do();
      const extraFee = BigInt(d.extra_fee || 2000);
      sp.fee = sp.fee > extraFee ? sp.fee : extraFee;
      sp.flatFee = true;

      // 3. Build atomic group: [MBR top-up, AppCallTxn(refund)]
      const MBR = 100_000;
      const mbrTxn = algosdk.makePaymentTxnWithSuggestedParamsFromObject({
        sender: activeAddress,
        receiver: algosdk.getApplicationAddress(d.app_id),
        amount: MBR,
        suggestedParams: sp,
      });

      const txn = algosdk.makeApplicationCallTxnFromObject({
        sender: activeAddress,
        appIndex: d.app_id,
        onComplete: algosdk.OnApplicationComplete.NoOpOC,
        appArgs: d.app_args_b64.map(b64ToBytes),
        suggestedParams: sp,
      });

      algosdk.assignGroupID([mbrTxn, txn]);

      // 4. Sign and submit
      const signedB64 = await signTxns([mbrTxn, txn]);

      const { data: submitRes } = await api.post(`/v1/escrow/${escrowId}/submit-signed-refund`, {
        signed_transactions: signedB64,
      });

      toast.success(`Escrow refunded! TX: ${submitRes.data.txid.slice(0, 12)}...`);
      return submitRes.data;
    } catch (err: any) {
      const msg = err?.message || 'Refund transaction failed';
      setError(msg);
      toast.error(msg);
      throw err;
    }
  }, [activeAddress, getAlgod, signTxns]);

  return (
    <CadenciaWalletContext.Provider value={{
      activeAddress,
      wallets,
      isWalletConnected,
      isReady,
      isConnecting,
      connectWallet,
      disconnectWallet,
      isLinked,
      linkedAddress,
      balance,
      isLoadingBalance,
      linkStatus,
      error,
      linkWallet,
      unlinkWallet,
      refreshBalance,
      signAndSubmitFundTxn,
      signAndSubmitDeployTxn,
      signAndSubmitReleaseTxn,
      signAndSubmitRefundTxn,
    }}>
      {children}
    </CadenciaWalletContext.Provider>
  );
}

/**
 * Fallback provider when WalletManager hasn't loaded yet.
 * Provides noop functions so the app renders without crashing.
 */
function WalletDisabledProvider({ children }: { children: React.ReactNode }) {
  const { enterprise } = useAuth();
  const isLinked = !!enterprise?.algorand_wallet;
  const linkedAddress = enterprise?.algorand_wallet ?? null;

  const noop = async () => {};
  const noopFund = async () => { throw new Error('Wallet not ready'); };

  return (
    <CadenciaWalletContext.Provider value={{
      activeAddress: null,
      wallets: [],
      isWalletConnected: false,
      isReady: false,
      isConnecting: false,
      connectWallet: noop,
      disconnectWallet: noop,
      isLinked,
      linkedAddress,
      balance: null,
      isLoadingBalance: false,
      linkStatus: 'idle',
      error: null,
      linkWallet: noop,
      unlinkWallet: noop,
      refreshBalance: noop,
      signAndSubmitFundTxn: noopFund,
      signAndSubmitDeployTxn: noopFund as any,
      signAndSubmitReleaseTxn: noopFund as any,
      signAndSubmitRefundTxn: noopFund as any,
    }}>
      {children}
    </CadenciaWalletContext.Provider>
  );
}

export function CadenciaWalletProvider({ children }: { children: React.ReactNode }) {
  const walletReady = useWalletReady();

  if (!walletReady) {
    return <WalletDisabledProvider>{children}</WalletDisabledProvider>;
  }

  return <WalletEnabledProvider>{children}</WalletEnabledProvider>;
}

export function useWalletContext() {
  const ctx = useContext(CadenciaWalletContext);
  if (!ctx) throw new Error('useWalletContext must be used inside CadenciaWalletProvider');
  return ctx;
}

// Backward-compatible alias
export const useWallet_legacy = useWalletContext;

