import type { NextConfig } from "next";

// Hard error: MSW must never be active in production builds
if (process.env.NODE_ENV === 'production' && process.env.NEXT_PUBLIC_ENABLE_MOCKS === 'true') {
  throw new Error(
    'NEXT_PUBLIC_ENABLE_MOCKS must not be true in production builds. Remove it from your env.'
  );
}

// Internal backend URL — used server-side by Next.js proxy rewrites.
// In Docker: http://backend:8000 (Docker internal network, baked at build time).
// Local dev outside Docker: set NEXT_INTERNAL_BACKEND_URL=http://localhost:8000
const BACKEND_INTERNAL_URL =
  process.env.NEXT_INTERNAL_BACKEND_URL ?? 'http://backend:8000';

const nextConfig: NextConfig = {
  output: 'standalone',

  // Force webpack to use the CJS builds of Magic SDK packages.
  // The ESM builds (dist/es/*.mjs) of @magic-sdk/* reference 'Wallets' and
  // 'Events' from @magic-sdk/types that only exist in the CJS build of
  // @magic-sdk/types@24.22.x. Aliasing to CJS entry points fixes the build.
  webpack(config) {
    const path = require('path');
    const nm = path.resolve(__dirname, 'node_modules');

    config.resolve.alias = {
      ...config.resolve.alias,
      'magic-sdk': path.join(nm, 'magic-sdk/dist/cjs/index.js'),
      '@magic-sdk/provider': path.join(nm, '@magic-sdk/provider/dist/cjs/index.js'),
      '@magic-sdk/commons': path.join(nm, '@magic-sdk/commons/dist/cjs/index.js'),
      '@magic-sdk/types': path.join(nm, '@magic-sdk/types/dist/cjs/index.js'),
      '@magic-ext/algorand': path.join(nm, '@magic-ext/algorand/dist/cjs/index.js'),
    };

    // Stub out optional @txnlab/use-wallet peer dependencies we don't use
    // (Web3Auth, viem/account-abstraction etc. pull in massive Ethereum bundles)
    config.resolve.fallback = {
      ...config.resolve.fallback,
      'viem/account-abstraction': false,
    };

    // Ignore missing optional modules from @txnlab/use-wallet
    config.plugins.push(
      new (require('webpack')).IgnorePlugin({
        resourceRegExp: /^(@web3auth\/modal|@web3auth\/no-modal|@toruslabs\/ethereum-controllers|viem\/account-abstraction)$/,
      })
    );

    return config;
  },

  // Turbopack config (Next.js 16 default bundler).
  // Empty object silences the "webpack config present but no turbopack config" error.
  turbopack: {},

  // Proxy all /v1/* API requests through Next.js to avoid CORS.
  // Browser → localhost:3000/v1/... → (Next.js rewrites) → backend:8000/v1/...
  async rewrites() {
    return [
      {
        source: '/v1/:path*',
        destination: `${BACKEND_INTERNAL_URL}/v1/:path*`,
      },
      {
        source: '/health',
        destination: `${BACKEND_INTERNAL_URL}/health`,
      },
    ];
  },
};

export default nextConfig;
