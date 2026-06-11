# Negotiation Engine — Mandatory Unit Tests
# Tests the full engine pipeline: session lifecycle, turn execution,
# convergence detection, stall recovery, and agent coordination.
# Pure domain logic — no DB, no I/O.

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.negotiation.domain.offer import Offer, ProposerRole
from src.negotiation.domain.session import (
    MAX_ROUNDS,
    NegotiationSession,
    SessionStatus,
)
from src.negotiation.domain.strategy import StrategyEngine, StrategyType
from src.negotiation.domain.valuation import compute_buyer_valuation, compute_seller_valuation
from src.negotiation.domain.value_objects import OfferValue, RoundNumber
from src.shared.domain.exceptions import ConflictError, PolicyViolation


# ═════════════════════════════════════════════════════════════════════════════
# Helper factories
# ═════════════════════════════════════════════════════════════════════════════

def _session(status=SessionStatus.INIT) -> NegotiationSession:
    return NegotiationSession(
        rfq_id=uuid.uuid4(),
        match_id=uuid.uuid4(),
        buyer_enterprise_id=uuid.uuid4(),
        seller_enterprise_id=uuid.uuid4(),
        status=status,
    )


def _offer(session_id, role=ProposerRole.BUYER, price=50000, round_num=1):
    return Offer.create_agent_offer(
        session_id=session_id,
        round_number=round_num,
        proposer_role=role,
        price=Decimal(str(price)),
        currency="INR",
        terms={},
        confidence=0.8,
        agent_reasoning="engine test",
    )


# ═════════════════════════════════════════════════════════════════════════════
# 1. Session Lifecycle — DANP FSM Completeness
# ═════════════════════════════════════════════════════════════════════════════

class TestSessionLifecycleCompleteness:
    """Every valid FSM path must work without error."""

    def test_happy_path_init_to_agreed(self):
        """INIT → SELLER_ANCHOR → SELLER_RESPONSE → ROUND_LOOP → AGREED."""
        s = _session()
        s.activate()
        assert s.status == SessionStatus.SELLER_ANCHOR

        # Seller anchor offer
        s.add_offer(_offer(s.id, ProposerRole.SELLER, 60000, 1))
        assert s.status == SessionStatus.BUYER_RESPONSE

        # Buyer response
        s.add_offer(_offer(s.id, ProposerRole.BUYER, 55000, 2))
        assert s.status == SessionStatus.ROUND_LOOP

        # Converge and agree
        s.mark_agreed(OfferValue(amount=Decimal("57500"), currency="INR"), {"payment": "LC"})
        assert s.status == SessionStatus.AGREED
        assert s.agreed_price.amount == Decimal("57500")

    def test_walk_away_path(self):
        """Session can be walked away from any active state."""
        s = _session(SessionStatus.ROUND_LOOP)
        event = s.mark_walk_away("No convergence after 10 rounds")
        assert s.status == SessionStatus.WALK_AWAY
        assert s.status.is_terminal

    def test_timeout_path(self):
        s = _session(SessionStatus.ROUND_LOOP)
        s.mark_timeout()
        assert s.status == SessionStatus.TIMEOUT
        assert s.status.is_terminal

    def test_policy_breach_path(self):
        s = _session(SessionStatus.ROUND_LOOP)
        s.mark_policy_breach("3 consecutive schema failures")
        assert s.status == SessionStatus.POLICY_BREACH
        assert s.status.is_terminal

    def test_stall_to_human_review_to_resume(self):
        """ROUND_LOOP → STALLED → HUMAN_REVIEW → ROUND_LOOP."""
        s = _session(SessionStatus.ROUND_LOOP)
        s.mark_stalled()
        assert s.status == SessionStatus.STALLED

        s.escalate_to_human_review()
        assert s.status == SessionStatus.HUMAN_REVIEW

        # Add offers so resume goes to ROUND_LOOP
        s.offers = [
            _offer(s.id, ProposerRole.BUYER, 50000, 1),
            _offer(s.id, ProposerRole.SELLER, 55000, 2),
        ]
        s.resume_from_human_review()
        assert s.status == SessionStatus.ROUND_LOOP

    def test_closed_by_buyer_is_terminal(self):
        assert SessionStatus.CLOSED_BY_BUYER.is_terminal is True
        assert SessionStatus.CLOSED_BY_BUYER.is_active is False


# ═════════════════════════════════════════════════════════════════════════════
# 2. Turn Execution Guards
# ═════════════════════════════════════════════════════════════════════════════

