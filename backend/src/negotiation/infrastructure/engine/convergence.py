"""Convergence detection logic extracted from NeutralEngine.

Handles ZOPA pre-check, agreement detection, and deal quality scoring.
These functions are called by NeutralEngine.process_turn() but can be
tested independently.
"""

from __future__ import annotations

from decimal import Decimal


def check_zopa_exists(
    buyer_ceiling: Decimal, seller_floor: Decimal
) -> bool:
    """Check if a Zone of Possible Agreement exists."""
    return buyer_ceiling >= seller_floor


def compute_deal_quality(
    agreed_price: Decimal,
    buyer_ceiling: Decimal,
    seller_floor: Decimal,
) -> dict:
    """Compute deal quality metrics after agreement.

    Returns buyer_surplus, seller_surplus, ZOPA width, and position.
    """
    zopa_width = buyer_ceiling - seller_floor
    if zopa_width <= 0:
        return {"score": 0, "zopa_width_inr": 0}

    buyer_surplus = buyer_ceiling - agreed_price
    seller_surplus = agreed_price - seller_floor
    buyer_share = float(buyer_surplus / zopa_width) if zopa_width > 0 else 0.5

    return {
        "score": round(buyer_share, 3),
        "buyer_surplus_inr": float(buyer_surplus),
        "seller_surplus_inr": float(seller_surplus),
        "zopa_width_inr": float(zopa_width),
        "zopa_position_pct": round(buyer_share * 100, 1),
        "agreed_price_inr": float(agreed_price),
    }


def is_within_convergence_tolerance(
    price_a: Decimal, price_b: Decimal, tolerance: float = 0.035
) -> bool:
    """Check if two prices are within convergence tolerance."""
    if price_a <= 0 or price_b <= 0:
        return False
    gap = abs(price_a - price_b) / max(price_a, price_b)
    return float(gap) <= tolerance
