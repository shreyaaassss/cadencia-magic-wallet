# context.md §6.3: NegotiationPolicy guards — pure static methods, no state, no I/O.

from __future__ import annotations

from decimal import Decimal

from src.shared.domain.exceptions import PolicyViolation


class NegotiationPolicy:
    """Stateless policy guards for negotiation invariants."""

    @staticmethod
    def check_budget_guard(price: Decimal, budget_ceiling: Decimal) -> None:
        if price > budget_ceiling:
            raise PolicyViolation(
                f"Offer {price} exceeds budget ceiling {budget_ceiling}"
            )

    @staticmethod
    def check_margin_floor(
        price: Decimal,
        cost_basis: Decimal,
        margin_floor: Decimal,
    ) -> None:
        if cost_basis <= Decimal("0"):
            return
        margin = (price - cost_basis) / cost_basis * 100
        if margin < margin_floor:
            raise PolicyViolation(
                f"Offer margin {margin:.1f}% below floor {margin_floor}%"
            )

    @staticmethod
    def check_stall(round_count: int, stall_threshold: int) -> bool:
        return round_count >= stall_threshold

    @staticmethod
    def check_convergence(
        buyer_price: Decimal | None,
        seller_price: Decimal | None,
        tolerance: float = 0.02,
    ) -> bool:
        if buyer_price is None or seller_price is None:
            return False
        if buyer_price <= Decimal("0"):
            return False
        gap = abs(seller_price - buyer_price) / buyer_price
        return float(gap) <= tolerance

    @staticmethod
    def check_turn_order(
        offers: list,  # list[Offer] — avoid circular import
        proposer_role_value: str,
    ) -> None:
        # First offer: no constraint — seller or buyer can anchor first
        # (FSM flipped to seller-first; legacy sessions retain buyer-first via next_proposer)
        if not offers:
            return
        last_role = offers[-1].proposer_role.value
        if last_role == proposer_role_value:
            raise PolicyViolation(
                f"Out-of-turn offer: {proposer_role_value} cannot offer consecutively"
            )