class TestTurnExecutionGuards:
    """Verify all safety checks during offer submission."""

    def test_cannot_add_offer_to_agreed_session(self):
        s = _session(SessionStatus.AGREED)
        with pytest.raises(ConflictError, match="active state"):
            s.add_offer(_offer(s.id))

    def test_cannot_add_offer_to_expired_session(self):
        s = _session(SessionStatus.EXPIRED)
        with pytest.raises(ConflictError, match="active state"):
            s.add_offer(_offer(s.id))

    def test_cannot_add_offer_to_closed_by_buyer(self):
        s = _session(SessionStatus.CLOSED_BY_BUYER)
        with pytest.raises(ConflictError):
            s.add_offer(_offer(s.id))

    def test_max_rounds_enforced(self):
        s = _session(SessionStatus.ROUND_LOOP)
        for i in range(MAX_ROUNDS):
            role = ProposerRole.BUYER if i % 2 == 0 else ProposerRole.SELLER
            s.add_offer(_offer(s.id, role, 50000 + i * 100, i + 1))

        with pytest.raises(ConflictError, match="max rounds"):
            s.add_offer(_offer(s.id, round_num=MAX_ROUNDS + 1))

    def test_mismatched_session_id_rejected(self):
        s = _session(SessionStatus.BUYER_ANCHOR)
        wrong_offer = _offer(uuid.uuid4())  # different session
        with pytest.raises(ConflictError, match="does not match"):
            s.add_offer(wrong_offer)

    def test_round_count_increments_correctly(self):
        s = _session(SessionStatus.BUYER_ANCHOR)
        assert s.round_count.value == 0
        s.add_offer(_offer(s.id, ProposerRole.BUYER, 50000, 1))
        assert s.round_count.value == 1
        s.add_offer(_offer(s.id, ProposerRole.SELLER, 55000, 2))
        assert s.round_count.value == 2


# ═════════════════════════════════════════════════════════════════════════════
# 3. Convergence Detection
# ═════════════════════════════════════════════════════════════════════════════

class TestConvergenceDetection:
    """Price gap convergence must trigger agreement correctly."""

    def test_convergence_within_2_percent(self):
        s = _session(SessionStatus.ROUND_LOOP)
        buyer = Offer.create_agent_offer(
            session_id=s.id, round_number=1, proposer_role=ProposerRole.BUYER,
            price=Decimal("99000"), currency="INR", terms={}, confidence=0.9,
            agent_reasoning="close",
        )
        seller = Offer.create_agent_offer(
            session_id=s.id, round_number=2, proposer_role=ProposerRole.SELLER,
            price=Decimal("100000"), currency="INR", terms={}, confidence=0.9,
            agent_reasoning="close",
        )
        s.offers = [buyer, seller]
        assert s.check_convergence(tolerance=0.02) is True

    def test_no_convergence_10_percent_gap(self):
        s = _session(SessionStatus.ROUND_LOOP)
        buyer = Offer.create_agent_offer(
            session_id=s.id, round_number=1, proposer_role=ProposerRole.BUYER,
            price=Decimal("90000"), currency="INR", terms={}, confidence=0.8,
            agent_reasoning="far",
        )
        seller = Offer.create_agent_offer(
            session_id=s.id, round_number=2, proposer_role=ProposerRole.SELLER,
            price=Decimal("100000"), currency="INR", terms={}, confidence=0.8,
            agent_reasoning="far",
        )
        s.offers = [buyer, seller]
        assert s.check_convergence(tolerance=0.02) is False

    def test_convergence_exact_match(self):
        s = _session(SessionStatus.ROUND_LOOP)
        buyer = Offer.create_agent_offer(
            session_id=s.id, round_number=3, proposer_role=ProposerRole.BUYER,
            price=Decimal("50000"), currency="INR", terms={}, confidence=0.95,
            agent_reasoning="exact",
        )
        seller = Offer.create_agent_offer(
            session_id=s.id, round_number=4, proposer_role=ProposerRole.SELLER,
            price=Decimal("50000"), currency="INR", terms={}, confidence=0.95,
            agent_reasoning="exact",
        )
        s.offers = [buyer, seller]
        assert s.check_convergence(tolerance=0.02) is True

    def test_convergence_requires_both_offers(self):
        s = _session(SessionStatus.ROUND_LOOP)
        buyer_only = Offer.create_agent_offer(
            session_id=s.id, round_number=1, proposer_role=ProposerRole.BUYER,
            price=Decimal("50000"), currency="INR", terms={}, confidence=0.8,
            agent_reasoning="alone",
        )
        s.offers = [buyer_only]
        assert s.check_convergence(tolerance=0.02) is False


# ═════════════════════════════════════════════════════════════════════════════
# 4. Stall Detection & Recovery
# ═════════════════════════════════════════════════════════════════════════════

