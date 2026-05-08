# DANP Negotiation Engine — Layer 1: Valuation (Deterministic)
# Pure Python domain logic. Zero framework imports.
# Computes reservation_price, target_price, and walkaway_delta from
# intrinsic value, risk factor, and desired margin.

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from src.shared.domain.base_value_object import BaseValueObject
from src.shared.domain.exceptions import ValidationError


@dataclass(frozen=True)
class Valuation(BaseValueObject):
    """
    Deterministic valuation thresholds for a negotiation agent.

    reservation_price: Walk-away floor — agent will REJECT below this.
    target_price:      Ideal outcome — agent anchors here.
    walkaway_delta:    Convergence band — AGREED if gap <= this.
    """

    reservation_price: Decimal = Decimal("0")
    target_price: Decimal = Decimal("0")
    walkaway_delta: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.reservation_price <= Decimal("0"):
            raise ValidationError(
                f"reservation_price must be > 0, got {self.reservation_price}.",
                field="reservation_price",
            )
        if self.target_price <= Decimal("0"):
            raise ValidationError(
                f"target_price must be > 0, got {self.target_price}.",
                field="target_price",
            )
        if self.walkaway_delta < Decimal("0"):
            raise ValidationError(
                f"walkaway_delta must be >= 0, got {self.walkaway_delta}.",
                field="walkaway_delta",
            )

    def is_below_reservation(self, price: Decimal) -> bool:
        """True if price is below the walk-away floor."""
        return price < self.reservation_price

    def is_within_target(self, price: Decimal) -> bool:
        """True if price is at or better than the target."""
        return price <= self.target_price

    def gap_from_target(self, price: Decimal) -> Decimal:
        """Absolute gap between price and target, as fraction of target."""
        if self.target_price == Decimal("0"):
            return Decimal("1")
        return abs(price - self.target_price) / self.target_price


