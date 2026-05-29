# context.md §3: FastAPI/Pydantic imports ONLY in api/ layer.
# Pydantic v2 DTOs — completely separate from domain entities.
# NOTE: Do NOT use `from __future__ import annotations` — it breaks
# Pydantic v2 annotation resolution (EmailStr, model_validator returns).

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional, Self

from pydantic import BaseModel, EmailStr, Field, model_validator

from src.identity.domain.enterprise import Enterprise


# ── Request schemas ───────────────────────────────────────────────────────────

class AddressCreateRequest(BaseModel):
    """Address for facility (seller) or delivery site (buyer)."""
    address_type: Literal["FACILITY", "DELIVERY", "REGISTERED_OFFICE", "WAREHOUSE"] = "FACILITY"
    address_line1: str = Field(min_length=5, max_length=500)
    address_line2: str | None = Field(None, max_length=500)
    city: str = Field(min_length=2, max_length=100)
    state: str = Field(min_length=2, max_length=50)
    pincode: str = Field(pattern=r"^\d{6}$")
    latitude: float | None = None
    longitude: float | None = None


class EnterpriseCreateRequest(BaseModel):
    legal_name: str = Field(min_length=2, max_length=255)
    pan: str = Field(pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")
    gstin: str = Field(pattern=r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}Z[A-Z\d]{1}$")
    trade_role: Literal["BUYER", "SELLER", "BOTH"]
    commodities: list[str] = Field(default_factory=list, max_length=50)
    min_order_value: Decimal | None = Field(None, ge=0)
    max_order_value: Decimal | None = Field(None, ge=0)
    industry_vertical: str | None = Field(None, max_length=100)
    geography: str = Field(default="IN", max_length=100)
    # Enhanced onboarding: address
    address: Optional[AddressCreateRequest] = None
    # Enhanced onboarding: business details
    facility_type: Optional[Literal[
        "MANUFACTURING_PLANT", "WAREHOUSE", "TRADING_OFFICE", "INTEGRATED"
    ]] = None
    payment_terms_accepted: list[str] = Field(default_factory=list)
    credit_period_days: Optional[int] = Field(None, ge=0, le=180)
    years_in_operation: Optional[int] = Field(None, ge=0)
    annual_turnover_inr: Optional[Decimal] = Field(None, ge=0)
    quality_certifications: list[str] = Field(default_factory=list)
    test_certificate_available: bool = False
    third_party_inspection_allowed: bool = False


class UserCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(
        min_length=10,
        max_length=128,
        description="Min 10 chars. Must contain uppercase, digit, and special character.",
    )
    full_name: str | None = Field(None, max_length=255)
    role: Literal["MEMBER", "ADMIN", "TREASURY_MANAGER", "COMPLIANCE_OFFICER", "AUDITOR"] = "MEMBER"


class RegisterRequest(BaseModel):
    enterprise: EnterpriseCreateRequest
    user: UserCreateRequest

    @model_validator(mode="after")
    def validate_order_values(self) -> Self:
        e = self.enterprise
        if e.min_order_value is not None and e.max_order_value is not None:
            if e.min_order_value > e.max_order_value:
                raise ValueError("min_order_value must be <= max_order_value")
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class CreateAPIKeyRequest(BaseModel):
    label: str | None = Field(None, max_length=100)


# ── Agent Config schemas ──────────────────────────────────────────────────────


class AgentConfigInner(BaseModel):
    """The actual AI agent configuration the frontend sends/reads."""
    negotiation_style: Literal["AGGRESSIVE", "MODERATE", "CONSERVATIVE"] = "MODERATE"
    max_rounds: int = Field(default=20, ge=1, le=50)
    auto_escalate: bool = False
    min_acceptable_price: Optional[float] = None


class AgentConfigUpdateRequest(BaseModel):
    """PUT /v1/enterprises/:id/agent-config — request body."""
    agent_config: AgentConfigInner


class AgentConfigUpdateResponse(BaseModel):
    """PUT /v1/enterprises/:id/agent-config — success response."""
    message: str = "Agent configuration updated successfully"


# Kept for backwards compat in enterprise-update flows (not agent-config)
class AgentConfigRequest(BaseModel):
    """Legacy enterprise update request — used by PATCH enterprise."""
    industry_vertical: str | None = Field(None, max_length=100)
    commodities: list[str] = Field(default_factory=list)
    min_order_value: Decimal | None = Field(None, ge=0)
    max_order_value: Decimal | None = Field(None, ge=0)
    algorand_wallet: str | None = None

    @model_validator(mode="after")
    def validate_order_values(self) -> Self:
        if self.min_order_value is not None and self.max_order_value is not None:
            if self.min_order_value > self.max_order_value:
                raise ValueError("min_order_value must be <= max_order_value")
        return self


# ── Response schemas ──────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    enterprise_id: Optional[uuid.UUID] = None
    user_id: Optional[uuid.UUID] = None


class UserMeResponse(BaseModel):
    """GET /v1/auth/me — current user profile."""
    id: uuid.UUID
    email: str
    full_name: str
    role: str                                   # "ADMIN" | "MEMBER"
    enterprise_id: Optional[uuid.UUID] = None


class APIKeyResponse(BaseModel):
    id: uuid.UUID               # Frontend expects "id", not "key_id"
    key: str                    # Raw key shown ONCE
    label: str | None
    created_at: Optional[datetime] = None
    message: str = "Store this key securely — it will not be shown again."


class APIKeyListItem(BaseModel):
    id: uuid.UUID               # Frontend expects "id"
    label: str | None
    created_at: Optional[datetime] = None
    last_used: Optional[datetime] = None


# ── Enterprise response schemas ───────────────────────────────────────────────


class AgentConfigResponse(BaseModel):
    """Nested agent_config inside EnterpriseResponse."""
    negotiation_style: str = "MODERATE"
    max_rounds: int = 20
    auto_escalate: bool = False
    min_acceptable_price: Optional[float] = None


# KYC status value mapping (backend → frontend)
_KYC_STATUS_MAP = {
    "PENDING": "NOT_SUBMITTED",
    "KYC_SUBMITTED": "PENDING",
    "VERIFIED": "ACTIVE",
    "ACTIVE": "ACTIVE",
    "REJECTED": "REJECTED",
}


class EnterpriseResponse(BaseModel):
    """GET /v1/enterprises/:id — matches frontend Enterprise TypeScript interface."""
    id: uuid.UUID                                   # RENAMED from enterprise_id
    legal_name: str
    pan: str
    gstin: str
    trade_role: str
    kyc_status: str                                 # NOT_SUBMITTED | PENDING | ACTIVE | REJECTED
    industry_vertical: str
    geography: str
    commodities: list[str]
    min_order_value: float
    max_order_value: float
    algorand_wallet: Optional[str] = None
    agent_config: Optional[AgentConfigResponse] = None
    # Enhanced onboarding fields
    facility_type: Optional[str] = None
    payment_terms_accepted: list[str] = Field(default_factory=list)
    credit_period_days: Optional[int] = None
    years_in_operation: Optional[int] = None
    quality_certifications: list[str] = Field(default_factory=list)
    test_certificate_available: bool = False
    third_party_inspection_allowed: bool = False

    @classmethod
    def from_domain(cls, enterprise: "Enterprise") -> "EnterpriseResponse":
        # Map kyc_status to frontend-expected values
        raw_kyc = enterprise.kyc_status.value if hasattr(enterprise.kyc_status, 'value') else str(enterprise.kyc_status)
        frontend_kyc = _KYC_STATUS_MAP.get(raw_kyc, "NOT_SUBMITTED")

        # Build agent_config from the enterprise's agent_config dict (JSONB)
        agent_cfg = None
        if hasattr(enterprise, 'agent_config') and enterprise.agent_config:
            agent_cfg = AgentConfigResponse(
                negotiation_style=enterprise.agent_config.get("negotiation_style", "MODERATE"),
                max_rounds=enterprise.agent_config.get("max_rounds", 20),
                auto_escalate=enterprise.agent_config.get("auto_escalate", False),
                min_acceptable_price=enterprise.agent_config.get("min_acceptable_price"),
            )

        return cls(
            id=enterprise.id,
            legal_name=enterprise.legal_name,
            pan=enterprise.pan.value,
            gstin=enterprise.gstin.value,
            kyc_status=frontend_kyc,
            trade_role=enterprise.trade_role.value,
            algorand_wallet=enterprise.algorand_wallet.value if enterprise.algorand_wallet else None,
            industry_vertical=enterprise.industry_vertical or "",
            geography=getattr(enterprise, 'geography', 'IN') or "IN",
            commodities=enterprise.commodities or [],
            min_order_value=float(enterprise.min_order_value) if enterprise.min_order_value else 0,
            max_order_value=float(enterprise.max_order_value) if enterprise.max_order_value else 0,
            agent_config=agent_cfg,
            facility_type=getattr(enterprise, 'facility_type', None),
            payment_terms_accepted=getattr(enterprise, 'payment_terms_accepted', []) or [],
            credit_period_days=getattr(enterprise, 'credit_period_days', None),
            years_in_operation=getattr(enterprise, 'years_in_operation', None),
            quality_certifications=getattr(enterprise, 'quality_certifications', []) or [],
            test_certificate_available=getattr(enterprise, 'test_certificate_available', False) or False,
            third_party_inspection_allowed=getattr(enterprise, 'third_party_inspection_allowed', False) or False,
        )


class KYCStatusResponse(BaseModel):
    kyc_status: str
    message: str = "KYC documents submitted for review"


# ── Wallet schemas (RW-02: Pera Wallet integration) ──────────────────────────


class WalletChallengeResponse(BaseModel):
    """Challenge issued for wallet ownership verification."""

    challenge_id: str = Field(description="Unique challenge identifier")
    nonce: str = Field(description="Random nonce value")
    message_to_sign: str = Field(
        description="Full message string the wallet must sign"
    )
    expires_at: str = Field(description="ISO 8601 expiry timestamp (5 min TTL)")


class EnterpriseWalletLinkRequest(BaseModel):
    """Enterprise-scoped wallet link request (used by /v1/enterprises/{id}/wallet/link)."""

    algorand_address: str = Field(
        min_length=58, max_length=58,
        description="58-character Algorand address",
    )
    signature: str = Field(
        description="Base64-encoded Ed25519 signature of the challenge message"
    )
    challenge_id: str = Field(
        description="Challenge ID from the challenge endpoint"
    )


class WalletUnlinkResponse(BaseModel):
    """Response after unlinking a wallet."""

    enterprise_id: str
    message: str = "Wallet unlinked successfully"


class OptedInApp(BaseModel):
    """Application the wallet has opted into."""

    app_id: int
    app_name: str | None = None


class WalletBalanceResponse(BaseModel):
    """On-chain wallet balance and opted-in applications."""

    algorand_address: str
    algo_balance_microalgo: int = Field(description="Balance in microALGO")
    algo_balance_algo: str = Field(description="Balance in ALGO (human-readable)")
    min_balance: int = Field(description="Minimum balance required (microALGO)")
    available_balance: int = Field(
        description="Spendable balance (total - min_balance)"
    )
    opted_in_apps: list[OptedInApp] = Field(
        default_factory=list, description="Algorand apps the wallet has opted into"
    )
