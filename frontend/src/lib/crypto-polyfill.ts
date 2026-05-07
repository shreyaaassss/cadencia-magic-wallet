/**
 * Minimal crypto.subtle polyfill for non-HTTPS (HTTP) deployments.
 *
 * Problem: WalletConnect v2 relay-client calls window.crypto.subtle.importKey
 * at session setup time. On HTTP, window.crypto.subtle is undefined (browsers
 * restrict SubtleCrypto to secure contexts), causing:
 *   TypeError: Cannot read properties of undefined (reading 'importKey')
 *
 * Fix: Patch window.crypto.subtle with a pure-JS AES-256-GCM implementation
 * backed by @noble/ciphers (already bundled transitively via @walletconnect/utils).
 * On HTTPS, window.crypto.subtle is already defined so this is a no-op.
 *
 * Only AES-GCM importKey/generateKey/encrypt/decrypt are implemented — the
 * exact operations WalletConnect v2 uses for relay message encryption.
 */

type PolyfillKey = {
  _raw: Uint8Array;
  type: 'secret';
  extractable: boolean;
  algorithm: object;
  usages: KeyUsage[];
};

function toBytes(src: BufferSource): Uint8Array {
  if (src instanceof Uint8Array) return src;
  if (ArrayBuffer.isView(src))
    return new Uint8Array(src.buffer, src.byteOffset, src.byteLength);
  return new Uint8Array(src as ArrayBuffer);
}

function toArrayBuffer(u8: Uint8Array): ArrayBuffer {
  return u8.buffer.slice(u8.byteOffset, u8.byteOffset + u8.byteLength) as ArrayBuffer;
}

const subtlePolyfill: SubtleCrypto = {
  async importKey(
    _format: string,
    keyData: BufferSource | JsonWebKey,
    _algorithm: AlgorithmIdentifier | RsaHashedImportParams | EcKeyImportParams | HmacImportParams | AesKeyAlgorithm,
    extractable: boolean,
    keyUsages: KeyUsage[]
  ): Promise<CryptoKey> {
    const raw = toBytes(keyData as BufferSource);
    return { _raw: raw, type: 'secret', extractable, algorithm: _algorithm as object, usages: keyUsages } as unknown as CryptoKey;
  },

  async generateKey(
    algorithm: AlgorithmIdentifier | RsaHashedKeyGenParams | EcKeyGenParams | AesKeyGenParams | HmacKeyGenParams,
    extractable: boolean,
    keyUsages: KeyUsage[]
  ): Promise<CryptoKey | CryptoKeyPair> {
    const len = (algorithm as AesKeyGenParams).length ?? 256;
    const raw = new Uint8Array(len / 8);
    globalThis.crypto.getRandomValues(raw); // getRandomValues works on HTTP
    return { _raw: raw, type: 'secret', extractable, algorithm, usages: keyUsages } as unknown as CryptoKey;
  },

  async exportKey(_format: KeyFormat, key: CryptoKey): Promise<ArrayBuffer | JsonWebKey> {
    return toArrayBuffer((key as unknown as PolyfillKey)._raw);
  },

  async encrypt(
    algorithm: AlgorithmIdentifier | RsaOaepParams | AesCtrParams | AesCbcParams | AesGcmParams,
    key: CryptoKey,
    data: BufferSource
  ): Promise<ArrayBuffer> {
    const { gcm } = await import('@noble/ciphers/aes');
    const params = algorithm as AesGcmParams;
    const iv = toBytes(params.iv as BufferSource);
    const aad = params.additionalData ? toBytes(params.additionalData as BufferSource) : undefined;
    const result = gcm((key as unknown as PolyfillKey)._raw, iv, aad).encrypt(toBytes(data));
    return toArrayBuffer(result);
  },

  async decrypt(
    algorithm: AlgorithmIdentifier | RsaOaepParams | AesCtrParams | AesCbcParams | AesGcmParams,
    key: CryptoKey,
    data: BufferSource
  ): Promise<ArrayBuffer> {
    const { gcm } = await import('@noble/ciphers/aes');
    const params = algorithm as AesGcmParams;
    const iv = toBytes(params.iv as BufferSource);
    const aad = params.additionalData ? toBytes(params.additionalData as BufferSource) : undefined;
    const result = gcm((key as unknown as PolyfillKey)._raw, iv, aad).decrypt(toBytes(data));
    return toArrayBuffer(result);
  },

  async digest(algorithm: AlgorithmIdentifier, data: BufferSource): Promise<ArrayBuffer> {
    const { sha256 } = await import('@noble/hashes/sha256');
    return toArrayBuffer(sha256(toBytes(data)));
  },

  // Stubs for unused SubtleCrypto methods
  async sign(): Promise<ArrayBuffer> { throw new Error('sign not implemented in HTTP polyfill'); },
  async verify(): Promise<boolean> { throw new Error('verify not implemented in HTTP polyfill'); },
  async deriveKey(): Promise<CryptoKey> { throw new Error('deriveKey not implemented in HTTP polyfill'); },
  async deriveBits(): Promise<ArrayBuffer> { throw new Error('deriveBits not implemented in HTTP polyfill'); },
  async wrapKey(): Promise<ArrayBuffer> { throw new Error('wrapKey not implemented in HTTP polyfill'); },
  async unwrapKey(): Promise<CryptoKey> { throw new Error('unwrapKey not implemented in HTTP polyfill'); },
} as unknown as SubtleCrypto;

/**
 * Installs the crypto.subtle polyfill if the browser is in a non-secure
 * context (HTTP) where crypto.subtle is undefined.
 * Safe to call multiple times — no-ops if already installed.
 */
export function installCryptoPolyfillIfNeeded(): void {
  if (typeof window === 'undefined') return;
  if (window.crypto?.subtle) return; // HTTPS / localhost — no polyfill needed

  const target = window.crypto as unknown as Record<string, unknown>;

  // Strategy 1: own property via defineProperty
  try {
    Object.defineProperty(target, 'subtle', {
      configurable: true,
      enumerable: true,
      value: subtlePolyfill,
    });
    if (window.crypto.subtle) {
      console.info('[cadencia] crypto.subtle polyfill installed (HTTP context)');
      return;
    }
  } catch { /* try next */ }

  // Strategy 2: direct assignment
  try {
    target['subtle'] = subtlePolyfill;
    if (window.crypto.subtle) {
      console.info('[cadencia] crypto.subtle polyfill installed via assignment (HTTP context)');
      return;
    }
  } catch { /* try next */ }

  // Strategy 3: patch via prototype
  try {
    Object.defineProperty(Object.getPrototypeOf(target), 'subtle', {
      configurable: true,
      enumerable: true,
      value: subtlePolyfill,
    });
    if (window.crypto.subtle) {
      console.info('[cadencia] crypto.subtle polyfill installed via prototype (HTTP context)');
      return;
    }
  } catch { /* non-fatal */ }

  console.warn('[cadencia] crypto.subtle polyfill could not be installed — wallet may fail on HTTP');
}
