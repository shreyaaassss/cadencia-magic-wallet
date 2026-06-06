"""Tests for §10: Security and information leak fixes — I1 through I7.

These are unit/structural tests that verify the fixes exist in code.
Integration tests (with auth tokens + live sessions) are in integration/.
"""
from __future__ import annotations

import re
import uuid
from decimal import Decimal
from unittest.mock import MagicMock

import pytest


class TestI1IntelligenceRoleFilter:
    """I1: /intelligence must return role-filtered response."""

    def test_redact_function_exists_in_router(self):
        """The role-filtering logic must exist in the router module."""
        from src.negotiation.api import router
        # The endpoint function should exist
        assert hasattr(router, "get_intelligence")

    def test_intelligence_response_excludes_raw_beliefs(self):
        """Verify the intelligence endpoint function filters response."""
        # We can't easily call the endpoint without a running app,
        # but we can verify the response structure via code inspection.
        import inspect
        from src.negotiation.api.router import get_intelligence
        source = inspect.getsource(get_intelligence)
        # Must contain role-filtering logic
        assert "opponent_classification" in source, "Intelligence endpoint missing role-filter"
        assert "your_intelligence" in source, "Intelligence endpoint missing own-intelligence return"


class TestI2DealQualityScoreRedaction:
    """I2: deal_quality_score must be redacted per party."""

    def test_redact_deal_quality_for_buyer(self):
        from src.negotiation.api.router import _redact_deal_quality_for_party
        dqs = {
            "score": 0.65,
            "buyer_surplus_inr": 50000,
            "seller_surplus_inr": 80000,
            "zopa_width_inr": 130000,
            "zopa_position_pct": 38,
            "agreed_price_inr": 900000,
        }
        result = _redact_deal_quality_for_party(dqs, is_buyer=True)
        assert "your_savings_inr" in result
        assert "seller_surplus_inr" not in result
        assert "zopa_width_inr" not in result
        assert result["agreed_price_inr"] == 900000

    def test_redact_deal_quality_for_seller(self):
        from src.negotiation.api.router import _redact_deal_quality_for_party
        dqs = {
            "score": 0.65,
            "buyer_surplus_inr": 50000,
            "seller_surplus_inr": 80000,
            "zopa_width_inr": 130000,
            "agreed_price_inr": 900000,
        }
        result = _redact_deal_quality_for_party(dqs, is_buyer=False)
        assert "your_margin_inr" in result
        assert "buyer_surplus_inr" not in result
        assert "zopa_width_inr" not in result

    def test_redact_none_dqs(self):
        from src.negotiation.api.router import _redact_deal_quality_for_party
        assert _redact_deal_quality_for_party(None, True) is None

    def test_redact_float_dqs(self):
        from src.negotiation.api.router import _redact_deal_quality_for_party
        assert _redact_deal_quality_for_party(0.75, True) == 0.75


class TestI3WalkAwayReasoningRedaction:
    """I3: WALK_AWAY reasoning must not contain exact INR amounts."""

    def test_no_zopa_offer_reasoning_generic(self, neutral_engine):
        """_create_no_zopa_offer must produce generic reasoning."""
        from src.negotiation.domain.session import NegotiationSession
        from src.negotiation.domain.offer import ProposerRole

        session = NegotiationSession(
            rfq_id=uuid.uuid4(),
            match_id=uuid.uuid4(),
            buyer_enterprise_id=uuid.uuid4(),
            seller_enterprise_id=uuid.uuid4(),
        )
        offer = neutral_engine._create_no_zopa_offer(
            session=session,
            role=ProposerRole.BUYER,
            seller_target=Decimal("850000"),
            buyer_ceiling=Decimal("700000"),
            seller_floor=Decimal("850000"),
        )
        reasoning = offer.agent_reasoning or ""
        # Must NOT contain exact INR amounts
        price_pattern = re.compile(r"\u20b9[\d,]+")
        assert not price_pattern.search(reasoning), \
            f"WALK_AWAY reasoning leaks exact prices: {reasoning[:200]}"
        # Must still contain WALK_AWAY prefix for routing
        assert "WALK_AWAY" in reasoning


class TestI4BuyerBudgetNotInSellerValuation:
    """I4: Seller's cost_basis must not use buyer's budget_max when qty parse fails."""

    def test_seller_valuation_uses_catalogue_price(self):
        from src.negotiation.domain.valuation import compute_seller_valuation_from_catalogue
        val = compute_seller_valuation_from_catalogue(
            catalogue_price=Decimal("55000"),
            margin_floor=Decimal("10"),
            risk_appetite="MEDIUM",
        )
        # Reservation must be derived from catalogue_price (55000),
        # not from any buyer budget
        assert val.reservation_price >= Decimal("40000")
        assert val.reservation_price <= Decimal("60000")


class TestI5ZOPAMidpointAsymmetric:
    """I5: ZOPA hint must use per-role anchors, not symmetric midpoint."""

    def test_zopa_midpoint_key_removed(self):
        """The 'zopa_midpoint_hint_inr' key must not be injected anymore."""
        import inspect
        from src.negotiation.infrastructure.neutral_engine import NeutralEngine
        source = inspect.getsource(NeutralEngine.process_turn)
        assert "zopa_midpoint_hint_inr" not in source, \
            "Symmetric ZOPA midpoint still injected — I5 fix not applied"
        assert "fairness_anchor_inr" in source, \
            "Asymmetric fairness anchor not found — I5 fix not applied"


class TestI6AgentReasoningRoleFilter:
    """I6: agent_reasoning must be role-filtered in _session_to_response."""

    def test_session_to_response_filters_opponent_reasoning(self):
        """_session_to_response must redact opponent's agent_reasoning."""
        import inspect
        from src.negotiation.api.router import _session_to_response
        source = inspect.getsource(_session_to_response)
        assert "viewer_role" in source, "viewer_role not used in _session_to_response"
        assert "viewer_enterprise_id" in source, \
            "viewer_enterprise_id parameter not found"


class TestI7RAGRoleIsolation:
    """I7: RAG retrieval must filter by role."""

    def test_retrieve_context_accepts_role_param(self):
        """retrieve_context_for_negotiation must accept role parameter."""
        import inspect
        from src.negotiation.application.personalization_service import PersonalizationService
        sig = inspect.signature(PersonalizationService.retrieve_context_for_negotiation)
        assert "role" in sig.parameters, "role parameter missing from retrieve_context_for_negotiation"

    def test_retrieve_similar_accepts_role_param(self):
        """memory_repo.retrieve_similar must accept role parameter."""
        import inspect
        from src.negotiation.infrastructure.repositories import PostgresAgentMemoryRepository
        sig = inspect.signature(PostgresAgentMemoryRepository.retrieve_similar)
        assert "role" in sig.parameters, "role parameter missing from retrieve_similar"

    def test_retrieve_command_has_role_field(self):
        """RetrieveMemoryCommand must have role field."""
        from src.negotiation.application.commands import RetrieveMemoryCommand
        cmd = RetrieveMemoryCommand(tenant_id=uuid.uuid4(), query="test", role="buyer")
        assert cmd.role == "buyer"
