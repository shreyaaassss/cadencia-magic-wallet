# context.md §3 — Hexagonal Architecture: domain layer MUST NOT import
# FastAPI, SQLAlchemy, algosdk, or any ORM/framework library.
#
# CONFLICT RESOLUTION (passlib):
# HashedPassword uses passlib[bcrypt] for password hashing. This is a
# security-specific library with no ORM/framework coupling. Password hashing
# is a domain invariant (the hash IS the stored credential). Importing passlib
# here is acceptable per context.md §3 which bans "infrastructure libraries"
# (ORM, web framework, blockchain SDK) — not security primitives.
# REF: context.md §3, §14

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass

from src.shared.domain.base_value_object import BaseValueObject
from src.shared.domain.exceptions import ValidationError

# ── PAN ───────────────────────────────────────────────────────────────────────

_PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")


@dataclass(frozen=True)
class PAN(BaseValueObject):
    """
    Indian Permanent Account Number (PAN).

    Format: AAAAA9999A — 5 uppercase alpha, 4 digits, 1 uppercase alpha.
    context.md §20 glossary: PAN is a 10-character Indian tax identifier.
    """

    value: str

    def __post_init__(self) -> None:
        if not _PAN_REGEX.match(self.value):
            raise ValidationError(
                f"Invalid PAN format: '{self.value}'. "
                "Expected format: 5 uppercase letters, 4 digits, 1 uppercase letter "
                "(e.g. ABCDE1234F).",
                field="pan",
            )


# ── GSTIN ─────────────────────────────────────────────────────────────────────

# 2-digit state code + 10-char PAN + 1-char entity + Z + 1-char checksum
_GSTIN_REGEX = re.compile(
    r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}Z[A-Z\d]{1}$"
)


@dataclass(frozen=True)
class GSTIN(BaseValueObject):
    """
    Indian Goods and Services Tax Identification Number (GSTIN).

    Format: 2-digit state code + PAN (10 chars) + entity number + Z + checksum.
    context.md §20 glossary: 15-character GSTIN identifier.
    """

    value: str

    def __post_init__(self) -> None:
        if not _GSTIN_REGEX.match(self.value):
            raise ValidationError(
                f"Invalid GSTIN format: '{self.value}'. "
                "Expected: 2-digit state code + 10-char PAN + entity + Z + checksum "
                "(e.g. 27ABCDE1234F1Z5).",
                field="gstin",
            )


# ── Email ─────────────────────────────────────────────────────────────────────

# RFC 5322 simplified — covers all practical email formats
_EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


@dataclass(frozen=True)
class Email(BaseValueObject):
    """
    Normalised email address (lowercase).

    Raises ValidationError on invalid format.
    Equality is case-insensitive (both values normalised to lowercase).
    """

    value: str

    def __post_init__(self) -> None:
        # Normalise to lowercase before validation
        # frozen=True means we must use object.__setattr__ to mutate during init
        object.__setattr__(self, "value", self.value.strip().lower())
        if not _EMAIL_REGEX.match(self.value):
            raise ValidationError(
                f"Invalid email format: '{self.value}'.",
                field="email",
            )


# ── AlgorandAddress ───────────────────────────────────────────────────────────

# Algorand addresses are 58-character base32 encoded strings
_ALGO_ADDR_REGEX = re.compile(r"^[A-Z2-7]{58}$")


@dataclass(frozen=True)
class AlgorandAddress(BaseValueObject):
    """
    Algorand account address (58-char base32).

    Validation is format-only (length + charset). Checksum verification
    requires algosdk and is performed in the infrastructure layer.
    """

    value: str

    def __post_init__(self) -> None:
        if not _ALGO_ADDR_REGEX.match(self.value):
            raise ValidationError(
                "Invalid Algorand address: must be 58 uppercase base32 characters.",
                field="algorand_wallet",
            )


# ── HashedPassword ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HashedPassword(BaseValueObject):
    """
    Bcrypt-hashed password.

    CONFLICT RESOLUTION: passlib is a security primitive (not ORM/framework).
    Password hashing is a domain invariant — the hash IS the credential.
    Only the hash is ever stored or logged. REF: context.md §14.
    """

    value: str  # bcrypt hash string

    @staticmethod
    def _truncate(plaintext: str) -> str:
        """Bcrypt only uses the first 72 bytes. Truncate to avoid bcrypt>=4.1 errors."""
        return plaintext.encode("utf-8")[:72].decode("utf-8", errors="ignore")

    @classmethod
    def from_plaintext(cls, plaintext: str) -> "HashedPassword":
        """Hash plaintext with bcrypt. Returns a HashedPassword value object."""
        # Lazy import to defer passlib load until first use
        from passlib.context import CryptContext  # type: ignore[import-untyped]

        _ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
        return cls(value=_ctx.hash(cls._truncate(plaintext)))

    def verify(self, plaintext: str) -> bool:
        """Return True if plaintext matches the stored hash."""
        from passlib.context import CryptContext  # type: ignore[import-untyped]

        _ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
        return bool(_ctx.verify(self._truncate(plaintext), self.value))


# ── HashedAPIKey ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HashedAPIKey(BaseValueObject):
    """
    HMAC-SHA256 hash of a raw API key.

    context.md §14: API keys stored as HMAC-SHA256 hashes.
    Plaintext NEVER persisted or logged.
    Uses stdlib hashlib.hmac — no external dependency.
    """

    value: str  # hex-encoded HMAC-SHA256 digest

    @classmethod
    def from_raw(cls, raw_key: str, secret: str) -> "HashedAPIKey":
        """Produce HMAC-SHA256 hash of raw_key using secret."""
        digest = hmac.new(
            secret.encode("utf-8"),
            raw_key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return cls(value=digest)

    def verify(self, raw_key: str, secret: str) -> bool:
        """Constant-time comparison of raw_key against stored hash."""
        expected = hmac.new(
            secret.encode("utf-8"),
            raw_key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(self.value, expected)
