# context.md §4 — SRP: commands are pure data transfer objects.
# No Pydantic, no FastAPI — these are internal application commands.

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class RegisterEnterpriseCommand:
    legal_name: str
    pan: str
    gstin: str
    trade_role: str
    email: str
    password: str
    full_name: str | None
    role: str
    commodities: list[str]
    min_order_value: Decimal | None
    max_order_value: Decimal | None
    industry_vertical: str | None
    geography: str = "IN"
    # Enhanced onboarding: address
    address: dict | None = None  # Serialized AddressCreateRequest
    # Enhanced onboarding: business details
    facility_type: str | None = None
    payment_terms_accepted: list[str] = field(default_factory=list)
    credit_period_days: int | None = None
    years_in_operation: int | None = None
    annual_turnover_inr: Decimal | None = None
    quality_certifications: list[str] = field(default_factory=list)
    test_certificate_available: bool = False
    third_party_inspection_allowed: bool = False


@dataclass(frozen=True)
class LoginCommand:
    email: str
    password: str


@dataclass(frozen=True)
class RefreshTokenCommand:
    refresh_token: str


@dataclass(frozen=True)
class SubmitKYCCommand:
    enterprise_id: uuid.UUID
    requesting_user_id: uuid.UUID
    documents: dict


@dataclass(frozen=True)
class VerifyKYCCommand:
    enterprise_id: uuid.UUID
    requesting_user_id: uuid.UUID


@dataclass(frozen=True)
class CreateAPIKeyCommand:
    enterprise_id: uuid.UUID
    requesting_user_id: uuid.UUID
    label: str | None


@dataclass(frozen=True)
class RevokeAPIKeyCommand:
    key_id: uuid.UUID
    enterprise_id: uuid.UUID
    requesting_user_id: uuid.UUID


@dataclass(frozen=True)
class UpdateAgentConfigCommand:
    enterprise_id: uuid.UUID
    requesting_user_id: uuid.UUID
    config: dict


@dataclass(frozen=True)
class LinkWalletCommand:
    enterprise_id: uuid.UUID
    requesting_user_id: uuid.UUID
    algorand_address: str


@dataclass(frozen=True)
class UnlinkWalletCommand:
    enterprise_id: uuid.UUID
    requesting_user_id: uuid.UUID
