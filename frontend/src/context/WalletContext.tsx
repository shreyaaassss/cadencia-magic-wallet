'use client';

/**
 * Cadencia Wallet Context — supports both Magic (Web2) and external wallets (Web3).
 *
 * When authMethod === 'magic': signing via Magic SDK (embedded wallet)
 * When authMethod === 'web3': signing via @txnlab/use-wallet-react (Pera/Defly/Lute)
 */

import React, { createContext, useContext, useState, useCallback } from 'react';
import { toast } from 'sonner';
import algosdk from 'algosdk';
import { api } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';
import { magic, signAlgoTxn, signAlgoTxnGroup } from '@/lib/magic';
import { useWallet as _useTxnLabWallet } from '@txnlab/use-wallet-react';

// Safe wrapper — returns empty defaults if WalletProvider isn't mounted yet (SSR)
function useTxnLabWalletSafe() {
  try {
    return _useTxnLabWallet();
  } catch {
    return {
      activeAddress: null,
      wallets: [],
      signTransactions: async () => [] as any,
      activeWallet: null,
    } as any;
  }
}
import type { WalletBalance } from '@/types';

interface CadenciaWalletContextValue {
  activeAddress: string | null;
  wallets: any[];
  isWalletConnected: boolean;
  isReady: boolean;
  isConnecting: boolean;
  connectWallet: (walletId: string) => Promise<void>;
  disconnectWallet: () => Promise<void>;
  isLinked: boolean;
  linkedAddress: string | null;
  balance: WalletBalance | null;
  isLoadingBalance: boolean;
  linkStatus: 'idle' | 'signing' | 'submitting' | 'error';
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

/** Decode base64 string to Uint8Array */
const b64ToBytes = (b64: string) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));

