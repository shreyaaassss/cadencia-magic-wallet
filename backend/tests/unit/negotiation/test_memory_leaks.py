"""Tests for §7.1, §7.2: Memory leak prevention.

Covers: ZOPA cache eviction, belief cache eviction, agent driver singleton.
"""
from __future__ import annotations

import pytest
from decimal import Decimal
from unittest.mock import MagicMock


class TestZOPACacheEviction:
    """§7.1/§10.2: _zopa_cache and _belief_cache must be evicted on terminal state."""

    def test_evict_session_state_removes_entries(self, neutral_engine):
        session_id = "test-session-uuid-001"
        neutral_engine._zopa_cache[session_id] = {
            "seller_floor": Decimal("800000"),
            "buyer_ceiling": Decimal("1000000"),
        }
        neutral_engine._belief_cache[session_id] = {
            "buyer": MagicMock(),
            "seller": MagicMock(),
        }
        neutral_engine.evict_session_state(session_id)
        assert session_id not in neutral_engine._zopa_cache
        assert session_id not in neutral_engine._belief_cache

    def test_evict_nonexistent_session_is_safe(self, neutral_engine):
        """Evicting a session that never had cache entries must not raise."""
        neutral_engine.evict_session_state("nonexistent-session-id")

    def test_cache_max_size_attribute(self, neutral_engine):
        """Engine must have a _CACHE_MAX_SIZE attribute."""
        assert hasattr(neutral_engine, "_CACHE_MAX_SIZE")
        assert neutral_engine._CACHE_MAX_SIZE > 0

    def test_enforce_cache_limits_method_exists(self, neutral_engine):
        """_enforce_cache_limits method must exist."""
        assert hasattr(neutral_engine, "_enforce_cache_limits")
        assert callable(neutral_engine._enforce_cache_limits)


class TestAgentDriverSingleton:
    """§7.2: get_agent_driver() returns a singleton."""

    def test_get_agent_driver_returns_same_instance(self):
        from src.negotiation.infrastructure.llm_agent_driver import get_agent_driver
        driver1 = get_agent_driver()
        driver2 = get_agent_driver()
        assert driver1 is driver2, "get_agent_driver() returned different instances — not a singleton"

    def test_singleton_variable_exists(self):
        from src.negotiation.infrastructure import llm_agent_driver
        assert hasattr(llm_agent_driver, "_agent_driver_singleton")


class TestLLMRateLimiter:
    """§7.8: Module-level semaphore must exist."""

    def test_semaphore_exists(self):
        from src.negotiation.infrastructure import llm_agent_driver
        assert hasattr(llm_agent_driver, "_llm_semaphore")

    def test_semaphore_has_bound(self):
        import asyncio
        from src.negotiation.infrastructure.llm_agent_driver import _llm_semaphore
        assert isinstance(_llm_semaphore, asyncio.Semaphore)
