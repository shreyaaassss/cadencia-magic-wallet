"""Negotiation configuration service.

Resolves the active NegotiationConfig for a session based on priority:
  1. Enterprise-level override (if enterprise has a custom config)
  2. Industry-matched config (from negotiation_config.applies_to_industries)
  3. Global 'DEFAULT' config
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import structlog

log = structlog.get_logger(__name__)


@dataclass
class NegotiationConfig:
    """Resolved configuration for a negotiation session."""

    config_name: str = "DEFAULT"
    max_rounds: int = 15  # Aligned with session.py MAX_ROUNDS
    stall_rounds: int = 3
    convergence_tolerance: float = 0.035  # 3.5% — B2B procurement standard
    session_ttl_hours: int = 24
    hardball_flexibility_threshold: float = 0.15
    walkaway_pct_below_floor: float = 0.10
    concessive_step_pct: float = 0.035
    conservative_step_pct: float = 0.015
    opponent_modifiers: dict = field(default_factory=lambda: {
        "cooperative": 0.85, "strategic": 1.0, "stubborn": 1.2, "bluffing": 0.7,
        "deadline_driven": 1.1, "reciprocator": 0.90, "hardball_then_cave": 1.15, "escalator": 1.3,
    })
    urgency_max_rounds: dict = field(default_factory=lambda: {
        "CRITICAL": 3, "HIGH": 5, "MODERATE": 8, "LOW": 15,
    })


class NegotiationConfigService:
    """Resolves and caches negotiation config per session."""

    def __init__(self, session: object) -> None:
        self._session = session
        self._cache: dict[str, NegotiationConfig] = {}

    async def resolve_config(
        self,
        enterprise_id: uuid.UUID | None = None,
        industry_vertical: str | None = None,
    ) -> NegotiationConfig:
        """Resolve the best-matching config.

        Priority: industry match → DEFAULT.
        """
        cache_key = f"{enterprise_id}:{industry_vertical}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        from sqlalchemy import select

        from src.negotiation.infrastructure.models import NegotiationConfigModel

        # Try industry-specific config
        if industry_vertical:
            result = await self._session.execute(
                select(NegotiationConfigModel).where(
                    NegotiationConfigModel.is_active == True,  # noqa: E712
                    NegotiationConfigModel.applies_to_industries.any(industry_vertical),
                )
            )
            row = result.scalar_one_or_none()
            if row:
                config = self._row_to_config(row)
                self._cache[cache_key] = config
                return config

        # Fallback to DEFAULT
        result = await self._session.execute(
            select(NegotiationConfigModel).where(
                NegotiationConfigModel.config_name == "DEFAULT"
            )
        )
        row = result.scalar_one_or_none()
        if row:
            config = self._row_to_config(row)
        else:
            config = NegotiationConfig()  # hardcoded defaults as last resort
            log.warning("negotiation_config_missing_default")

        self._cache[cache_key] = config
        return config

    @staticmethod
    def _row_to_config(row: object) -> NegotiationConfig:
        return NegotiationConfig(
            config_name=row.config_name,
            max_rounds=row.max_rounds,
            stall_rounds=row.stall_rounds,
            convergence_tolerance=float(row.convergence_tolerance),
            session_ttl_hours=row.session_ttl_hours,
            hardball_flexibility_threshold=float(row.hardball_flexibility_threshold or 0.15),
            walkaway_pct_below_floor=float(row.walkaway_pct_below_floor or 0.10),
            concessive_step_pct=float(row.concessive_step_pct or 0.035),
            conservative_step_pct=float(row.conservative_step_pct or 0.015),
            opponent_modifiers=row.opponent_modifiers or {},
            urgency_max_rounds=row.urgency_max_rounds or {},
        )
