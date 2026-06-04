# DANP Negotiation Engine — Bayesian Opponent Modeling (Intelligence Layer)
# Pure Python domain logic. Zero framework imports.
# Classifies opponents as cooperative/strategic/stubborn/bluffing
# using Bayesian belief updating from observed negotiation metrics.

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Sequence

from src.shared.domain.base_value_object import BaseValueObject
from src.shared.domain.exceptions import ValidationError


class OpponentType(str, Enum):
    """Classified opponent negotiation archetype."""

    COOPERATIVE = "cooperative"          # High flexibility, fast responses, convergent
    STRATEGIC = "strategic"             # Medium flexibility, controlled pace
    STUBBORN = "stubborn"               # Low flexibility, slow, minimal concession
    BLUFFING = "bluffing"               # Oscillating flexibility, non-monotone
    DEADLINE_DRIVEN = "deadline_driven" # Speeds up concessions only near timeout
    RECIPROCATOR = "reciprocator"       # Mirrors concessions exactly (tit-for-tat)
    HARDBALL_THEN_CAVE = "hardball_then_cave"  # Holds firm then collapses after round 6-8
    ESCALATOR = "escalator"             # Increases demands (negative concession trend)


@dataclass(frozen=True)
class OpponentMetrics(BaseValueObject):
    """
    Observable signals from opponent's negotiation behavior.

    Computed from offer history by NeutralEngine after each turn.
    """

    flexibility_score: float = 0.5    # [0, 1] — how much they concede per round
    response_time: float = 5.0        # seconds — how fast they respond
    consistency: float = 0.5          # [0, 1] — monotonicity of concession
    concession_trend: float = 0.0     # positive = conceding more; negative = stiffening
    rounds_observed: int = 0

    def __post_init__(self) -> None:
        if not (0.0 <= self.flexibility_score <= 1.0):
            raise ValidationError(
                f"flexibility_score must be in [0, 1], got {self.flexibility_score}.",
                field="flexibility_score",
            )
        if not (0.0 <= self.consistency <= 1.0):
            raise ValidationError(
                f"consistency must be in [0, 1], got {self.consistency}.",
                field="consistency",
            )


