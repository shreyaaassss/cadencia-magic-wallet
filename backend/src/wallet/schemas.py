"""
Short-form wallet API schemas.

These match the frontend's WalletContext.tsx / WalletBalance TypeScript types exactly.
The existing enterprise-scoped schemas (src/identity/api/schemas.py) have a slightly
different shape (e.g. challenge_id instead of challenge). These are the frontend-facing
schemas; the enterprise-scoped ones remain for direct API usage.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator

# ── Request schemas ────────────────────────────────────────────────────────────


class WalletLinkRequest(BaseModel):
    """POST /v1/wallet/link — body submitted after wallet signs the challenge txn."""

    algorand_address: str = Field(
        ...,
        min_length=58,
        max_length=58,
        description="58-character Algorand wallet address",
    )
    signed_txn: str = Field(
        ...,
        description="Base64-encoded signed zero-value txn containing challenge in note field",
    )

    @field_validator("algorand_address")
    @classmethod
    def validate_algorand_address(cls, v: str) -> str:
        try:
            from algosdk import encoding

            encoding.decode_address(v)
            return v
        except Exception:
            raise ValueError("Invalid Algorand address format")


# ── Response schemas ───────────────────────────────────────────────────────────


class WalletChallengeResponse(BaseModel):
    """GET /v1/wallet/challenge — nonce for wallet ownership verification."""

    challenge: str = Field(description="Unique challenge nonce to sign")
    enterprise_id: str = Field(description="UUID of the enterprise")
    expires_at: str = Field(description="ISO 8601 expiry timestamp (5 min TTL)")


class WalletLinkResponse(BaseModel):
    """POST /v1/wallet/link — success response after signature verification."""

    algorand_address: str
    message: str = "Wallet linked successfully"


class WalletUnlinkResponse(BaseModel):
    """DELETE /v1/wallet/link — confirmation of wallet removal."""

    message: str = "Wallet unlinked successfully"


class OptedInApp(BaseModel):
    """A single Algorand application the wallet has opted into."""

    app_id: int
    app_name: Optional[str] = None


class WalletBalanceResponse(BaseModel):
    """GET /v1/wallet/balance — live on-chain balance from Algorand node."""

    algorand_address: str
    algo_balance_microalgo: int = Field(description="Balance in microALGO")
    algo_balance_algo: str = Field(description="Balance in ALGO as string, e.g. '42.5'")
    min_balance: int = Field(description="Minimum balance required (microALGO)")
    available_balance: int = Field(description="algo_balance_microalgo - min_balance")
    opted_in_apps: list[OptedInApp] = Field(default_factory=list)
