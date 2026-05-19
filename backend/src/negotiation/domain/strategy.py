# DANP Negotiation Engine — Layer 2: Strategy Engine (8 Strategies)
# Pure Python domain logic. Zero framework imports.
# Implements 8 negotiation strategies with concession curves
# and adaptive concession based on Bayesian opponent beliefs.

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Callable

from src.shared.domain.base_value_object import BaseValueObject
from src.shared.domain.exceptions import ValidationError


class StrategyType(str, Enum):
    """8 negotiation strategies from the DANP spec."""

    STRONG_ANCHOR = "STRONG_ANCHOR"       # Round 0: aggressive opening
    BOULWARE = "BOULWARE"                 # Slow → Fast concession
    TIT_FOR_TAT = "TIT_FOR_TAT"           # Mirror opponent's last move
    ULTIMATUM = "ULTIMATUM"               # Final take-it-or-leave-it offer
    HARDBALL = "HARDBALL"                  # Hold firm (bluff detected)
    DEADLINE_PRESSURE = "DEADLINE_PRESSURE"  # Accelerate near timeout
    CONDITIONAL = "CONDITIONAL"            # Bundle/terms trading
    WALK_AWAY = "WALK_AWAY"                # Below reservation → reject


# ── Concession Curves ─────────────────────────────────────────────────────────

def _boulware_curve(round_num: int, max_rounds: int) -> float:
    """Slow initial concession, accelerating toward deadline."""
    if max_rounds <= 0:
        return 0.0
    t = round_num / max_rounds
    return 1.0 - (1.0 - t) ** 3


def _linear_curve(round_num: int, max_rounds: int) -> float:
    """Linear concession over rounds."""
    if max_rounds <= 0:
        return 0.0
    return round_num / max_rounds


def _conceder_curve(round_num: int, max_rounds: int) -> float:
    """Fast initial concession, slowing toward deadline."""
    if max_rounds <= 0:
        return 0.0
    t = round_num / max_rounds
    return t ** 2


def _hardliner_curve(round_num: int, max_rounds: int) -> float:
    """Minimal concession — hold firm."""
    return 0.05  # Always only 5%


def _deadline_pressure_curve(round_num: int, max_rounds: int) -> float:
    """Exponential ramp-up near deadline."""
    if max_rounds <= 0:
        return 0.0
    t = round_num / max_rounds
    return (math.exp(3 * t) - 1) / (math.exp(3) - 1)


CONCESSION_CURVES: dict[str, Callable[[int, int], float]] = {
    "BOULWARE": _boulware_curve,
    "LINEAR": _linear_curve,
    "CONCEDER": _conceder_curve,
    "HARDLINER": _hardliner_curve,
    "DEADLINE_PRESSURE": _deadline_pressure_curve,
}


# ── Strategy Selection ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StrategyRecommendation(BaseValueObject):
    """Output of strategy selection — tells the agent what to do."""

    strategy: StrategyType = StrategyType.TIT_FOR_TAT
    concession_fraction: Decimal = Decimal("0.05")
    suggested_price: Decimal = Decimal("0")
    rationale: str = ""
    action: str = "COUNTER"  # OFFER, COUNTER, ACCEPT, REJECT

    def __post_init__(self) -> None:
        if self.concession_fraction < Decimal("0") or self.concession_fraction > Decimal("1"):
            raise ValidationError(
                f"concession_fraction must be in [0, 1], got {self.concession_fraction}.",
                field="concession_fraction",
            )