export function CadenciaWalletProvider({ children }: { children: React.ReactNode }) {
  const { enterprise, walletAddress: magicAddress, authMethod } = useAuth();
  const txnLab = useTxnLabWalletSafe();

  const [balance, setBalance] = useState<WalletBalance | null>(null);
  const [isLoadingBalance, setIsLoadingBalance] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Active address depends on auth method
  const activeAddress = authMethod === 'web3'
    ? (txnLab.activeAddress ?? magicAddress ?? null)
    : (magicAddress ?? null);

  const isWalletConnected = !!activeAddress;
  const isLinked = !!enterprise?.algorand_wallet;
  const linkedAddress = enterprise?.algorand_wallet ?? null;

  const getAlgod = useCallback(() => {
    const server = process.env.NEXT_PUBLIC_ALGOD_SERVER || 'https://testnet-api.4160.nodely.dev';
    const port = process.env.NEXT_PUBLIC_ALGOD_PORT || '';
    const token = process.env.NEXT_PUBLIC_ALGOD_TOKEN || '';
    return new algosdk.Algodv2(token, server, port);
  }, []);

  /**
   * Sign transactions — delegates to Magic or external wallet based on authMethod.
   */
  const signTxns = useCallback(async (txns: algosdk.Transaction[]): Promise<string[]> => {
    if (authMethod === 'web3') {
      // Use @txnlab/use-wallet-react for external wallets
      const encoded = txns.map(t => algosdk.encodeUnsignedTransaction(t));
      try {
        const signed = await txnLab.signTransactions(encoded);
        // signTransactions returns (Uint8Array | null)[] — convert to base64
        return signed.map((s: any, i: number) => {
          if (!s) throw new Error(`Wallet did not sign transaction ${i}`);
          if (s instanceof Uint8Array) {
            return Buffer.from(s).toString('base64');
          }
          return typeof s === 'string' ? s : Buffer.from(s as any).toString('base64');
        });
      } catch (err: any) {
        // Pera error 4100: another transaction request is already pending
        if (err?.message?.includes('4100') || err?.message?.toLowerCase().includes('pending')) {
          throw new Error(
            'Your Pera Wallet has a pending transaction. Open the Pera app, cancel any pending request, then try again.'
          );
        }
        throw err;
      }
    }

    // Magic signing
    if (txns.length === 1) {
      const encodedB64 = Buffer.from(algosdk.encodeUnsignedTransaction(txns[0])).toString('base64');
      return [await signAlgoTxn(encodedB64)];
    }
    const encodedGroup = txns.map(t =>
      Buffer.from(algosdk.encodeUnsignedTransaction(t)).toString('base64')
    );
    return signAlgoTxnGroup(encodedGroup);
  }, [authMethod, txnLab]);

  const connectWallet = useCallback(async (_walletId: string) => {
    if (authMethod === 'web3') {
      toast.info('Use the login page to connect your wallet');
    } else {
      toast.info('Wallet is managed automatically via Magic — no connection needed');
    }
  }, [authMethod]);

  const disconnectWallet = useCallback(async () => {
    if (authMethod === 'web3') {
      toast.info('Use logout to disconnect your wallet');
    } else {
      toast.info('Wallet is managed by Magic — use logout to end your session');
    }
  }, [authMethod]);

  const linkWallet = useCallback(async () => {
    if (!activeAddress) {
      toast.error('No wallet address available — please log in again');
      return;
    }
    try {
      if (enterprise?.id) {
        await api.post(`/v1/enterprises/${enterprise.id}/wallet/link`, {
          algorand_address: activeAddress,
          magic_address: authMethod === 'magic',
        });
        toast.success('Wallet linked successfully');
      }
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || 'Failed to link wallet';
      setError(msg);
      toast.error(msg);
    }
  }, [activeAddress, enterprise, authMethod]);

  const unlinkWallet = useCallback(async () => {
    try {
      if (enterprise?.id) {
        await api.delete(`/v1/enterprises/${enterprise.id}/wallet`);
        toast.success('Wallet unlinked');
      }
    } catch {
      toast.error('Failed to unlink wallet');
    }
  }, [enterprise]);

  const refreshBalance = useCallback(async () => {
    if (!isLinked || !enterprise?.id) return;
    setIsLoadingBalance(true);
    try {
      const { data } = await api.get(`/v1/enterprises/${enterprise.id}/wallet/balance`);
      setBalance(data.data);
    } catch {
      toast.error('Failed to fetch wallet balance');
    } finally {
      setIsLoadingBalance(false);
    }
  }, [isLinked, enterprise]);

  // ── Deploy ─────────────────────────────────────────────────────────────────

  const signAndSubmitDeployTxn = useCallback(async (
    sessionId: string,
    params: { buyerAddress: string; sellerAddress: string; amountMicroAlgo: number },
  ) => {
    if (!activeAddress) throw new Error('No wallet available — please log in');
    setError(null);

    try {
      const query = new URLSearchParams({
        deployer_address: activeAddress,
        buyer_address: params.buyerAddress,
        seller_address: params.sellerAddress,
        amount_microalgo: String(params.amountMicroAlgo),
      });
      const { data: buildRes } = await api.get(`/v1/escrow/${sessionId}/build-deploy-txn?${query}`);
      const d = buildRes.data;

      const algod = getAlgod();
      const sp = await algod.getTransactionParams().do();

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

      const signedB64 = await signTxns([txn]);

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

  // ── Fund ───────────────────────────────────────────────────────────────────

  const signAndSubmitFundTxn = useCallback(async (escrowId: string) => {
    if (!activeAddress) throw new Error('No wallet available — please log in');
    setError(null);

    try {
      const { data: buildRes } = await api.get(`/v1/escrow/${escrowId}/build-fund-txn`);
      const d = buildRes.data;

      let signedB64: string[];

      if (d.encoded_group_b64 && d.encoded_group_b64.length === 2 && authMethod === 'magic') {
        // Fast path for Magic: backend returned pre-encoded txns
        signedB64 = await signAlgoTxnGroup(d.encoded_group_b64);
      } else {
        // Build locally (needed for external wallets + fallback)
        const algod = getAlgod();
        const sp = await algod.getTransactionParams().do();
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
        signedB64 = await signTxns([payTxn, callTxn]);
      }

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
  }, [activeAddress, getAlgod, signTxns, authMethod]);

  // ── Release ────────────────────────────────────────────────────────────────

  const signAndSubmitReleaseTxn = useCallback(async (escrowId: string) => {
    if (!activeAddress) throw new Error('No wallet available — please log in');
    setError(null);

    try {
      const { data: buildRes } = await api.get(
        `/v1/escrow/${escrowId}/build-release-txn?sender_address=${activeAddress}`
      );
      const d = buildRes.data;

      const algod = getAlgod();
      const sp = await algod.getTransactionParams().do();
      const extraFee = BigInt(d.extra_fee || 2000);
      sp.fee = sp.fee > extraFee ? sp.fee : extraFee;
      sp.flatFee = true;

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

  // ── Refund ─────────────────────────────────────────────────────────────────

  const signAndSubmitRefundTxn = useCallback(async (escrowId: string, reason: string) => {
    if (!activeAddress) throw new Error('No wallet available — please log in');
    setError(null);

    try {
      const query = new URLSearchParams({ sender_address: activeAddress, reason });
      const { data: buildRes } = await api.get(`/v1/escrow/${escrowId}/build-refund-txn?${query}`);
      const d = buildRes.data;

      const algod = getAlgod();
      const sp = await algod.getTransactionParams().do();
      const extraFee = BigInt(d.extra_fee || 2000);
      sp.fee = sp.fee > extraFee ? sp.fee : extraFee;
      sp.flatFee = true;

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
      wallets: txnLab.wallets ?? [],
      isWalletConnected,
      isReady: authMethod === 'web3' ? !!txnLab.activeAddress : !!magic,
      isConnecting: false,
      connectWallet,
      disconnectWallet,
      isLinked,
      linkedAddress,
      balance,
      isLoadingBalance,
      linkStatus: 'idle',
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

export function useWalletContext() {
  const ctx = useContext(CadenciaWalletContext);
  if (!ctx) throw new Error('useWalletContext must be used inside CadenciaWalletProvider');
  return ctx;
}

export const useWallet_legacy = useWalletContext;
