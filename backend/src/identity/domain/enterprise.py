# context.md §3 — Hexagonal Architecture: zero framework imports.
# Pure Python aggregate root.

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from src.shared.domain.base_entity import BaseEntity
from src.shared.domain.exceptions import ConflictError, PolicyViolation, ValidationError
from src.identity.domain.value_objects import AlgorandAddress, GSTIN, PAN


class KYCStatus(str, Enum):
    """
    KYC state machine (context.md §9.1):
    PENDING → KYC_SUBMITTED → VERIFIED → ACTIVE
    """

    PENDING = "PENDING"
    KYC_SUBMITTED = "KYC_SUBMITTED"
    VERIFIED = "VERIFIED"
    ACTIVE = "ACTIVE"


class TradeRole(str, Enum):
    BUYER = "BUYER"
    SELLER = "SELLER"
    BOTH = "BOTH"


@dataclass
class Enterprise(BaseEntity):
    """
    Enterprise aggregate root (identity bounded context).

    Enforces the KYC state machine and all business invariants.
    No framework imports — pure Python.
    """

    legal_name: str = ""
    pan: PAN = field(default_factory=lambda: PAN(value="AAAAA0000A"))
    gstin: GSTIN = field(default_factory=lambda: GSTIN(value="00AAAAA0000A0Z0"))
    kyc_status: KYCStatus = KYCStatus.PENDING
    trade_role: TradeRole = TradeRole.BUYER
    algorand_wallet: AlgorandAddress | None = None
    industry_vertical: str | None = None
    geography: str = "IN"
    min_order_value: Decimal | None = None
    max_order_value: Decimal | None = None
    commodities: list[str] = field(default_factory=list)
    listing_active: bool = True
    # KYC documents payload — stored as JSONB
    kyc_documents: dict | None = None
    # Agent config — AI negotiation settings (JSONB)
    agent_config: dict | None = None
    # Enhanced onboarding fields
    facility_type: str | None = None
    payment_terms_accepted: list[str] = field(default_factory=list)
    credit_period_days: int | None = None
    years_in_operation: int | None = None
    annual_turnover_inr: Decimal | None = None
    quality_certifications: list[str] = field(default_factory=list)
    test_certificate_available: bool = False
    third_party_inspection_allowed: bool = False

    # ── KYC State Machine ─────────────────────────────────────────────────────

    def submit_kyc(self, documents: dict) -> "EnterpriseKYCSubmitted":
        """
        Transition: PENDING → KYC_SUBMITTED.

        Raises ConflictError if not in PENDING status.
        Returns EnterpriseKYCSubmitted domain event.
        """
        if self.kyc_status != KYCStatus.PENDING:
            raise ConflictError(
                f"Cannot submit KYC: enterprise is in status '{self.kyc_status.value}', "
                "expected PENDING."
            )
        self.kyc_status = KYCStatus.KYC_SUBMITTED
        self.kyc_documents = documents
        self.touch()
        return EnterpriseKYCSubmitted(
            aggregate_id=self.id,
            event_type="EnterpriseKYCSubmitted",
            enterprise_id=self.id,
        )

    def verify_kyc(self) -> "EnterpriseKYCVerified":
        """
        Transition: KYC_SUBMITTED → VERIFIED.

        Raises ConflictError if not in KYC_SUBMITTED status.
        """
        if self.kyc_status != KYCStatus.KYC_SUBMITTED:
            raise ConflictError(
                f"Cannot verify KYC: enterprise is in status '{self.kyc_status.value}', "
                "expected KYC_SUBMITTED."
            )
        self.kyc_status = KYCStatus.VERIFIED
        self.touch()
        return EnterpriseKYCVerified(
            aggregate_id=self.id,
            event_type="EnterpriseKYCVerified",
            enterprise_id=self.id,
        )

    def activate(self) -> "EnterpriseActivated":
        """
        Transition: VERIFIED → ACTIVE.

        Raises PolicyViolation if not in VERIFIED status.
        """
        if self.kyc_status != KYCStatus.VERIFIED:
            raise PolicyViolation(
                f"Cannot activate enterprise: KYC status is '{self.kyc_status.value}', "
                "must be VERIFIED first."
            )
        self.kyc_status = KYCStatus.ACTIVE
        self.touch()
        return EnterpriseActivated(
            aggregate_id=self.id,
            event_type="EnterpriseActivated",
            enterprise_id=self.id,
        )

    # ── Business operations ───────────────────────────────────────────────────

    def update_agent_config(self, config: dict) -> None:
        """
        Update agent personalization configuration.

        Validates min_order_value <= max_order_value.
        Raises ValidationError on constraint violation.
        """
        new_min = config.get("min_order_value")
        new_max = config.get("max_order_value")

        if new_min is not None:
            self.min_order_value = Decimal(str(new_min))
        if new_max is not None:
            self.max_order_value = Decimal(str(new_max))

        if self.min_order_value is not None and self.max_order_value is not None:
            if self.min_order_value > self.max_order_value:
                raise ValidationError(
                    "min_order_value must be less than or equal to max_order_value.",
                    field="min_order_value",
                )

        if "industry_vertical" in config:
            self.industry_vertical = config["industry_vertical"]
        if "commodities" in config:
            self.commodities = list(config["commodities"])
        if "geography" in config:
            self.geography = str(config["geography"])

        self.touch()

    def link_algorand_wallet(self, address: AlgorandAddress) -> None:
        """
        Link an Algorand wallet to this enterprise.

        Raises ConflictError if a wallet is already linked.
        """
        if self.algorand_wallet is not None:
            raise ConflictError(
                f"Algorand wallet already linked: {self.algorand_wallet.value}. "
                "Unlink the existing wallet before linking a new one."
            )
        self.algorand_wallet = address
        self.touch()

    def unlink_algorand_wallet(self) -> None:
        """Unlink the Algorand wallet from this enterprise."""
        self.algorand_wallet = None
        self.touch()


# ── Domain Events ─────────────────────────────────────────────────────────────
# Defined here for proximity to the aggregate; re-exported from identity/domain/events.py

from src.shared.domain.events import DomainEvent  # noqa: E402


@dataclass(frozen=True)
class EnterpriseKYCSubmitted(DomainEvent):
    enterprise_id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass(frozen=True)
class EnterpriseKYCVerified(DomainEvent):
    enterprise_id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass(frozen=True)
class EnterpriseActivated(DomainEvent):
    enterprise_id: uuid.UUID = field(default_factory=uuid.uuid4)
