# DANP Negotiation Engine — Layer 2: Strategy Engine (8 Strategies)
# Pure Python domain logic. Zero framework imports.
# Implements 8 negotiation strategies with concession curves
# and adaptive concession based on Bayesian opponent beliefs.

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Callable

from src.shared.domain.base_value_object import BaseValueObject
from src.shared.domain.exceptions import ValidationError


class StrategyType(str, Enum):
    """8 negotiation strategies from the DANP spec."""

    STRONG_ANCHOR = "STRONG_ANCHOR"           # Round 0: aggressive opening
    ANCHOR = "ANCHOR"                         # Round 1 seller: listed asking price
    BOULWARE = "BOULWARE"                     # Slow → Fast concession
    TIT_FOR_TAT = "TIT_FOR_TAT"               # Mirror opponent's last move
    ULTIMATUM = "ULTIMATUM"                   # Final take-it-or-leave-it offer
    HARDBALL = "HARDBALL"                     # Hold firm (aspirational zone)
    DEADLINE_PRESSURE = "DEADLINE_PRESSURE"   # Accelerate near timeout
    CONDITIONAL = "CONDITIONAL"               # Bundle/terms trading
    WALK_AWAY = "WALK_AWAY"                   # Below reservation → reject
    CONSERVATIVE = "CONSERVATIVE"             # Small step concession
    CONCESSIVE = "CONCESSIVE"                 # Larger concession to close gap
    CONSTRAINED = "CONSTRAINED"               # Near-budget / near-floor move


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
        aspirational_price: Decimal | None = None,
    ) -> StrategyRecommendation:
        """
        Select the optimal strategy for this turn.

        aspirational_price is the practical hold-firm zone — 40% above the
        seller's true floor (or 40% below the buyer's ceiling toward target).
        In normal rounds, neither side concedes past their aspirational price.
        Only DEADLINE_PRESSURE / ULTIMATUM may push into the true floor zone.

        Returns a StrategyRecommendation with the selected strategy,
        concession fraction, suggested price, and rationale.
        """
        # Resolve effective floor: aspirational if set, else reservation
        # Seller: never publicly concede below aspirational in normal rounds
        # Buyer:  aspirational is slightly above target (mild friction)
        effective_floor: Decimal = (
            aspirational_price
            if aspirational_price is not None and aspirational_price > reservation_price
            else reservation_price
        )

        # Round 0 / buyer's first response (seller-first flow)
        if round_num == 0 or (round_num == 1 and my_last_price is None):
            # In seller-first flow the buyer responds to a known seller anchor.
            # Open at the midpoint of target and aspirational (not reservation) so
            # the gap is convergeable and the buyer isn't unnecessarily aggressive.
            if (
                is_buyer
                and opponent_last_price is not None
                and opponent_last_price > reservation_price
            ):
                # Buyer aspirational is slightly above target — use it as the
                # opening offer floor so we don't start too low
                buyer_aspir = aspirational_price if aspirational_price else target_price
                responsive = (
                    (target_price + buyer_aspir) / Decimal("2")
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                return StrategyRecommendation(
                    strategy=StrategyType.STRONG_ANCHOR,
                    concession_fraction=Decimal("0"),
                    suggested_price=max(responsive, Decimal("0.01")),
                    rationale=(
                        "Seller anchored above budget — opening at midpoint of "
                        "target and aspirational to create a convergeable gap."
                    ),
                    action="OFFER",
                )
            return self._strong_anchor(target_price, effective_floor, is_buyer)

        # Reservation-price guard — do NOT walk away on first low buyer offer.
        # The stall_counter handles genuine deadlock.
        if opponent_last_price is not None:
            if is_buyer and opponent_last_price > reservation_price:
                pass  # seller above ceiling — normal, buyer negotiates down

        # Less than 3 rounds remaining → ultimatum (may push past aspirational)
        remaining = self.max_rounds - round_num
        if remaining <= 2:
            return self._ultimatum(
                my_last_price or target_price,
                opponent_last_price,
                reservation_price,   # ultimatum can reach true floor
                is_buyer,
            )

        # ── ASPIRATIONAL HOLD-FIRM ZONE ──────────────────────────────────────
        # If my current price is already AT or BELOW the aspirational price,
        # switch to HARDBALL — signal credible resistance before crossing into
        # the true floor zone. This simulates a negotiator saying "this is my
        # best price" before reluctantly making a final concession.
        #
        # Only applies when NOT near deadline (deadline_pressure handles that)
        # and when the opponent is not extremely stubborn (stall handles that).
        if (
            my_last_price is not None
            and aspirational_price is not None
            and time_remaining_pct >= 0.25  # not near deadline
            and rounds_since_concession < 3   # not fully stalled
        ):
            at_aspirational = (
                (not is_buyer and my_last_price <= aspirational_price * Decimal("1.02"))
                or (is_buyer and my_last_price >= aspirational_price * Decimal("0.98"))
            )
            if at_aspirational:
                return self._hardball(
                    my_last_price,
                    effective_floor,
                    is_buyer,
                    rationale=(
                        "At aspirational hold-firm zone — signalling credible "
                        "resistance before any further concession."
                    ),
                )

        # Opponent genuinely stubborn (low flexibility + stalled) → hardball
        if opponent_flexibility < 0.15 and rounds_since_concession >= 2:
            return self._hardball(
                my_last_price or target_price,
                effective_floor,
                is_buyer,
            )

        # Near deadline → deadline pressure (may push past aspirational toward floor)
        if time_remaining_pct < 0.25:
            return self._deadline_pressure(
                round_num,
                my_last_price or target_price,
                opponent_last_price,
                reservation_price,   # deadline pressure uses true floor
                target_price,
                is_buyer,
            )

        # Opponent cooperative → tit-for-tat with aspirational floor
        if opponent_flexibility > 0.7:
            return self._tit_for_tat(
                my_last_price or target_price,
                opponent_last_price,
                effective_floor,     # aspirational as floor, not true reservation
                target_price,
                modifier=Decimal("0.85"),
                is_buyer=is_buyer,
            )

        # WALK_AWAY — opponent persistently 10%+ below seller's TRUE floor
        if (
            opponent_last_price is not None
            and not is_buyer
            and opponent_last_price < reservation_price * Decimal("0.90")
            and rounds_since_concession >= 3
        ):
            return self._walk_away(reservation_price, opponent_last_price, is_buyer)

        # CONDITIONAL — large gap, cooperative opponent → bundle terms
        if (
            opponent_flexibility > 0.4
            and my_last_price is not None
            and opponent_last_price is not None
            and abs(opponent_last_price - my_last_price)
                / max(my_last_price, Decimal("1")) > Decimal("0.20")
        ):
            return self._conditional(
                my_last_price, effective_floor, target_price, is_buyer
            )

        # ── CONSTRAINED: near floor, time remaining — micro-concession ──
        if (
            my_last_price is not None
            and time_remaining_pct > 0.25
        ):
            at_floor = (
                (not is_buyer and my_last_price <= reservation_price * Decimal("1.05"))
                or (is_buyer and my_last_price >= reservation_price * Decimal("0.95"))
            )
            if at_floor:
                return self._constrained(my_last_price, reservation_price, target_price, is_buyer)

        # ── Anti-stall: force CONCESSIVE if no concession for 3+ rounds mid-session ──
        # Prevents buyer/seller from deadlocking when gap is still closeable.
        time_used_pct = 1.0 - time_remaining_pct
        if (
            rounds_since_concession >= 3
            and time_used_pct >= 0.50
            and my_last_price is not None
            and opponent_last_price is not None
        ):
            gap_abs = abs(float(my_last_price) - float(opponent_last_price))
            gap_pct_abs = gap_abs / max(float(my_last_price), 1.0)
            if 0.05 <= gap_pct_abs <= 0.35:  # Gap is closeable — force movement
                return self._concessive(my_last_price, reservation_price, target_price, is_buyer)

        # ── CONCESSIVE: mid-to-late rounds, large gap — accelerate closing ──
        if (
            0.60 <= time_used_pct <= 0.85
            and my_last_price is not None
            and opponent_last_price is not None
        ):
            gap = abs(float(my_last_price) - float(opponent_last_price))
            gap_pct = gap / max(float(my_last_price), 1.0)
            if gap_pct > 0.08:  # Lowered from 0.10 for earlier trigger
                return self._concessive(my_last_price, reservation_price, target_price, is_buyer)

        # ── CONSERVATIVE: moderate opponent, no stall ──
        if 0.3 <= opponent_flexibility <= 0.5 and rounds_since_concession < 2:
            return self._conservative(my_last_price or target_price, reservation_price, target_price, is_buyer)

        # Default: Boulware — concedes toward aspirational (NOT true floor)
        return self._boulware(
            round_num,
            my_last_price or target_price,
            effective_floor,        # aspirational as practical endpoint
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
        effective_floor: Decimal,
        target_price: Decimal,
        is_buyer: bool,
    ) -> StrategyRecommendation:
        """
        Boulware: slow concession toward aspirational (not true floor).

        ZOPA-MIDPOINT FIX: the curve endpoint is now `effective_floor`
        (= aspirational_price in normal rounds, = reservation_price only
        under deadline pressure). This prevents the seller from conceding
        all the way to the true floor during ordinary negotiation rounds.
        """
        fraction = Decimal(str(_boulware_curve(round_num, self.max_rounds)))
        price_range = abs(effective_floor - target_price)

        if is_buyer:
            # Buyer concedes UP from target toward effective_floor (aspirational)
            suggested = target_price + (price_range * fraction)
            # Never exceed effective_floor (buyer aspirational)
            suggested = min(suggested, effective_floor)
        else:
            # Seller concedes DOWN from target toward effective_floor (aspirational)
            suggested = target_price - (price_range * fraction)
            # Never go below effective_floor (seller aspirational)
            suggested = max(suggested, effective_floor)

        suggested = suggested.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        suggested = max(suggested, Decimal("0.01"))

        return StrategyRecommendation(
            strategy=StrategyType.BOULWARE,
            concession_fraction=fraction.quantize(Decimal("0.01")),
            suggested_price=suggested,
            rationale=(
                f"Boulware curve at round {round_num}/{self.max_rounds} — "
                f"conceding toward aspirational hold-firm price "
                f"({float(effective_floor):,.2f}), not true floor."
            ),
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
        effective_floor: Decimal,
        is_buyer: bool,
        rationale: str = "Hardball: holding firm against stubborn/bluffing opponent.",
    ) -> StrategyRecommendation:
        """
        Hold firm — minimal 0.5% token concession to show engagement.

        Used both for genuine bluff detection AND for the aspirational hold-firm
        zone (when price reaches 40% above the true floor). The token concession
        keeps the session alive while signalling resistance.
        """
        if is_buyer:
            suggested = (my_last_price * Decimal("1.005")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            suggested = min(suggested, effective_floor)
        else:
            suggested = (my_last_price * Decimal("0.995")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            suggested = max(suggested, effective_floor)

        suggested = max(suggested, Decimal("0.01"))

        return StrategyRecommendation(
            strategy=StrategyType.HARDBALL,
            concession_fraction=Decimal("0.005"),
            suggested_price=suggested,
            rationale=rationale,
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

    def _conditional(
        self,
        my_last_price: Decimal,
        reservation_price: Decimal,
        target_price: Decimal,
        is_buyer: bool,
    ) -> StrategyRecommendation:
        """
        Conditional/terms-bundling strategy.

        Used when a large gap remains but the opponent is cooperative —
        suggest adding non-price terms (payment schedule, delivery timeline,
        volume commitment, warranty, etc.) to unlock value without pure concession.
        The suggested price stays at target (no price movement in this round).
        """
        # Hold price at target — terms will compensate for the gap
        suggested = target_price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        suggested = max(suggested, Decimal("0.01"))

        if is_buyer:
            rationale = (
                "CONDITIONAL: Large gap remains but opponent is cooperative — "
                "propose bundling faster payment terms or volume commitments to "
                "bridge the difference without further price concessions."
            )
        else:
            rationale = (
                "CONDITIONAL: Large gap remains but opponent is cooperative — "
                "propose bundling extended warranty, preferred delivery scheduling, "
                "or phased delivery to add value without lowering price further."
            )

        return StrategyRecommendation(
            strategy=StrategyType.CONDITIONAL,
            concession_fraction=Decimal("0"),
            suggested_price=suggested,
            rationale=rationale,
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

    def _conservative(
        self,
        my_last: Decimal,
        floor: Decimal,
        target: Decimal,
        is_buyer: bool,
    ) -> StrategyRecommendation:
        """Small step: 1.5% concession toward target."""
        step = my_last * Decimal("0.015")
        if is_buyer:
            price = min(my_last + step, target)
        else:
            price = max(my_last - step, floor)
        price = price.quantize(Decimal("0.01"))
        return StrategyRecommendation(
            strategy=StrategyType.CONSERVATIVE,
            concession_fraction=Decimal("0.015"),
            suggested_price=price,
            rationale="Conservative: moderate opponent, small deliberate step.",
            action="OFFER",
        )

    def _concessive(
        self,
        my_last: Decimal,
        floor: Decimal,
        target: Decimal,
        is_buyer: bool,
    ) -> StrategyRecommendation:
        """Larger step: 3-4% concession to close gap in mid-late rounds."""
        step = my_last * Decimal("0.035")
        if is_buyer:
            price = min(my_last + step, target)
        else:
            price = max(my_last - step, floor)
        price = price.quantize(Decimal("0.01"))
        return StrategyRecommendation(
            strategy=StrategyType.CONCESSIVE,
            concession_fraction=Decimal("0.035"),
            suggested_price=price,
            rationale="Concessive: mid-to-late stage, closing gap to reach agreement.",
            action="OFFER",
        )

    def _constrained(
        self,
        my_last: Decimal,
        floor: Decimal,
        target: Decimal,
        is_buyer: bool,
    ) -> StrategyRecommendation:
        """Near-floor: 0.5-1% micro-concession while signaling constraint."""
        step = my_last * Decimal("0.007")
        if is_buyer:
            price = min(my_last + step, target)
        else:
            price = max(my_last - step, floor)
        price = price.quantize(Decimal("0.01"))
        return StrategyRecommendation(
            strategy=StrategyType.CONSTRAINED,
            concession_fraction=Decimal("0.007"),
            suggested_price=price,
            rationale="Constrained: near reservation price — signaling this is our limit.",
            action="OFFER",
        )


def adaptive_concession(
    base_concession: Decimal,
    opponent_flexibility: float,
    opponent_type: str = "strategic",
    reciprocity_ratio: Decimal = Decimal("1.0"),
) -> Decimal:
    """
    Modify base concession using Bayesian opponent classification
    AND reciprocity ratio (Improvement #4).

    - Cooperative opponent → concede less (they'll meet us)
    - Stubborn opponent → concede more (pressure/show flexibility)
    - Bluffing → hold firm
    - Strategic → match pace
    - reciprocity_ratio < 1: I'm giving more than I'm getting → reduce concession
    - reciprocity_ratio > 1: opponent giving more → I can be generous
    """
    modifiers = {
        "cooperative": Decimal("0.85"),
        "strategic": Decimal("1.00"),
        "stubborn": Decimal("1.20"),
        "bluffing": Decimal("0.70"),
    }
    modifier = modifiers.get(opponent_type, Decimal("1.00"))
    adjusted = (base_concession * modifier * reciprocity_ratio).quantize(
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


# ── Improvement #4: Reciprocity Ratio ────────────────────────────────────────


def compute_reciprocity_ratio(
    my_last_concession: Decimal,
    opponent_last_concession: Decimal,
) -> Decimal:
    """
    Compute how much I'm giving relative to the opponent's last move.

    If I conceded ₹50K and they conceded ₹10K → ratio = 5.0
    I'm training them to be stubborn → halve my next concession.

    If they conceded ₹40K and I conceded ₹10K → ratio = 0.25
    They're being generous → I can reciprocate.

    Returns a multiplier for adaptive_concession():
      > 1.0  → opponent is more flexible, I can concede more
      = 1.0  → balanced
      < 1.0  → I'm conceding too much relative to opponent, slow down
    """
    if my_last_concession <= Decimal("0"):
        return Decimal("1.0")  # First move — neutral
    if opponent_last_concession <= Decimal("0"):
        return Decimal("0.5")  # Opponent not moving → be cautious

    ratio = my_last_concession / opponent_last_concession

    if ratio > Decimal("3.0"):
        # I'm giving 3×+ more → significantly reduce concession
        return Decimal("0.40")
    elif ratio > Decimal("2.0"):
        # I'm giving 2×+ more → reduce concession
        return Decimal("0.60")
    elif ratio > Decimal("1.5"):
        # Slightly unbalanced → mild reduction
        return Decimal("0.80")
    elif ratio < Decimal("0.33"):
        # Opponent giving 3×+ more → I can be quite generous
        return Decimal("1.40")
    elif ratio < Decimal("0.5"):
        # Opponent giving 2×+ more → be somewhat generous
        return Decimal("1.20")
    else:
        # Roughly balanced (0.5–1.5× ratio) → neutral
        return Decimal("1.0")


# ── Improvement #3: Dynamic Confidence Scoring ───────────────────────────────


def compute_dynamic_confidence(
    my_price: Decimal,
    opponent_last_price: Decimal | None,
    aspirational: Decimal,
    reservation: Decimal,
    is_buyer: bool,
    rounds_used: int,
    max_rounds: int,
) -> float:
    """
    Compute meaningful confidence score (0.0–1.0) for this offer.

    Components (weighted):
      40% — ZOPA position: how close is my price to the aspirational hold-firm?
              Closer to aspirational = more defensible = higher confidence.
      40% — Gap to opponent: smaller gap = higher likelihood of acceptance.
      20% — Time factor: fewer rounds remaining = higher urgency/seriousness.

    Replaces the hardcoded confidence=0.5 across the engine.
    """
    if reservation <= Decimal("0") or aspirational <= Decimal("0"):
        return 0.5

    # 1. ZOPA position component
    zopa_range = abs(aspirational - reservation)
    if zopa_range > Decimal("0"):
        if not is_buyer:
            # Seller: higher price relative to aspirational = better position
            pos = float((my_price - reservation) / zopa_range)
        else:
            # Buyer: lower price relative to reservation = better position
            pos = float((reservation - my_price) / zopa_range)
        zopa_component = max(0.0, min(1.0, pos))
    else:
        zopa_component = 0.5

    # 2. Gap to opponent component
    if opponent_last_price and opponent_last_price > Decimal("0"):
        gap_frac = float(
            abs(my_price - opponent_last_price) / opponent_last_price
        )
        gap_component = max(0.0, 1.0 - gap_frac * 3)
    else:
        gap_component = 0.3  # No opponent data yet → low confidence

    # 3. Time pressure component (more rounds used → more serious)
    time_component = min(1.0, rounds_used / max(max_rounds * 0.6, 1))

    confidence = (
        zopa_component * 0.40
        + gap_component * 0.40
        + time_component * 0.20
    )
    return round(min(1.0, max(0.10, confidence)), 2)


# ── Improvement #8: Psychological Price Rounding ─────────────────────────────


def apply_negotiation_rounding(
    price: Decimal,
    round_num: int,
    max_rounds: int,
) -> Decimal:
    """
    Round price to psychologically appropriate precision.

    Real negotiators use deliberate rounding to signal confidence.
    Raw computed prices like ₹12,87,345.23 signal "I am a machine."
    Rounded offers like ₹13,00,000 signal "I've thought about this."

    Progress-based quanta:
      Early  (0–20% of rounds): nearest ₹25,000 — confident anchor
      Mid    (20–60%):          nearest ₹10,000 — calculated but clear
      Late   (60–85%):          nearest  ₹5,000 — precision = seriousness
      Final  (85–100%):         nearest  ₹2,500 — "I've done the math"
    """
    progress = round_num / max(max_rounds, 1)

    if progress < 0.20:
        quantum = Decimal("25000")
    elif progress < 0.60:
        quantum = Decimal("10000")
    elif progress < 0.85:
        quantum = Decimal("5000")
    else:
        quantum = Decimal("2500")

    if quantum <= Decimal("0") or price <= Decimal("0"):
        return price

    rounded = (price / quantum).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * quantum
    return max(rounded, Decimal("2500"))  # Never round to zero