def compute_valuation(
    intrinsic: Decimal,
    risk: float,
    margin: float,
) -> Valuation:
    """
    Compute buyer/seller valuation from intrinsic value.

    For a BUYER:
      - reservation_price = intrinsic * (1 + risk)  — max they'll pay
      - target_price      = intrinsic * (1 - margin) — ideal low price
    For a SELLER:
      - reservation_price = intrinsic * (1 - risk)  — min they'll accept
      - target_price      = intrinsic * (1 + margin) — ideal high price

    This function is role-agnostic. Caller passes appropriate risk/margin signs.

    Args:
        intrinsic: Base fair value of the asset/commodity.
        risk:      Risk premium factor [0.0, 1.0] — widens the walk-away zone.
        margin:    Desired profit margin [0.0, 1.0] — sets the target.
    """
    if intrinsic <= Decimal("0"):
        raise ValidationError(
            f"intrinsic must be > 0, got {intrinsic}.", field="intrinsic"
        )
    if not (0.0 <= risk <= 1.0):
        raise ValidationError(
            f"risk must be in [0.0, 1.0], got {risk}.", field="risk"
        )
    if not (0.0 <= margin <= 1.0):
        raise ValidationError(
            f"margin must be in [0.0, 1.0], got {margin}.", field="margin"
        )

    risk_d = Decimal(str(risk))
    margin_d = Decimal(str(margin))

    reservation_price = (intrinsic * (Decimal("1") - risk_d)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    target_price = (intrinsic * (Decimal("1") - margin_d)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    walkaway_delta = abs(intrinsic * Decimal("0.02")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    # Ensure reservation_price is always positive
    if reservation_price <= Decimal("0"):
        reservation_price = Decimal("0.01")

    return Valuation(
        reservation_price=reservation_price,
        target_price=target_price if target_price > Decimal("0") else Decimal("0.01"),
        walkaway_delta=walkaway_delta,
    )


def compute_buyer_valuation(
    fair_price: Decimal,
    risk_appetite: str = "MEDIUM",
    budget_ceiling: Decimal | None = None,
) -> Valuation:
    """
    Convenience: compute valuation for a BUYER agent.

    Buyer wants to MINIMIZE cost:
      - reservation_price = budget_ceiling or fair_price * (1 + risk_factor)
      - target_price      = fair_price * (1 - discount_target)
    """
    risk_map = {"LOW": 0.05, "MEDIUM": 0.10, "HIGH": 0.20}
    margin_map = {"LOW": 0.03, "MEDIUM": 0.05, "HIGH": 0.10}
    risk = risk_map.get(risk_appetite, 0.10)
    margin = margin_map.get(risk_appetite, 0.05)

    val = compute_valuation(fair_price, risk=risk, margin=margin)

    # If budget_ceiling is specified, cap reservation_price
    if budget_ceiling is not None and budget_ceiling > Decimal("0"):
        capped_reservation = min(val.reservation_price, budget_ceiling)
        if capped_reservation <= Decimal("0"):
            capped_reservation = Decimal("0.01")
        return Valuation(
            reservation_price=capped_reservation,
            target_price=val.target_price,
            walkaway_delta=val.walkaway_delta,
        )
    return val


def compute_seller_valuation(
    cost_basis: Decimal,
    margin_floor: Decimal = Decimal("10"),
    risk_appetite: str = "MEDIUM",
) -> Valuation:
    """
    Convenience: compute valuation for a SELLER agent.

    Seller wants to MAXIMIZE revenue:
      - reservation_price = cost_basis * (1 + margin_floor/100)
      - target_price      = cost_basis * (1 + target_margin/100)
    """
    risk_map = {"LOW": 0.05, "MEDIUM": 0.10, "HIGH": 0.15}
    target_margin_map = {"LOW": 0.15, "MEDIUM": 0.20, "HIGH": 0.30}
    risk = risk_map.get(risk_appetite, 0.10)
    target_margin = target_margin_map.get(risk_appetite, 0.20)

    margin_d = margin_floor / Decimal("100")
    reservation = (cost_basis * (Decimal("1") + margin_d)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    target = (cost_basis * (Decimal("1") + Decimal(str(target_margin)))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    walkaway_delta = abs(cost_basis * Decimal("0.02")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    if reservation <= Decimal("0"):
        reservation = Decimal("0.01")
    if target <= Decimal("0"):
        target = Decimal("0.01")

    return Valuation(
        reservation_price=reservation,
        target_price=target,
        walkaway_delta=walkaway_delta,
    )


# ── Catalogue-aware convenience functions ────────────────────────────────────


def compute_seller_valuation_from_catalogue(
    catalogue_price: Decimal,
    bulk_price: Decimal | None = None,
    margin_floor: Decimal = Decimal("10"),
    risk_appetite: str = "MEDIUM",
) -> Valuation:
    """
    Compute seller valuation using catalogue pricing.

    catalogue_price is the listed ASKING/SELLING price (what the seller wants
    to receive), NOT an internal cost. margin_floor is the maximum discount
    the seller will accept from their asking price (e.g. 10% → floor is 90%
    of the catalogue price).

    reservation_price = catalogue_price × (1 - margin_floor/100)
    target_price      = catalogue_price  (seller aims for their full ask)

    Uses the bulk-tier price if available, otherwise the base catalogue price.
    """
    asking_price = bulk_price if bulk_price else catalogue_price
    margin_d = margin_floor / Decimal("100")

    reservation = (asking_price * (Decimal("1") - margin_d)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    target = asking_price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    walkaway_delta = (asking_price * Decimal("0.02")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    if reservation <= Decimal("0"):
        reservation = Decimal("0.01")

    return Valuation(
        reservation_price=reservation,
        target_price=target,
        walkaway_delta=walkaway_delta,
    )


def compute_buyer_valuation_from_rfq(
    budget_min: Decimal,
    budget_max: Decimal,
    risk_appetite: str = "MEDIUM",
) -> Valuation:
    """
    Compute buyer valuation from RFQ budget range.

    reservation_price = budget_max — the buyer's hard ceiling (won't pay more).
    target_price      = budget_max × target_factor — aspirational low price.

    NOTE: compute_valuation() applies (1-risk) which is the seller formula and
    produces a reservation BELOW the fair price. For buyers the reservation is
    their MAXIMUM (budget ceiling), so we set it directly rather than deriving it.
    """
    target_factor_map = {"LOW": Decimal("0.85"), "MEDIUM": Decimal("0.80"), "HIGH": Decimal("0.70")}
    target_factor = target_factor_map.get(risk_appetite, Decimal("0.80"))

    reservation = budget_max.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    target = (budget_max * target_factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    walkaway_delta = (budget_max * Decimal("0.02")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if target <= Decimal("0"):
        target = Decimal("0.01")

    return Valuation(
        reservation_price=reservation,
        target_price=target,
        walkaway_delta=walkaway_delta,
    )