@dataclass(frozen=True)
class OpponentBelief(BaseValueObject):
    """
    Posterior probability distribution over 8 opponent archetypes.

    Sum of all probabilities should equal 1.0 (normalized).
    New archetypes (deadline_driven, reciprocator, hardball_then_cave, escalator)
    default to 0.0 for backward compatibility with existing 4-type beliefs.
    """

    cooperative: float = 0.25
    strategic: float = 0.25
    stubborn: float = 0.25
    bluffing: float = 0.25
    # Extended archetypes — default 0.0 for backward compat
    deadline_driven: float = 0.0
    reciprocator: float = 0.0
    hardball_then_cave: float = 0.0
    escalator: float = 0.0

    def __post_init__(self) -> None:
        total = (
            self.cooperative + self.strategic + self.stubborn + self.bluffing
            + self.deadline_driven + self.reciprocator
            + self.hardball_then_cave + self.escalator
        )
        if abs(total - 1.0) > 0.01:
            raise ValidationError(
                f"Belief probabilities must sum to 1.0, got {total:.4f}.",
                field="belief",
            )

    @property
    def dominant_type(self) -> OpponentType:
        """Return the most probable opponent type."""
        beliefs = {
            OpponentType.COOPERATIVE: self.cooperative,
            OpponentType.STRATEGIC: self.strategic,
            OpponentType.STUBBORN: self.stubborn,
            OpponentType.BLUFFING: self.bluffing,
            OpponentType.DEADLINE_DRIVEN: self.deadline_driven,
            OpponentType.RECIPROCATOR: self.reciprocator,
            OpponentType.HARDBALL_THEN_CAVE: self.hardball_then_cave,
            OpponentType.ESCALATOR: self.escalator,
        }
        return max(beliefs, key=beliefs.get)  # type: ignore[arg-type]

    @property
    def confidence(self) -> float:
        """Return the probability of the dominant type."""
        return max(
            self.cooperative, self.strategic, self.stubborn, self.bluffing,
            self.deadline_driven, self.reciprocator,
            self.hardball_then_cave, self.escalator,
        )

    def to_dict(self) -> dict:
        """Serialize for JSON/JSONB storage."""
        return {
            "cooperative": round(self.cooperative, 4),
            "strategic": round(self.strategic, 4),
            "stubborn": round(self.stubborn, 4),
            "bluffing": round(self.bluffing, 4),
            "deadline_driven": round(self.deadline_driven, 4),
            "reciprocator": round(self.reciprocator, 4),
            "hardball_then_cave": round(self.hardball_then_cave, 4),
            "escalator": round(self.escalator, 4),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OpponentBelief":
        """Reconstruct from JSONB storage. Backward-compatible with 4-type beliefs."""
        return cls(
            cooperative=data.get("cooperative", 0.25),
            strategic=data.get("strategic", 0.25),
            stubborn=data.get("stubborn", 0.25),
            bluffing=data.get("bluffing", 0.25),
            deadline_driven=data.get("deadline_driven", 0.0),
            reciprocator=data.get("reciprocator", 0.0),
            hardball_then_cave=data.get("hardball_then_cave", 0.0),
            escalator=data.get("escalator", 0.0),
        )


class BayesianOpponentModel:
    """
    Bayesian opponent classifier — updates beliefs based on observed metrics.

    Uses P(type|data) ∝ P(data|type) × P(type) with Gaussian likelihoods.

    Thread-safe: no mutable state. Beliefs passed in/out per call.
    """

    # Prior: uniform over 4 types
    PRIOR = OpponentBelief()

    # Likelihood parameters: (mean, std_dev) for flexibility_score given type
    _FLEXIBILITY_LIKELIHOOD: dict[OpponentType, tuple[float, float]] = {
        OpponentType.COOPERATIVE: (0.8, 0.15),
        OpponentType.STRATEGIC: (0.45, 0.15),
        OpponentType.STUBBORN: (0.1, 0.10),
        OpponentType.BLUFFING: (0.5, 0.25),
    }

    # Likelihood for response_time given type
    _RESPONSE_TIME_LIKELIHOOD: dict[OpponentType, tuple[float, float]] = {
        OpponentType.COOPERATIVE: (2.0, 2.0),    # Fast
        OpponentType.STRATEGIC: (5.0, 3.0),       # Medium
        OpponentType.STUBBORN: (10.0, 5.0),       # Slow
        OpponentType.BLUFFING: (6.0, 4.0),        # Variable
    }

    # Likelihood for consistency given type
    _CONSISTENCY_LIKELIHOOD: dict[OpponentType, tuple[float, float]] = {
        OpponentType.COOPERATIVE: (0.8, 0.15),    # Highly consistent
        OpponentType.STRATEGIC: (0.6, 0.20),      # Fairly consistent
        OpponentType.STUBBORN: (0.7, 0.15),       # Consistent (consistently low)
        OpponentType.BLUFFING: (0.2, 0.20),       # Inconsistent (oscillating)
    }

    # Likelihood for new archetypes (concession_trend signal)
    _CONCESSION_TREND_LIKELIHOOD: dict[OpponentType, tuple[float, float]] = {
        OpponentType.COOPERATIVE: (0.02, 0.02),      # Steadily conceding
        OpponentType.STRATEGIC: (0.005, 0.01),        # Controlled
        OpponentType.STUBBORN: (-0.005, 0.005),       # Stiffening
        OpponentType.BLUFFING: (0.0, 0.03),           # Erratic
        OpponentType.DEADLINE_DRIVEN: (0.005, 0.02),  # Neutral until late
        OpponentType.RECIPROCATOR: (0.005, 0.01),     # Mirrors opponent
        OpponentType.HARDBALL_THEN_CAVE: (-0.01, 0.02), # Negative trend early
        OpponentType.ESCALATOR: (-0.03, 0.02),        # Consistently stiffening
    }

    # Flexibility likelihood for new archetypes
    _FLEXIBILITY_LIKELIHOOD_EXTENDED: dict[OpponentType, tuple[float, float]] = {
        OpponentType.DEADLINE_DRIVEN: (0.4, 0.20),   # Low early, spikes late
        OpponentType.RECIPROCATOR: (0.5, 0.15),      # Mirrors opponent
        OpponentType.HARDBALL_THEN_CAVE: (0.15, 0.10), # Very low early
        OpponentType.ESCALATOR: (0.1, 0.10),         # Extremely rigid
    }

    def update_belief(
        self,
        metrics: OpponentMetrics,
        prior: OpponentBelief | None = None,
    ) -> OpponentBelief:
        """Bayesian update: P(type|data) ∝ P(data|type) × P(type)."""
        prior = prior or self.PRIOR
        posteriors: dict[OpponentType, float] = {}

        for opp_type in OpponentType:
            p_type = getattr(prior, opp_type.value)

            # Flexibility likelihood (extended dict for new types)
            flex_params = (
                self._FLEXIBILITY_LIKELIHOOD.get(opp_type)
                or self._FLEXIBILITY_LIKELIHOOD_EXTENDED.get(opp_type)
                or (0.5, 0.25)
            )
            p_flex = self._gaussian_likelihood(metrics.flexibility_score, *flex_params)

            # Response time (reuse existing for new types — default strategic params)
            rt_params = self._RESPONSE_TIME_LIKELIHOOD.get(opp_type, (5.0, 3.0))
            p_time = self._gaussian_likelihood(metrics.response_time, *rt_params)

            # Consistency
            c_params = self._CONSISTENCY_LIKELIHOOD.get(opp_type, (0.5, 0.20))
            p_consistency = self._gaussian_likelihood(metrics.consistency, *c_params)

            # Concession trend (4th signal — only for new archetypes and existing)
            trend_params = self._CONCESSION_TREND_LIKELIHOOD.get(opp_type, (0.0, 0.02))
            p_trend = self._gaussian_likelihood(metrics.concession_trend, *trend_params)

            posteriors[opp_type] = p_type * p_flex * p_time * p_consistency * p_trend

        total = sum(posteriors.values())
        if total == 0:
            return prior

        normalized = {k: v / total for k, v in posteriors.items()}

        return OpponentBelief(
            cooperative=normalized[OpponentType.COOPERATIVE],
            strategic=normalized[OpponentType.STRATEGIC],
            stubborn=normalized[OpponentType.STUBBORN],
            bluffing=normalized[OpponentType.BLUFFING],
            deadline_driven=normalized[OpponentType.DEADLINE_DRIVEN],
            reciprocator=normalized[OpponentType.RECIPROCATOR],
            hardball_then_cave=normalized[OpponentType.HARDBALL_THEN_CAVE],
            escalator=normalized[OpponentType.ESCALATOR],
        )

    def strategy_modifier(self, belief: OpponentBelief) -> dict:
        """Return strategy adjustment based on dominant opponent type."""
        dominant = belief.dominant_type
        modifiers = {
            OpponentType.COOPERATIVE: {
                "concession_rate": 0.85,
                "pressure": False,
                "patience": 3,
                "rationale": "Cooperative opponent — concede less, they'll meet us.",
            },
            OpponentType.STRATEGIC: {
                "concession_rate": 1.00,
                "pressure": False,
                "patience": 5,
                "rationale": "Strategic opponent — match pace, standard concession.",
            },
            OpponentType.STUBBORN: {
                "concession_rate": 1.20,
                "pressure": True,
                "patience": 2,
                "rationale": "Stubborn opponent — increase pressure, concede more to probe.",
            },
            OpponentType.BLUFFING: {
                "concession_rate": 0.70,
                "pressure": True,
                "patience": 1,
                "rationale": "Bluffing detected — hold firm, call the bluff.",
            },
            OpponentType.DEADLINE_DRIVEN: {
                "concession_rate": 0.75,
                "pressure": False,
                "patience": 6,
                "rationale": "Deadline-driven — they'll cave near round limit, be patient.",
            },
            OpponentType.RECIPROCATOR: {
                "concession_rate": 1.00,
                "pressure": False,
                "patience": 5,
                "rationale": "Reciprocator — match their concessions exactly.",
            },
            OpponentType.HARDBALL_THEN_CAVE: {
                "concession_rate": 0.90,
                "pressure": False,
                "patience": 7,
                "rationale": "Hardball-then-cave — hold firm, they will collapse after round 6-8.",
            },
            OpponentType.ESCALATOR: {
                "concession_rate": 0.50,
                "pressure": True,
                "patience": 2,
                "rationale": "Escalator detected — extremely defensive, prepare to walk away.",
            },
        }
        return modifiers[dominant]

    @staticmethod
    def _gaussian_likelihood(x: float, mean: float, std: float) -> float:
        """Compute Gaussian PDF value — P(x | mean, std)."""
        if std <= 0:
            return 1.0 if x == mean else 0.0
        exponent = -0.5 * ((x - mean) / std) ** 2
        return (1.0 / (std * math.sqrt(2 * math.pi))) * math.exp(exponent)


# ── Metrics Computation (from offer history) ──────────────────────────────────


def compute_flexibility(prices: Sequence[Decimal]) -> float:
    """
    Compute flexibility score from a sequence of opponent's prices.

    Flexibility = EMA of relative price changes (0 = rigid, 1 = very flexible).
    """
    if len(prices) < 2:
        return 0.5  # Neutral prior

    deltas = []
    for i in range(1, len(prices)):
        prev = float(prices[i - 1])
        curr = float(prices[i])
        if prev > 0:
            delta = abs(curr - prev) / prev
            deltas.append(delta)

    if not deltas:
        return 0.5

    # Exponential Moving Average (alpha = 0.4)
    return min(_ema(deltas, alpha=0.4), 1.0)


def compute_consistency(prices: Sequence[Decimal]) -> float:
    """
    Compute consistency of concession direction.

    1.0 = always conceding in same direction (monotone).
    0.0 = oscillating wildly.
    """
    if len(prices) < 3:
        return 0.5  # Neutral

    directions = []
    for i in range(1, len(prices)):
        diff = float(prices[i]) - float(prices[i - 1])
        if diff > 0:
            directions.append(1)
        elif diff < 0:
            directions.append(-1)
        else:
            directions.append(0)

    if not directions:
        return 0.5

    # What fraction of transitions are in the same direction as the first?
    if directions[0] == 0:
        return 0.5

    same_direction = sum(1 for d in directions if d == directions[0])
    return same_direction / len(directions)


def compute_concession_trend(prices: Sequence[Decimal]) -> float:
    """
    Compute whether concessions are increasing or decreasing over time.

    Positive = conceding more per round; Negative = stiffening.
    """
    if len(prices) < 3:
        return 0.0

    deltas = []
    for i in range(1, len(prices)):
        prev = float(prices[i - 1])
        curr = float(prices[i])
        if prev > 0:
            deltas.append(abs(curr - prev) / prev)

    if len(deltas) < 2:
        return 0.0

    # Trend = average change in deltas
    trends = [deltas[i] - deltas[i - 1] for i in range(1, len(deltas))]
    return sum(trends) / len(trends) if trends else 0.0


def compute_opponent_metrics(
    opponent_prices: Sequence[Decimal],
    response_time: float = 5.0,
) -> OpponentMetrics:
    """
    Factory: compute all opponent metrics from offer price history.

    Args:
        opponent_prices: Sequence of prices from the opponent (chronological).
        response_time:   Average response time in seconds.
    """
    return OpponentMetrics(
        flexibility_score=compute_flexibility(opponent_prices),
        response_time=response_time,
        consistency=compute_consistency(opponent_prices),
        concession_trend=compute_concession_trend(opponent_prices),
        rounds_observed=len(opponent_prices),
    )


def _ema(values: list[float], alpha: float = 0.4) -> float:
    """Exponential moving average."""
    if not values:
        return 0.0
    result = values[0]
    for v in values[1:]:
        result = alpha * v + (1 - alpha) * result
    return result


def detect_strategy_shift(
    historical_prices: list[float],
    recent_window: int = 5,
    threshold: float = 0.3,
) -> bool:
    """
    Detect if opponent suddenly changed tactics using Wasserstein distance.

    Splits price history into historical vs recent windows.
    If distributional distance > threshold → strategy shift detected.
    Uses scipy.stats.wasserstein_distance (lightweight, no ML needed).
    Returns False if insufficient data.
    """
    if len(historical_prices) < recent_window + 3:
        return False

    deltas = [
        abs(historical_prices[i] - historical_prices[i - 1])
        / max(historical_prices[i - 1], 1.0)
        for i in range(1, len(historical_prices))
    ]

    hist_deltas = deltas[:-recent_window]
    recent_deltas = deltas[-recent_window:]

    if not hist_deltas or not recent_deltas:
        return False

    try:
        from scipy.stats import wasserstein_distance  # type: ignore[import-untyped]
        distance = wasserstein_distance(hist_deltas, recent_deltas)
        return distance > threshold
    except ImportError:
        # scipy not available — fall back to simple mean comparison
        hist_mean = sum(hist_deltas) / len(hist_deltas)
        recent_mean = sum(recent_deltas) / len(recent_deltas)
        if hist_mean > 0:
            return abs(recent_mean - hist_mean) / hist_mean > threshold
        return False