class TestStallDetection:
    """Stall counter must trigger escalation at threshold."""

    def test_stall_counter_increments(self):
        s = _session()
        assert s.stall_counter == 0
        s.record_no_concession()
        assert s.stall_counter == 1
        s.record_no_concession()
        assert s.stall_counter == 2

    def test_stall_triggers_at_threshold_3(self):
        s = _session()
        assert s.record_no_concession() is False  # 1
        assert s.record_no_concession() is False  # 2
        assert s.record_no_concession() is True   # 3 → stalled

    def test_concession_resets_stall_counter(self):
        s = _session()
        s.record_no_concession()
        s.record_no_concession()
        s.reset_stall_counter()
        assert s.stall_counter == 0
        # Need 3 more to trigger
        assert s.record_no_concession() is False

    def test_schema_failure_triggers_policy_breach(self):
        s = _session()
        assert s.record_schema_failure() is False  # 1
        assert s.record_schema_failure() is False  # 2
        assert s.record_schema_failure() is True   # 3 → breach


# ═════════════════════════════════════════════════════════════════════════════
# 5. Strategy Engine Integration
# ═════════════════════════════════════════════════════════════════════════════

class TestStrategyEngineIntegration:
    """Strategy engine must produce valid prices for all scenarios."""

    def test_opening_anchor_is_aggressive(self):
        engine = StrategyEngine(max_rounds=15)
        rec = engine.select_strategy(
            round_num=0,
            my_last_price=None,
            opponent_last_price=None,
            reservation_price=Decimal("110000"),
            target_price=Decimal("95000"),
            is_buyer=True,
        )
        assert rec.strategy == StrategyType.STRONG_ANCHOR
        assert rec.suggested_price > 0

    def test_cooperative_opponent_gets_tit_for_tat(self):
        engine = StrategyEngine(max_rounds=15)
        rec = engine.select_strategy(
            round_num=5,
            my_last_price=Decimal("95000"),
            opponent_last_price=Decimal("100000"),
            reservation_price=Decimal("110000"),
            target_price=Decimal("90000"),
            opponent_flexibility=0.8,
            is_buyer=True,
        )
        assert rec.strategy == StrategyType.TIT_FOR_TAT

    def test_last_round_is_ultimatum(self):
        engine = StrategyEngine(max_rounds=15)
        rec = engine.select_strategy(
            round_num=14,
            my_last_price=Decimal("95000"),
            opponent_last_price=Decimal("105000"),
            reservation_price=Decimal("110000"),
            target_price=Decimal("90000"),
            is_buyer=True,
        )
        assert rec.strategy == StrategyType.ULTIMATUM

    def test_price_never_exceeds_reservation_for_buyer(self):
        engine = StrategyEngine(max_rounds=15)
        for r in range(15):
            rec = engine.select_strategy(
                round_num=r,
                my_last_price=Decimal("90000") + Decimal(str(r * 1000)),
                opponent_last_price=Decimal("120000") - Decimal(str(r * 500)),
                reservation_price=Decimal("110000"),
                target_price=Decimal("85000"),
                is_buyer=True,
            )
            if rec.suggested_price:
                assert rec.suggested_price <= Decimal("110000"), (
                    f"Round {r}: price {rec.suggested_price} exceeds reservation 110000"
                )


# ═════════════════════════════════════════════════════════════════════════════
# 6. Valuation Consistency
# ═════════════════════════════════════════════════════════════════════════════

class TestValuationConsistency:
    """Buyer and seller valuations must produce consistent negotiation zones."""

    def test_buyer_reservation_above_seller_reservation_creates_zone(self):
        """If buyer willing to pay more than seller's minimum, a deal is possible."""
        buyer_v = compute_buyer_valuation(Decimal("100000"), risk_appetite="MEDIUM")
        seller_v = compute_seller_valuation(Decimal("70000"), margin_floor=Decimal("10"))
        # Buyer's reservation (max willing to pay) should be above seller's
        # reservation (min willing to accept) for a viable trade
        assert buyer_v.reservation_price > seller_v.reservation_price

    def test_buyer_target_differs_from_reservation(self):
        """Buyer target and reservation prices must be distinct."""
        v = compute_buyer_valuation(Decimal("100000"), risk_appetite="MEDIUM")
        assert v.target_price != v.reservation_price

    def test_seller_target_above_reservation(self):
        """Seller wants more (target) than the minimum they'd accept (reservation)."""
        v = compute_seller_valuation(Decimal("80000"), margin_floor=Decimal("10"))
        assert v.target_price > v.reservation_price

    def test_high_risk_buyer_has_lower_reservation(self):
        """Higher risk tolerance → buyer willing to pay less."""
        low = compute_buyer_valuation(Decimal("100000"), risk_appetite="LOW")
        high = compute_buyer_valuation(Decimal("100000"), risk_appetite="HIGH")
        assert high.reservation_price < low.reservation_price