class StrategyEngine:
    """
    Selects and applies one of 8 negotiation strategies based on:
    - Current round / max rounds
    - Last opponent offer
    - Agent's valuation (reservation + target)
    - Opponent belief (from Bayesian model)

    Stateless — all context passed per call.
    """

    def __init__(self, max_rounds: int = 20) -> None:
        self.max_rounds = max_rounds

    def select_strategy(
        self,
        round_num: int,
        my_last_price: Decimal | None,
        opponent_last_price: Decimal | None,
        reservation_price: Decimal,
        target_price: Decimal,
        opponent_flexibility: float = 0.5,
        rounds_since_concession: int = 0,
        time_remaining_pct: float = 1.0,
        is_buyer: bool = True,
    ) -> StrategyRecommendation:
        """
        Select the optimal strategy for this turn.

        Returns a StrategyRecommendation with the selected strategy,
        concession fraction, suggested price, and rationale.
        """
        # Round 0 / buyer's first response (seller-first flow)
        if round_num == 0 or (round_num == 1 and my_last_price is None):
            # In seller-first flow the buyer responds to a known seller anchor.
            # If the seller opened above the buyer's ceiling, opening at 76% of
            # budget (the old formula) creates a 40-50% gap that never converges.
            # Instead, open at the midpoint of target and reservation so the gap
            # is ~20-25% and reachable within the round budget.
            if (
                is_buyer
                and opponent_last_price is not None
                and opponent_last_price > reservation_price
            ):
                responsive = (
                    (target_price + reservation_price) / Decimal("2")
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                return StrategyRecommendation(
                    strategy=StrategyType.STRONG_ANCHOR,
                    concession_fraction=Decimal("0"),
                    suggested_price=max(responsive, Decimal("0.01")),
                    rationale=(
                        "Seller anchored above budget ceiling — opening at midpoint "
                        "of target and budget to create a convergeable gap."
                    ),
                    action="OFFER",
                )
            return self._strong_anchor(target_price, reservation_price, is_buyer)

        # Reservation-price guard.
        # For the SELLER: do NOT walk away just because the buyer's current
        # offer is below the floor. Low buyer anchors are normal negotiation
        # strategy — the buyer will concede upward over subsequent rounds.
        # If they genuinely refuse to move, the stall_counter (3 consecutive
        # no-concession rounds) will terminate the session naturally.
        # Walking away here on the first low offer kills deals that a ZOPA
        # analysis already proved are reachable (e.g. buyer ceiling ₹15L,
        # seller floor ₹14.85L → deal at ~₹14.9L is perfectly achievable).
        if opponent_last_price is not None:
            if is_buyer and opponent_last_price > reservation_price:
                # Seller is above buyer's ceiling — normal, buyer negotiates down.
                pass
            # Seller side: fall through to normal strategy (Boulware / TitForTat).
            # Stall detection handles the genuine deadlock case.

        # Less than 3 rounds remaining → ultimatum
        remaining = self.max_rounds - round_num
        if remaining <= 2:
            return self._ultimatum(
                my_last_price or target_price,
                opponent_last_price,
                reservation_price,
                is_buyer,
            )

        # Opponent stubborn (low flexibility) → hardball
        if opponent_flexibility < 0.15 and rounds_since_concession >= 2:
            return self._hardball(
                my_last_price or target_price,
                reservation_price,
                is_buyer,
            )

        # Near deadline → deadline pressure
        if time_remaining_pct < 0.25:
            return self._deadline_pressure(
                round_num,
                my_last_price or target_price,
                opponent_last_price,
                reservation_price,
                target_price,
                is_buyer,
            )

        # Opponent oscillating → conditional/hold
        if opponent_flexibility > 0.7:
            # Cooperative opponent — concede less
            return self._tit_for_tat(
                my_last_price or target_price,
                opponent_last_price,
                reservation_price,
                target_price,
                modifier=Decimal("0.85"),
                is_buyer=is_buyer,
            )

        # Default: Boulware (slow concession)
        return self._boulware(
            round_num,
            my_last_price or target_price,
            reservation_price,
            target_price,
            is_buyer,
        )

    # ── Strategy Implementations ──────────────────────────────────────────────

    def _strong_anchor(
        self,
        target_price: Decimal,
        reservation_price: Decimal,
        is_buyer: bool,
    ) -> StrategyRecommendation:
        """Aggressive opening offer at or beyond target."""
        if is_buyer:
            # Buyer anchors LOW — 5% below target
            anchor = (target_price * Decimal("0.95")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        else:
            # Seller anchors HIGH — 10% above target
            anchor = (target_price * Decimal("1.10")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        return StrategyRecommendation(
            strategy=StrategyType.STRONG_ANCHOR,
            concession_fraction=Decimal("0"),
            suggested_price=max(anchor, Decimal("0.01")),
            rationale="Round 0 aggressive anchor to establish position.",
            action="OFFER",
        )

    def _boulware(
        self,
        round_num: int,
        my_last_price: Decimal,
        reservation_price: Decimal,
        target_price: Decimal,
        is_buyer: bool,
    ) -> StrategyRecommendation:
        """Boulware: slow concession, accelerating toward deadline."""
        fraction = Decimal(str(_boulware_curve(round_num, self.max_rounds)))
        price_range = abs(reservation_price - target_price)

        if is_buyer:
            # Buyer concedes UP from target toward reservation
            suggested = target_price + (price_range * fraction)
        else:
            # Seller concedes DOWN from target toward reservation
            suggested = target_price - (price_range * fraction)

        suggested = suggested.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        suggested = max(suggested, Decimal("0.01"))

        return StrategyRecommendation(
            strategy=StrategyType.BOULWARE,
            concession_fraction=fraction.quantize(Decimal("0.01")),
            suggested_price=suggested,
            rationale=f"Boulware curve at round {round_num}/{self.max_rounds}.",
            action="COUNTER",
        )

    def _tit_for_tat(
        self,
        my_last_price: Decimal,
        opponent_last_price: Decimal | None,
        reservation_price: Decimal,
        target_price: Decimal,
        modifier: Decimal = Decimal("1.0"),
        is_buyer: bool = True,
    ) -> StrategyRecommendation:
        """Mirror opponent's last concession, optionally modified."""
        if opponent_last_price is None:
            # No opponent data — use small concession
            concession = Decimal("0.02")
        else:
            gap = abs(opponent_last_price - my_last_price)
            if my_last_price > Decimal("0"):
                concession = (gap / my_last_price * modifier).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                )
            else:
                concession = Decimal("0.02")

        # Cap concession
        concession = min(concession, Decimal("0.15"))
        concession = max(concession, Decimal("0.005"))

        if is_buyer:
            suggested = (my_last_price * (Decimal("1") + concession)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            # Don't exceed reservation
            suggested = min(suggested, reservation_price)
        else:
            suggested = (my_last_price * (Decimal("1") - concession)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            # Don't go below reservation
            suggested = max(suggested, reservation_price)

        suggested = max(suggested, Decimal("0.01"))

        return StrategyRecommendation(
            strategy=StrategyType.TIT_FOR_TAT,
            concession_fraction=concession.quantize(Decimal("0.01")),
            suggested_price=suggested,
            rationale="Tit-for-tat: mirroring opponent's last concession.",
            action="COUNTER",
        )

    def _ultimatum(
        self,
        my_last_price: Decimal,
        opponent_last_price: Decimal | None,
        reservation_price: Decimal,
        is_buyer: bool,
    ) -> StrategyRecommendation:
        """Final offer — take it or leave it."""
        # Move halfway to reservation as final concession
        if opponent_last_price is not None:
            midpoint = (my_last_price + opponent_last_price) / Decimal("2")
        else:
            midpoint = my_last_price

        midpoint = midpoint.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Ensure within bounds
        if is_buyer:
            suggested = min(midpoint, reservation_price)
        else:
            suggested = max(midpoint, reservation_price)

        suggested = max(suggested, Decimal("0.01"))

        return StrategyRecommendation(
            strategy=StrategyType.ULTIMATUM,
            concession_fraction=Decimal("0"),
            suggested_price=suggested,
            rationale="Ultimatum: final offer with <3 rounds remaining.",
            action="COUNTER",
        )

    def _hardball(
        self,
        my_last_price: Decimal,
        reservation_price: Decimal,
        is_buyer: bool,
    ) -> StrategyRecommendation:
        """Hold firm — minimal concession against stubborn/bluffing opponent."""
        # Tiny 1% concession to show engagement
        if is_buyer:
            suggested = (my_last_price * Decimal("1.01")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            suggested = min(suggested, reservation_price)
        else:
            suggested = (my_last_price * Decimal("0.99")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            suggested = max(suggested, reservation_price)

        suggested = max(suggested, Decimal("0.01"))

        return StrategyRecommendation(
            strategy=StrategyType.HARDBALL,
            concession_fraction=Decimal("0.01"),
            suggested_price=suggested,
            rationale="Hardball: holding firm against stubborn opponent.",
            action="COUNTER",
        )

    def _deadline_pressure(
        self,
        round_num: int,
        my_last_price: Decimal,
        opponent_last_price: Decimal | None,
        reservation_price: Decimal,
        target_price: Decimal,
        is_buyer: bool,
    ) -> StrategyRecommendation:
        """Accelerated concession near timeout."""
        fraction = Decimal(
            str(_deadline_pressure_curve(round_num, self.max_rounds))
        )
        price_range = abs(reservation_price - target_price)

        if is_buyer:
            suggested = target_price + (price_range * fraction)
        else:
            suggested = target_price - (price_range * fraction)

        suggested = suggested.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        suggested = max(suggested, Decimal("0.01"))

        return StrategyRecommendation(
            strategy=StrategyType.DEADLINE_PRESSURE,
            concession_fraction=fraction.quantize(Decimal("0.01")),
            suggested_price=suggested,
            rationale="Deadline pressure: accelerated concession near timeout.",
            action="COUNTER",
        )

    def _walk_away(
        self,
        reservation_price: Decimal,
        opponent_price: Decimal,
        is_buyer: bool,
    ) -> StrategyRecommendation:
        """Reject — opponent's offer is beyond our walk-away threshold."""
        return StrategyRecommendation(
            strategy=StrategyType.WALK_AWAY,
            concession_fraction=Decimal("0"),
            suggested_price=reservation_price,
            rationale=(
                f"Walk-away: opponent price {opponent_price} "
                f"{'exceeds' if is_buyer else 'below'} reservation {reservation_price}."
            ),
            action="REJECT",
        )


def adaptive_concession(
    base_concession: Decimal,
    opponent_flexibility: float,
    opponent_type: str = "strategic",
) -> Decimal:
    """
    Modify base concession using Bayesian opponent classification.

    - Cooperative opponent → concede less (they'll meet us)
    - Stubborn opponent → concede more (pressure/show flexibility)
    - Bluffing → hold firm
    - Strategic → match pace
    """
    modifiers = {
        "cooperative": Decimal("0.85"),
        "strategic": Decimal("1.00"),
        "stubborn": Decimal("1.20"),
        "bluffing": Decimal("0.70"),
    }
    modifier = modifiers.get(opponent_type, Decimal("1.00"))
    adjusted = (base_concession * modifier).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    # Cap at [0, 0.30]
    return max(Decimal("0"), min(adjusted, Decimal("0.30")))


# ── Urgency-Aware Round Limits ───────────────────────────────────────────────


_URGENCY_MAX_ROUNDS = {
    "CRITICAL": 3,
    "HIGH": 5,
    "MODERATE": 8,
    "LOW": 15,
}


def get_max_rounds_for_urgency(urgency_level: str) -> int:
    """
    Return max negotiation rounds based on delivery urgency.

    CRITICAL (<2 days buffer): 3 rounds — push for immediate agreement
    HIGH (2-5 days buffer): 5 rounds — quick convergence
    MODERATE (5-10 days buffer): 8 rounds — normal with timeline awareness
    LOW (>10 days buffer): 15 rounds — negotiate freely
    """
    return _URGENCY_MAX_ROUNDS.get(urgency_level.upper(), 15)
