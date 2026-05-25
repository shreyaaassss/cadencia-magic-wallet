"""
Wallet challenge-response verifier for Pera Wallet integration.

context.md §14: Wallet ownership verified via challenge-response.
context.md §12 SRS-SC-001: backend NEVER stores private keys.

Flow:
1. Backend generates random nonce → stores in Redis with 5-min TTL
2. Frontend signs nonce with wallet private key via Pera Wallet
3. Backend verifies signature using algosdk.encoding.verify_bytes()

Security:
- Challenge nonces expire after 5 minutes (Redis TTL)
- Wallet address validated against Algorand checksum before linking
- All wallet operations logged to structured audit trail
"""

from __future__ import annotations

import base64
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import algosdk
from algosdk import encoding

from src.shared.infrastructure.logging import get_logger

log = get_logger(__name__)

_CHALLENGE_TTL = 300  # 5 minutes
_CHALLENGE_PREFIX = "wallet_challenge:"


@dataclass(frozen=True)
class WalletChallenge:
    """Issued challenge for wallet ownership verification."""

    challenge_id: str
    nonce: str
    message_to_sign: str
    expires_at: datetime


class WalletVerifier:
    """
    Cryptographic wallet ownership verification using Algorand signatures.

    Uses Redis for challenge storage with automatic TTL expiration.
    Backend NEVER handles or stores private keys (context.md §12).
    """

    def __init__(self, redis: object) -> None:
        """
        Args:
            redis: Redis async client for challenge storage.
        """
        self._redis = redis

    async def create_open_challenge(self) -> WalletChallenge:
        """
        Generate a wallet ownership challenge without requiring an enterprise_id.
        Used for pre-auth Web3 login/register where the user isn't logged in yet.
        """
        challenge_id = f"wc-{uuid.uuid4().hex[:16]}"
        nonce = secrets.token_hex(32)
        message = f"Cadencia wallet verification: {nonce}"
        expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=_CHALLENGE_TTL)

        redis_key = f"{_CHALLENGE_PREFIX}{challenge_id}"
        await self._redis.setex(
            redis_key,
            _CHALLENGE_TTL,
            f"{nonce}|__open__",
        )

        log.info(
            "wallet_open_challenge_created",
            challenge_id=challenge_id,
            expires_at=expires_at.isoformat(),
        )

        return WalletChallenge(
            challenge_id=challenge_id,
            nonce=nonce,
            message_to_sign=message,
            expires_at=expires_at,
        )

    async def verify_open_challenge(
        self,
        challenge_id: str,
        algorand_address: str,
        signed_txn_b64: str,
    ) -> bool:
        """
        Verify wallet ownership for a pre-auth open challenge.
        Accepts a signed zero-value transaction (like verify_challenge_txn but
        without enterprise_id scoping).
        """
        if not self._is_valid_algorand_address(algorand_address):
            return False

        try:
            stxn = encoding.msgpack_decode(signed_txn_b64)
            txn = stxn.transaction
        except Exception as exc:
            log.warning("web3_verify_decode_error", error=str(exc))
            return False

        if txn.sender != algorand_address:
            return False

        note_bytes = getattr(txn, "note", None)
        if not note_bytes:
            return False

        note_str = note_bytes.decode("utf-8") if isinstance(note_bytes, bytes) else str(note_bytes)
        prefix = "Cadencia wallet verification: "
        if not note_str.startswith(prefix):
            return False

        nonce_from_txn = note_str[len(prefix):]

        redis_key = f"{_CHALLENGE_PREFIX}{challenge_id}"
        stored = await self._redis.get(redis_key)
        if stored is None:
            return False

        stored_str = stored.decode() if isinstance(stored, bytes) else stored
        parts = stored_str.split("|", 1)
        if len(parts) != 2 or parts[0] != nonce_from_txn:
            return False

        # Verify Ed25519 signature
        try:
            from nacl.signing import VerifyKey
            from nacl.exceptions import BadSignatureError

            pk_bytes = encoding.decode_address(algorand_address)
            verify_key = VerifyKey(pk_bytes)
            txn_b64 = encoding.msgpack_encode(txn)
            txn_raw = base64.b64decode(txn_b64)
            message = b"TX" + txn_raw
            sig_bytes = (
                base64.b64decode(stxn.signature)
                if isinstance(stxn.signature, str)
                else stxn.signature
            )
            verify_key.verify(message, sig_bytes)
        except Exception:
            log.warning("web3_verify_signature_invalid", address=algorand_address[:8])
            return False

        await self._redis.delete(redis_key)
        log.info("web3_ownership_verified", address=algorand_address[:8])
        return True

    async def create_challenge(self, enterprise_id: uuid.UUID) -> WalletChallenge:
        """
        Generate a new wallet ownership challenge.

        Creates a random nonce and stores it in Redis with 5-minute TTL.
        The frontend should prompt the user to sign the message via Pera Wallet.
        """
        challenge_id = f"wc-{uuid.uuid4().hex[:16]}"
        nonce = secrets.token_hex(32)
        message = f"Cadencia wallet verification: {nonce}"
        expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=_CHALLENGE_TTL)

        # Store in Redis
        redis_key = f"{_CHALLENGE_PREFIX}{challenge_id}"
        await self._redis.setex(
            redis_key,
            _CHALLENGE_TTL,
            f"{nonce}|{enterprise_id}",
        )

        log.info(
            "wallet_challenge_created",
            challenge_id=challenge_id,
            enterprise_id=str(enterprise_id),
            expires_at=expires_at.isoformat(),
        )

        return WalletChallenge(
            challenge_id=challenge_id,
            nonce=nonce,
            message_to_sign=message,
            expires_at=expires_at,
        )

    async def verify_challenge(
        self,
        challenge_id: str,
        algorand_address: str,
        signature_b64: str,
    ) -> bool:
        """
        Verify that the wallet owner signed the challenge nonce (raw bytes).

        Legacy method — kept for enterprise-scoped endpoint compatibility.
        """
        if not self._is_valid_algorand_address(algorand_address):
            log.warning(
                "wallet_verify_invalid_address",
                challenge_id=challenge_id,
                address=algorand_address[:8] + "...",
            )
            return False

        redis_key = f"{_CHALLENGE_PREFIX}{challenge_id}"
        stored = await self._redis.get(redis_key)
        if stored is None:
            log.warning(
                "wallet_verify_challenge_expired_or_missing",
                challenge_id=challenge_id,
            )
            return False

        stored_str = stored.decode() if isinstance(stored, bytes) else stored
        parts = stored_str.split("|", 1)
        if len(parts) != 2:
            return False
        nonce, _ = parts

        message = f"Cadencia wallet verification: {nonce}"
        message_bytes = message.encode("utf-8")

        try:
            signature_bytes = base64.b64decode(signature_b64)
            is_valid = encoding.verify_bytes(
                message_bytes, signature_bytes, algorand_address
            )
        except Exception as exc:
            log.warning(
                "wallet_verify_signature_error",
                challenge_id=challenge_id,
                error=str(exc),
            )
            return False

        await self._redis.delete(redis_key)

        if is_valid:
            log.info(
                "wallet_ownership_verified",
                challenge_id=challenge_id,
                address=algorand_address[:8] + "...",
            )
        else:
            log.warning(
                "wallet_verify_signature_invalid",
                challenge_id=challenge_id,
                address=algorand_address[:8] + "...",
            )

        return is_valid

    async def verify_challenge_txn(
        self,
        enterprise_id: uuid.UUID,
        algorand_address: str,
        signed_txn_b64: str,
    ) -> bool:
        """
        Verify wallet ownership via a signed zero-value transaction.

        The frontend builds a self-payment (amount=0) transaction with the
        challenge message in the note field, signs it with the wallet, and
        sends the signed txn here. We decode it, check the note matches an
        active challenge, and verify the Ed25519 signature.

        Works with any Algorand wallet (Pera, Defly, etc.) since all wallets
        support transaction signing.
        """
        if not self._is_valid_algorand_address(algorand_address):
            log.warning(
                "wallet_verify_txn_invalid_address",
                address=algorand_address[:8] + "...",
            )
            return False

        try:
            # 1. Decode the signed transaction.
            #    py-algorand-sdk v2.x msgpack_decode expects a base64 string,
            #    NOT raw bytes. The frontend sends base64-encoded signed txn,
            #    so pass it directly — do NOT base64-decode first.
            stxn = encoding.msgpack_decode(signed_txn_b64)
            txn = stxn.transaction
        except Exception as exc:
            log.warning("wallet_verify_txn_decode_error", error=str(exc))
            return False

        # 2. Verify sender matches claimed address
        if txn.sender != algorand_address:
            log.warning(
                "wallet_verify_txn_sender_mismatch",
                claimed=algorand_address[:8] + "...",
                actual=txn.sender[:8] + "...",
            )
            return False

        # 3. Verify it's a zero-amount self-payment (safety)
        if getattr(txn, "amt", None) and txn.amt != 0:
            log.warning("wallet_verify_txn_nonzero_amount")
            return False

        # 4. Extract the note and find the matching challenge
        note_bytes = getattr(txn, "note", None)
        if not note_bytes:
            log.warning("wallet_verify_txn_missing_note")
            return False

        note_str = note_bytes.decode("utf-8") if isinstance(note_bytes, bytes) else str(note_bytes)

        # Note format: "Cadencia wallet verification: {nonce}"
        prefix = "Cadencia wallet verification: "
        if not note_str.startswith(prefix):
            log.warning("wallet_verify_txn_invalid_note_format")
            return False

        nonce_from_txn = note_str[len(prefix):]

        # 5. Find the challenge in Redis matching this nonce + enterprise
        challenge_id = None
        try:
            async for key in self._redis.scan_iter(match=f"{_CHALLENGE_PREFIX}*"):
                stored = await self._redis.get(key)
                if stored:
                    stored_str = stored.decode() if isinstance(stored, bytes) else stored
                    parts = stored_str.split("|", 1)
                    if len(parts) == 2:
                        stored_nonce, stored_eid = parts
                        if stored_nonce == nonce_from_txn and stored_eid == str(enterprise_id):
                            key_str = key.decode() if isinstance(key, bytes) else key
                            challenge_id = key_str.replace(_CHALLENGE_PREFIX, "")
                            break
        except Exception as exc:
            log.warning("wallet_verify_txn_redis_scan_error", error=str(exc))
            return False

        if challenge_id is None:
            log.warning("wallet_verify_txn_challenge_not_found", nonce=nonce_from_txn[:8])
            return False

        # 6. Verify the transaction signature using nacl directly.
        #    Algorand transaction signing uses the "TX" prefix: sign(b"TX" + msgpack(txn)).
        #    algosdk.util.verify_bytes uses "MX" prefix (for arbitrary bytes), so we
        #    must use nacl VerifyKey directly for transaction signatures.
        try:
            from nacl.signing import VerifyKey
            from nacl.exceptions import BadSignatureError

            pk_bytes = encoding.decode_address(algorand_address)
            verify_key = VerifyKey(pk_bytes)
            # msgpack_encode returns a base64 string in py-algorand-sdk v2.x;
            # we need raw bytes for the "TX" prefix used by Algorand signing.
            txn_b64 = encoding.msgpack_encode(txn)
            txn_raw = base64.b64decode(txn_b64)
            message = b"TX" + txn_raw
            sig_bytes = (
                base64.b64decode(stxn.signature)
                if isinstance(stxn.signature, str)
                else stxn.signature
            )
            verify_key.verify(message, sig_bytes)
            is_valid = True
        except (BadSignatureError, ValueError, TypeError):
            is_valid = False
        except Exception as exc:
            log.warning("wallet_verify_txn_signature_error", error=str(exc))
            is_valid = False

        # 7. Delete challenge (one-time use)
        if is_valid:
            redis_key = f"{_CHALLENGE_PREFIX}{challenge_id}"
            await self._redis.delete(redis_key)
            log.info(
                "wallet_ownership_verified_txn",
                challenge_id=challenge_id,
                address=algorand_address[:8] + "...",
            )
        else:
            log.warning(
                "wallet_verify_txn_signature_invalid",
                address=algorand_address[:8] + "...",
            )

        return is_valid

    @staticmethod
    def _is_valid_algorand_address(address: str) -> bool:
        """Validate Algorand address format and checksum."""
        try:
            algosdk.encoding.decode_address(address)
            return True
        except Exception:
            return False