# ═════════════════════════════════════════════════════════════════════════════
# 7. Multi-Round Simulation
# ═════════════════════════════════════════════════════════════════════════════

class TestMultiRoundSimulation:
    """Simulate a realistic multi-round negotiation at the domain level."""

    def test_10_round_alternating_offers(self):
        """10 rounds of alternating buyer/seller offers should not crash."""
        s = _session()
        s.activate()

        prices_buyer = [45000, 47000, 49000, 50000, 51000]
        prices_seller = [60000, 57000, 54000, 52000, 51500]

        for i in range(10):
            if i % 2 == 0:
                price = prices_seller[min(i // 2, 4)]
                role = ProposerRole.SELLER
            else:
                price = prices_buyer[min(i // 2, 4)]
                role = ProposerRole.BUYER
            s.add_offer(_offer(s.id, role, price, i + 1))

        assert s.round_count.value == 10
        assert s.status.is_active

    def test_converge_and_agree_mid_session(self):
        """Simulate natural convergence → agreement."""
        s = _session()
        s.activate()

        # Seller anchors high
        s.add_offer(_offer(s.id, ProposerRole.SELLER, 60000, 1))
        # Buyer counters low
        s.add_offer(_offer(s.id, ProposerRole.BUYER, 45000, 2))
        # Seller concedes
        s.add_offer(_offer(s.id, ProposerRole.SELLER, 55000, 3))
        # Buyer concedes
        s.add_offer(_offer(s.id, ProposerRole.BUYER, 50000, 4))
        # Seller final
        s.add_offer(_offer(s.id, ProposerRole.SELLER, 51000, 5))
        # Buyer final
        s.add_offer(_offer(s.id, ProposerRole.BUYER, 50500, 6))

        # Check convergence (1% gap)
        assert s.check_convergence(tolerance=0.02) is True

        # Agree
        agreed_price = OfferValue(amount=Decimal("50750"), currency="INR")
        event = s.mark_agreed(agreed_price, {"payment": "NET_30"})
        assert s.status == SessionStatus.AGREED
        assert event.agreed_price == Decimal("50750")

    def test_no_agreement_when_far_apart(self):
        """If prices don't converge, session stays active."""
        s = _session()
        s.activate()

        # Both sides stay far apart
        s.add_offer(_offer(s.id, ProposerRole.SELLER, 100000, 1))
        s.add_offer(_offer(s.id, ProposerRole.BUYER, 40000, 2))
        s.add_offer(_offer(s.id, ProposerRole.SELLER, 99000, 3))
        s.add_offer(_offer(s.id, ProposerRole.BUYER, 41000, 4))

        assert s.check_convergence(tolerance=0.02) is False
        assert s.status.is_active


# ═════════════════════════════════════════════════════════════════════════════
# 8. Event Publishing Isolation
# ═════════════════════════════════════════════════════════════════════════════

class TestEventPublisherIsolation:
    """Event publisher errors must NOT propagate to callers."""

    @pytest.mark.asyncio
    async def test_publisher_swallows_handler_errors(self):
        from src.shared.infrastructure.events.publisher import EventPublisher
        from src.negotiation.domain.events import OfferSubmitted

        publisher = EventPublisher()

        # Register a handler that throws
        async def bad_handler(event):
            raise RuntimeError("handler crash")

        publisher.subscribe("OfferSubmitted", bad_handler)

        # Publishing should NOT raise
        event = OfferSubmitted(
            aggregate_id=uuid.uuid4(),
            event_type="OfferSubmitted",
            session_id=uuid.uuid4(),
            offer_id=uuid.uuid4(),
            round_number=1,
            proposer_role="BUYER",
            price=Decimal("50000"),
        )
        await publisher.publish(event)  # Should not raise

    @pytest.mark.asyncio
    async def test_publisher_calls_all_handlers_even_after_failure(self):
        from src.shared.infrastructure.events.publisher import EventPublisher
        from src.negotiation.domain.events import SessionAgreed

        publisher = EventPublisher()
        call_log = []

        async def handler_a(event):
            raise RuntimeError("A fails")

        async def handler_b(event):
            call_log.append("B")

        publisher.subscribe("SessionAgreed", handler_a)
        publisher.subscribe("SessionAgreed", handler_b)

        event = SessionAgreed(
            aggregate_id=uuid.uuid4(),
            event_type="SessionAgreed",
            session_id=uuid.uuid4(),
            agreed_price=Decimal("50000"),
        )
        await publisher.publish(event)
        assert "B" in call_log, "Handler B should run even though A failed"
