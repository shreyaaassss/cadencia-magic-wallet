// Empty string → relative URLs → proxied by Next.js rewrites → no CORS.
// Set NEXT_PUBLIC_API_URL=http://localhost:8000 only to bypass the proxy (dev/debug).
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? '';


export const ROUTES = {
  LOGIN: '/login',
  REGISTER: '/register',
  DASHBOARD: '/dashboard',
  SETTINGS: '/settings',
  WALLET: '/settings/wallet',
  PAYMENT_HISTORY: '/settings/payments',
  MARKETPLACE: '/marketplace',
  SELLER_PROFILE: '/marketplace/profile',
  NEGOTIATIONS: '/negotiations',
  ESCROW: '/escrow',
  TREASURY: '/treasury',
  COMPLIANCE: '/compliance',
  ADMIN: '/admin',
} as const;
