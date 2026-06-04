# context.md §3 — Hexagonal Architecture: zero framework imports in domain layer.
# FEMA (Foreign Exchange Management Act) compliance records for Indian B2B trade.
# Equivalent to RBI Form 15CA / 15CB for outward remittances.

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from src.compliance.domain.value_objects import INRAmount, PANNumber, PurposeCode
from src.shared.domain.base_entity import BaseEntity


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass
class FEMARecord(BaseEntity):
    """
    FEMA compliance record for a completed escrow settlement.

    Generated automatically when EscrowReleased event is received.
    Corresponds to RBI Form 15CA (declaration) / 15CB (CA certificate equivalent).

    context.md §1: Regulatory compliance — FEMA/GST export, 7-year retention.
    """

    escrow_id: uuid.UUID = field(default_factory=uuid.uuid4)

    # Form type: 15CA is the taxpayer declaration; 15CB is the CA certificate.
    # For MSME trades below INR 5 lakh, 15CA Part A suffices.
    form_type: Literal["15CA", "15CB"] = "15CA"

    # RBI LRS purpose code — default P0108 (goods import by MSME)
    purpose_code: PurposeCode = field(
        default_factory=lambda: PurposeCode(value=PurposeCode.DEFAULT)
    )

    # Parties
    buyer_pan: PANNumber = field(default_factory=lambda: PANNumber(value="AAAAA0000A"))
    seller_pan: PANNumber = field(default_factory=lambda: PANNumber(value="BBBBB0000B"))

    # Amounts
    amount_inr: INRAmount = field(default_factory=lambda: INRAmount(value=Decimal("0")))
    amount_algo: Decimal = Decimal("0")  # Amount in Algorand (plain Decimal)
    fx_rate_inr_per_algo: Decimal = Decimal("0")  # INR per 1 ALGO

    # Merkle root anchored on-chain — links FEMA record to blockchain proof
    merkle_root: str = ""  # 64-char hex from EscrowReleased event

    # Immutable after creation
    generated_at: datetime = field(default_factory=_utcnow)

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def generate(
        cls,
        escrow_id: uuid.UUID,
        buyer_pan: str,
        seller_pan: str,
        amount_microalgo: int,
        fx_rate_inr_per_algo: Decimal,
        merkle_root: str,
        purpose_code: str = PurposeCode.DEFAULT,
    ) -> "FEMARecord":
        """
        Generate a FEMA record from escrow release data.

        Args:
            amount_microalgo:     Escrow amount in microAlgo (1 ALGO = 1_000_000 microAlgo).
            fx_rate_inr_per_algo: Current INR/ALGO exchange rate.
            merkle_root:          64-char hex Merkle root from on-chain anchor.
        """
        amount_algo = Decimal(amount_microalgo) / Decimal("1000000")
        amount_inr = amount_algo * fx_rate_inr_per_algo

        # 15CB required if remittance > INR 5,00,000 (500_000)
        form_type: Literal["15CA", "15CB"] = (
            "15CB" if amount_inr >= Decimal("500000") else "15CA"
        )

        return cls(
            escrow_id=escrow_id,
            form_type=form_type,
            purpose_code=PurposeCode(value=purpose_code),
            buyer_pan=PANNumber(value=buyer_pan),
            seller_pan=PANNumber(value=seller_pan),
            amount_inr=INRAmount(value=amount_inr.quantize(Decimal("0.01"))),
            amount_algo=amount_algo,
            fx_rate_inr_per_algo=fx_rate_inr_per_algo,
            merkle_root=merkle_root,
        )
