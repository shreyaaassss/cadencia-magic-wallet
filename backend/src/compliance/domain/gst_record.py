# context.md §3 — Hexagonal Architecture: zero framework imports in domain layer.
# Indian GST (Goods and Services Tax) compliance records.
# IGST for interstate; CGST+SGST for intrastate (same state buyer+seller).

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from src.compliance.domain.value_objects import GSTIN, HSNCode, INRAmount
from src.shared.domain.base_entity import BaseEntity


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# GST rate constants (as Decimal percentages)
_IGST_RATE = Decimal("18")     # 18% IGST for interstate
_CGST_RATE = Decimal("9")      # 9%  CGST for intrastate
_SGST_RATE = Decimal("9")      # 9%  SGST for intrastate


@dataclass
class GSTRecord(BaseEntity):
    """
    GST compliance record for a completed escrow settlement.

    Tax type determination:
        Interstate  (buyer_state != seller_state) → IGST @ 18%
        Intrastate  (buyer_state == seller_state) → CGST 9% + SGST 9%

    context.md §1: Regulatory compliance — FEMA/GST export, 7-year retention.
    """

    escrow_id: uuid.UUID = field(default_factory=uuid.uuid4)

    # Product classification
    hsn_code: HSNCode = field(default_factory=lambda: HSNCode(value="8471"))

    # Party GSTINs
    buyer_gstin: GSTIN = field(
        default_factory=lambda: GSTIN(value="27AAAAA0000A1Z5")
    )
    seller_gstin: GSTIN = field(
        default_factory=lambda: GSTIN(value="29BBBBB0000B1Z5")
    )

    # Tax type determined at generation time
    tax_type: Literal["IGST", "CGST_SGST"] = "IGST"

    # Amounts (in INR)
    taxable_amount: INRAmount = field(
        default_factory=lambda: INRAmount(value=Decimal("0"))
    )
    igst_amount: INRAmount = field(
        default_factory=lambda: INRAmount(value=Decimal("0"))
    )
    cgst_amount: INRAmount = field(
        default_factory=lambda: INRAmount(value=Decimal("0"))
    )
    sgst_amount: INRAmount = field(
        default_factory=lambda: INRAmount(value=Decimal("0"))
    )

    generated_at: datetime = field(default_factory=_utcnow)

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def generate(
        cls,
        escrow_id: uuid.UUID,
        buyer_gstin: str,
        seller_gstin: str,
        hsn_code: str,
        taxable_amount_inr: Decimal,
    ) -> "GSTRecord":
        """
        Generate a GST record from escrow release data.

        Interstate vs. intrastate determined by comparing the 2-digit state
        code prefix of buyer_gstin and seller_gstin.
        """
        buyer = GSTIN(value=buyer_gstin)
        seller = GSTIN(value=seller_gstin)
        taxable = INRAmount(value=taxable_amount_inr.quantize(Decimal("0.01")))

        is_interstate = buyer.state_code != seller.state_code

        if is_interstate:
            igst = INRAmount(
                value=(taxable_amount_inr * _IGST_RATE / Decimal("100")).quantize(
                    Decimal("0.01")
                )
            )
            return cls(
                escrow_id=escrow_id,
                hsn_code=HSNCode(value=hsn_code),
                buyer_gstin=buyer,
                seller_gstin=seller,
                tax_type="IGST",
                taxable_amount=taxable,
                igst_amount=igst,
                cgst_amount=INRAmount(value=Decimal("0")),
                sgst_amount=INRAmount(value=Decimal("0")),
            )
        else:
            cgst = INRAmount(
                value=(taxable_amount_inr * _CGST_RATE / Decimal("100")).quantize(
                    Decimal("0.01")
                )
            )
            sgst = INRAmount(
                value=(taxable_amount_inr * _SGST_RATE / Decimal("100")).quantize(
                    Decimal("0.01")
                )
            )
            return cls(
                escrow_id=escrow_id,
                hsn_code=HSNCode(value=hsn_code),
                buyer_gstin=buyer,
                seller_gstin=seller,
                tax_type="CGST_SGST",
                taxable_amount=taxable,
                igst_amount=INRAmount(value=Decimal("0")),
                cgst_amount=cgst,
                sgst_amount=sgst,
            )

    @property
    def total_tax(self) -> Decimal:
        """Total GST paid (IGST or CGST+SGST depending on tax_type)."""
        return (
            self.igst_amount.value
            + self.cgst_amount.value
            + self.sgst_amount.value
        )
