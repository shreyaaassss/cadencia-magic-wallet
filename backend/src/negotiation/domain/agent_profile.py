# context.md §3 — Hexagonal Architecture: zero framework imports in domain layer.
# context.md §6.2: AgentProfile learns from each completed session.
# SECURITY: to_prompt_context() NEVER includes exact budget_ceiling, PAN, GSTIN, or keys.

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from src.shared.domain.base_entity import BaseEntity
from src.negotiation.domain.value_objects import (
    AutomationLevel,
    RiskProfile,
    StrategyWeights,
)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)

_BUDGET_BUCKETS = [
    ("HIGH", Decimal("1000000")),
    ("MEDIUM", Decimal("100000")),
    ("LOW", Decimal("0")),
]


@dataclass
class AgentProfile(BaseEntity):
    """
    Per-enterprise LLM negotiation agent configuration.

    Learns from session outcomes via update_after_session().
    Serialised into LLM system prompt via to_prompt_context().

    context.md §6.2: Layer 2 — Agent Personalization Engine.
    """

    enterprise_id: uuid.UUID = field(default_factory=uuid.uuid4)
    strategy_weights: StrategyWeights = field(default_factory=StrategyWeights)
    risk_profile: RiskProfile = field(default_factory=RiskProfile)
    playbook_ids: list[uuid.UUID] = field(default_factory=list)
    history_embedding: list[float] | None = None   # pgvector (optional)
    automation_level: AutomationLevel = field(
        default_factory=lambda: AutomationLevel(value="FULL")
    )
    version: int = 1
    # Algo wallet address for SessionAgreed event (populated from enterprise)
    algo_address: str = ""

    # ── Learning ──────────────────────────────────────────────────────────────

    def update_after_session(
        self,
        session_agreed: bool,
        rounds_taken: int,
        final_price: Decimal | None,
        budget_ceiling: Decimal,
    ) -> None:
        """
        Update strategy_weights with exponential moving average after each session.

        context.md §6.2: rolling average for win_rate, avg_rounds, avg_deviation.
        """
        w = self.strategy_weights
        n = max(self.version, 1)  # use version as session count proxy
        alpha = 1.0 / (n + 1)    # EMA factor

        new_win_rate = (
            w.win_rate * (1 - alpha) + (1.0 if session_agreed else 0.0) * alpha
        )
        new_avg_rounds = w.avg_rounds * (1 - alpha) + rounds_taken * alpha

        new_avg_deviation = w.avg_deviation
        if session_agreed and final_price is not None and budget_ceiling > Decimal("0"):
            deviation = float(
                abs(final_price - budget_ceiling) / budget_ceiling * 100
            )
            new_avg_deviation = w.avg_deviation * (1 - alpha) + deviation * alpha

        # EMA-update concession_rate from this session's actual behavior
        new_concession_rate = w.concession_rate
        if session_agreed and final_price is not None and budget_ceiling > Decimal("0"):
            actual_concession = float(abs(final_price - budget_ceiling) / budget_ceiling)
            new_concession_rate = w.concession_rate * (1 - alpha) + actual_concession * alpha

        # Rebuild frozen StrategyWeights (frozen dataclass — use object.__setattr__)
        object.__setattr__(
            self,
            "strategy_weights",
            StrategyWeights(
                concession_rate=new_concession_rate,
                acceptance_threshold=w.acceptance_threshold,
                avg_deviation=new_avg_deviation,
                avg_rounds=new_avg_rounds,
                win_rate=new_win_rate,
                stall_threshold=w.stall_threshold,
            ),
        )
        self.version += 1
        self.touch()

    # ── LLM Context ───────────────────────────────────────────────────────────

    def to_prompt_context(self) -> dict:
        """
        Serialise profile for LLM system prompt injection.

        SECURITY: budget_ceiling exact value NEVER included.
        Redacted to HIGH/MEDIUM/LOW bucket.
        context.md §6.2, §7.4.
        """
        bucket = _get_budget_bucket(self.risk_profile.budget_ceiling)
        w = self.strategy_weights
        return {
            "automation_level": self.automation_level.value,
            "strategy": {
                "concession_rate": "aggressive" if w.concession_rate > 0.5 else "conservative",
                "win_rate_pct": round(w.win_rate * 100, 1),
                "avg_rounds": round(w.avg_rounds, 1),
                "stall_threshold": w.stall_threshold,
            },
            "risk": {
                "budget_range": bucket,        # HIGH / MEDIUM / LOW — never exact
                "margin_floor_pct": float(self.risk_profile.margin_floor),
                "risk_appetite": self.risk_profile.risk_appetite,
            },
        }


def _get_budget_bucket(ceiling: Decimal) -> str:
    for label, threshold in _BUDGET_BUCKETS:
        if ceiling > threshold:
            return label
    return "LOW"
