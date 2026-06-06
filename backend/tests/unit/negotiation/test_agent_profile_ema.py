"""Tests for §7.4: Windowed EMA for agent profiles.

Covers: alpha floor at 0.05, new data influence after many sessions.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.negotiation.domain.agent_profile import AgentProfile


class TestWindowedEMA:
    """§7.4: EMA alpha must not become negligibly small."""

    def test_alpha_capped_at_minimum(self):
        """After 100 sessions, alpha must be >= 0.05."""
        profile = AgentProfile()
        profile.version = 100
        # alpha = max(1/(100+1), 0.05) = max(0.0099, 0.05) = 0.05
        old_win_rate = profile.strategy_weights.win_rate

        profile.update_after_session(
            session_agreed=True,
            rounds_taken=5,
            final_price=Decimal("800000"),
            budget_ceiling=Decimal("1000000"),
        )
        new_win_rate = profile.strategy_weights.win_rate
        change = abs(new_win_rate - old_win_rate)
        # With alpha=0.05, a session_agreed=True should change win_rate by at least 2%
        assert change >= 0.02, \
            f"EMA alpha too small after 100 sessions — new data has <2% influence: delta={change:.4f}"

    def test_alpha_normal_for_few_sessions(self):
        """For 5 sessions, alpha should be ~0.167 (normal EMA)."""
        profile = AgentProfile()
        profile.version = 5
        old_win_rate = profile.strategy_weights.win_rate

        profile.update_after_session(
            session_agreed=True,
            rounds_taken=3,
            final_price=Decimal("500000"),
            budget_ceiling=Decimal("600000"),
        )
        new_win_rate = profile.strategy_weights.win_rate
        change = abs(new_win_rate - old_win_rate)
        # alpha = max(1/6, 0.05) = 0.167 — significant influence
        assert change >= 0.05, f"Alpha unexpectedly small for few sessions: delta={change:.4f}"

    def test_version_increments(self):
        """version must increment after each session update."""
        profile = AgentProfile()
        initial_version = profile.version
        profile.update_after_session(
            session_agreed=False,
            rounds_taken=10,
            final_price=None,
            budget_ceiling=Decimal("500000"),
        )
        assert profile.version == initial_version + 1
