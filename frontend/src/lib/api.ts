import axios from 'axios';
import algosdk from 'algosdk';
import { API_BASE_URL } from './constants';
import { getMagicAddress, signAlgoTxn } from '@/lib/magic';

let _accessToken: string | null = null;

export const setAccessToken = (token: string | null) => {
  _accessToken = token;
};

export const getAccessToken = () => _accessToken;

export const api = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  if (_accessToken) {
    config.headers.Authorization = `Bearer ${_accessToken}`;
  }
  return config;
});

// ── x402 Algorand payment interceptor ──────────────────────────────────────
// Intercepts HTTP 402 with x402 payment requirements, builds + signs an
// Algorand payment via Magic wallet, and retries the request automatically.
api.interceptors.response.use(
  (res) => res,
  async (err) => {
    const original = err.config;
    if (err.response?.status !== 402 || original._x402Retry) {
      return Promise.reject(err);
    }

    // Only handle x402 Algorand payment challenges
    const detail = err.response.data?.detail;
    if (!detail || detail.scheme !== 'algorand-payment') {
      return Promise.reject(err);
    }

    const { amount, recipient, nonce, expires_at } = detail as {
      amount: number; recipient: string; nonce: string; expires_at: number;
    };

    if (Date.now() / 1000 > expires_at) {
      return Promise.reject(new Error('[x402] Payment requirements expired — retry the request'));
    }

    try {
      const senderAddress = await getMagicAddress();
      const nodeUrl =
        process.env.NEXT_PUBLIC_ALGORAND_NODE_URL ?? 'https://testnet-api.algonode.cloud';
      const algodClient = new algosdk.Algodv2('', nodeUrl, '');
      const suggestedParams = await algodClient.getTransactionParams().do();

      const txn = algosdk.makePaymentTxnWithSuggestedParamsFromObject({
        sender: senderAddress,
        receiver: recipient,
        amount,
        note: new TextEncoder().encode(
          JSON.stringify({ nonce, expires_at }),
        ),
        suggestedParams,
      });

      const encodedB64 = Buffer.from(algosdk.encodeUnsignedTransaction(txn)).toString('base64');
      const signedB64 = await signAlgoTxn(encodedB64);

      // Retry original request with payment headers
      original._x402Retry = true;
      original.headers = original.headers || {};
      original.headers['X-PAYMENT'] = signedB64;
      original.headers['X-PAYMENT-NONCE'] = nonce;
      return api(original);
    } catch (payErr: any) {
      return Promise.reject(
        new Error(`[x402] Payment failed: ${payErr.message ?? payErr}`),
      );
    }
  },
);

// ── 401 token refresh interceptor ─────────────────────────────────────────
api.interceptors.response.use(
  (res) => res,
  async (err) => {
    const original = err.config;
    const url = original?.url || '';

    // Don't attempt refresh on auth endpoints (prevents infinite 401 loop)
    const isAuthEndpoint = url.includes('/v1/auth/');
    if (err.response?.status === 401 && !original._retry && !isAuthEndpoint) {
      original._retry = true;
      try {
        const { data } = await api.post('/v1/auth/refresh');
        setAccessToken(data.data.access_token);
        original.headers.Authorization = `Bearer ${data.data.access_token}`;
        return api(original);
      } catch {
        setAccessToken(null);
        // Signal auth expiry to AuthContext — it will clear state and
        // the AuthGuard will handle the redirect via client-side navigation.
        // Never use window.location.href here: it causes a full page reload
        // which re-triggers the refresh cycle and creates an infinite loop.
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new Event('auth:session-expired'));
        }
      }
    }
    return Promise.reject(err);
  }
);
