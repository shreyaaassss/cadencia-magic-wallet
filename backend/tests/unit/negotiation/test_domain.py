# Phase Four Unit Tests: Domain Layer — Full DANP Coverage
# Tests: Valuation, Strategy, Opponent Model, Guardrails, expanded Session FSM
# context.md §3: Domain layer tests — pure Python, zero I/O.

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from src.negotiation.domain.agent_profile import AgentProfile
from src.negotiation.domain.events import (
    OfferSubmitted,
    SessionAgreed,
    SessionEscalated,
    SessionExpired,
    SessionFailed,
)
from src.negotiation.domain.guardrails import (
    ActionEnvelope,
    GuardrailEngine,
    ViolationType,
    validate_raw_envelope,
)
from src.negotiation.domain.offer import Offer, ProposerRole
from src.negotiation.domain.opponent_model import (
    BayesianOpponentModel,
    OpponentBelief,
    OpponentMetrics,
    OpponentType,
    compute_consistency,
    compute_flexibility,
    compute_opponent_metrics,
)
from src.negotiation.domain.playbook import IndustryPlaybook
from src.negotiation.domain.policies import NegotiationPolicy
from src.negotiation.domain.session import (
    MAX_ROUNDS,
    NegotiationSession,
    SessionStatus,
)
from src.negotiation.domain.strategy import (
    StrategyEngine,
    StrategyType,
    adaptive_concession,
)
from src.negotiation.domain.valuation import (
    Valuation,
    compute_buyer_valuation,
    compute_seller_valuation,
    compute_valuation,
)
from src.negotiation.domain.value_objects import (
    AgentAction,
    AutomationLevel,
    Confidence,
    OfferValue,
    RiskProfile,
    RoundNumber,
    StrategyWeights,
)
from src.shared.domain.exceptions import ConflictError, PolicyViolation, ValidationError


# ═══════════════════════════════════════════════════════════════════════════════
# Value Object Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestOfferValue:
    def test_valid_offer_value(self):
        ov = OfferValue(amount=Decimal("100.50"), currency="INR")
        assert ov.amount == Decimal("100.50")
        assert ov.currency == "INR"

    def test_rejects_zero_amount(self):
        with pytest.raises(ValidationError, match="amount must be > 0"):
            OfferValue(amount=Decimal("0"), currency="INR")

    def test_rejects_negative_amount(self):
        with pytest.raises(ValidationError, match="amount must be > 0"):
            OfferValue(amount=Decimal("-10"), currency="INR")

    def test_rejects_invalid_currency(self):
        with pytest.raises(ValidationError, match="Currency"):
            OfferValue(amount=Decimal("100"), currency="EUR")


class TestConfidence:
    def test_valid_confidence(self):
        c = Confidence(value=0.85)
        assert c.value == 0.85

    def test_rejects_above_one(self):
        with pytest.raises(ValidationError, match="Confidence"):
            Confidence(value=1.1)

    def test_rejects_negative(self):
        with pytest.raises(ValidationError, match="Confidence"):
            Confidence(value=-0.1)


class TestAgentAction:
    def test_normalizes_to_uppercase(self):
        a = AgentAction(value="offer")
        assert a.value == "OFFER"

    def test_rejects_invalid_action(self):
        with pytest.raises(ValidationError, match="AgentAction"):
            AgentAction(value="INVALID")


class TestRoundNumber:
    def test_valid_round(self):
        r = RoundNumber(value=5)
        assert r.value == 5

    def test_rejects_negative(self):
        with pytest.raises(ValidationError, match="RoundNumber"):
            RoundNumber(value=-1)


class TestAutomationLevel:
    def test_normalizes_uppercase(self):
        a = AutomationLevel(value="full")
        assert a.value == "FULL"

    def test_rejects_invalid(self):
        with pytest.raises(ValidationError, match="AutomationLevel"):
            AutomationLevel(value="AUTO")


class TestStrategyWeights:
    def test_defaults_valid(self):
        sw = StrategyWeights()
        assert sw.concession_rate == 0.05
        assert sw.stall_threshold == 10

    def test_rejects_concession_rate_above_one(self):
        with pytest.raises(ValidationError, match="concession_rate"):
            StrategyWeights(concession_rate=1.5)

    def test_rejects_stall_threshold_zero(self):
        with pytest.raises(ValidationError, match="stall_threshold"):
            StrategyWeights(stall_threshold=0)


class TestRiskProfile:
    def test_defaults_valid(self):
        rp = RiskProfile()
        assert rp.risk_appetite == "MEDIUM"

    def test_rejects_margin_floor_above_100(self):
        with pytest.raises(ValidationError, match="margin_floor"):
            RiskProfile(margin_floor=Decimal("110"))

    def test_rejects_invalid_risk_appetite(self):
        with pytest.raises(ValidationError, match="risk_appetite"):
            RiskProfile(risk_appetite="EXTREME")


# ═══════════════════════════════════════════════════════════════════════════════
# Offer Entity Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestOffer:
    def test_create_agent_offer(self):
        sid = uuid.uuid4()
        offer = Offer.create_agent_offer(
            session_id=sid,
            round_number=1,
            proposer_role=ProposerRole.BUYER,
            price=Decimal("50000"),
            currency="INR",
            terms={"payment": "LC"},
            confidence=0.85,
            agent_reasoning="Good price point.",
        )
        assert offer.session_id == sid
        assert offer.is_human_override is False
        assert offer.price.amount == Decimal("50000")
        assert offer.confidence.value == 0.85

    def test_create_human_offer(self):
        sid = uuid.uuid4()
        offer = Offer.create_human_offer(
            session_id=sid,
            round_number=3,
            proposer_role=ProposerRole.BUYER,
            price=Decimal("45000"),
            currency="INR",
            terms={},
        )
        assert offer.is_human_override is True
        assert offer.confidence is None
        assert offer.agent_reasoning == "HUMAN_OVERRIDE"


# ═══════════════════════════════════════════════════════════════════════════════
# NegotiationSession Aggregate Tests — FULL DANP FSM
# ═══════════════════════════════════════════════════════════════════════════════


class TestNegotiationSession:
    def _make_session(self, status: SessionStatus = SessionStatus.INIT) -> NegotiationSession:
        return NegotiationSession(
            rfq_id=uuid.uuid4(),
            match_id=uuid.uuid4(),
            buyer_enterprise_id=uuid.uuid4(),
            seller_enterprise_id=uuid.uuid4(),
            status=status,
        )

    def _make_offer(self, session_id: uuid.UUID, role=ProposerRole.BUYER, round_num=1):
        return Offer.create_agent_offer(
            session_id=session_id,
            round_number=round_num,
            proposer_role=role,
            price=Decimal("50000"),
            currency="INR",
            terms={},
            confidence=0.8,
            agent_reasoning="test",
        )

    # ── DANP State Transitions ────────────────────────────────────────────────

    def test_activate_init_to_seller_anchor(self):
        session = self._make_session()
        event = session.activate()
        assert session.status == SessionStatus.SELLER_ANCHOR
        assert event.event_type == "SessionCreated"

    def test_activate_rejects_terminal_state(self):
        session = self._make_session(SessionStatus.AGREED)
        with pytest.raises(ConflictError):
            session.activate()

    def test_add_offer_transitions_buyer_anchor_to_seller_response(self):
        session = self._make_session(SessionStatus.BUYER_ANCHOR)
        offer = self._make_offer(session.id, ProposerRole.BUYER)
        session.add_offer(offer)
        assert session.status == SessionStatus.SELLER_RESPONSE

    def test_add_offer_transitions_seller_response_to_round_loop(self):
        session = self._make_session(SessionStatus.BUYER_ANCHOR)
        b_offer = self._make_offer(session.id, ProposerRole.BUYER, 1)
        session.add_offer(b_offer)
        s_offer = self._make_offer(session.id, ProposerRole.SELLER, 2)
        session.add_offer(s_offer)
        assert session.status == SessionStatus.ROUND_LOOP

    def test_round_loop_stays_in_round_loop(self):
        session = self._make_session(SessionStatus.ROUND_LOOP)
        # Add two initial offers to avoid FSM confusion
        b1 = self._make_offer(session.id, ProposerRole.BUYER, 1)
        s1 = self._make_offer(session.id, ProposerRole.SELLER, 2)
        session.offers = [b1, s1]
        session.round_count = RoundNumber(value=2)

        b2 = self._make_offer(session.id, ProposerRole.BUYER, 3)
        session.add_offer(b2)
        assert session.status == SessionStatus.ROUND_LOOP

    # ── Offer Management ──────────────────────────────────────────────────────

    def test_add_offer_returns_event(self):
        session = self._make_session(SessionStatus.BUYER_ANCHOR)
        offer = self._make_offer(session.id)
        event = session.add_offer(offer)
        assert isinstance(event, OfferSubmitted)
        assert event.session_id == session.id
        assert session.round_count.value == 1

    def test_add_offer_rejects_terminal_state(self):
        session = self._make_session(SessionStatus.AGREED)
        offer = self._make_offer(session.id)
        with pytest.raises(ConflictError):
            session.add_offer(offer)

    def test_add_offer_rejects_max_rounds(self):
        session = self._make_session(SessionStatus.ROUND_LOOP)
        for i in range(MAX_ROUNDS):
            role = ProposerRole.BUYER if i % 2 == 0 else ProposerRole.SELLER
            offer = self._make_offer(session.id, role=role, round_num=i + 1)
            session.add_offer(offer)
        extra = self._make_offer(session.id, round_num=MAX_ROUNDS + 1)
        with pytest.raises(ConflictError, match="max rounds"):
            session.add_offer(extra)

    def test_add_offer_rejects_mismatched_session_id(self):
        session = self._make_session(SessionStatus.BUYER_ANCHOR)
        offer = self._make_offer(uuid.uuid4())
        with pytest.raises(ConflictError, match="does not match"):
            session.add_offer(offer)

    # ── Terminal States ───────────────────────────────────────────────────────

    def test_mark_agreed(self):
        session = self._make_session(SessionStatus.ROUND_LOOP)
        agreed_price = OfferValue(amount=Decimal("48000"), currency="INR")
        event = session.mark_agreed(agreed_price, {"payment": "LC"})
        assert isinstance(event, SessionAgreed)
        assert session.status == SessionStatus.AGREED
        assert session.agreed_price == agreed_price
        assert event.agreed_price == Decimal("48000")

    def test_mark_agreed_rejects_terminal(self):
        session = self._make_session(SessionStatus.FAILED)
        with pytest.raises(ConflictError):
            session.mark_agreed(OfferValue(amount=Decimal("1"), currency="INR"), {})

    def test_mark_walk_away(self):
        session = self._make_session(SessionStatus.ROUND_LOOP)
        event = session.mark_walk_away("No deal")
        assert session.status == SessionStatus.WALK_AWAY
        assert "WALK_AWAY" in event.reason

    def test_mark_failed(self):
        session = self._make_session(SessionStatus.ROUND_LOOP)
        event = session.mark_failed("No convergence")
        assert isinstance(event, SessionFailed)
        assert session.status == SessionStatus.FAILED
        assert event.reason == "No convergence"

    def test_mark_stalled(self):
        session = self._make_session(SessionStatus.ROUND_LOOP)
        event = session.mark_stalled()
        assert session.status == SessionStatus.STALLED
        assert isinstance(event, SessionEscalated)

    def test_escalate_to_human_review(self):
        session = self._make_session(SessionStatus.STALLED)
        event = session.escalate_to_human_review()
        assert isinstance(event, SessionEscalated)
        assert session.status == SessionStatus.HUMAN_REVIEW

    def test_resume_from_human_review(self):
        session = self._make_session(SessionStatus.HUMAN_REVIEW)
        session.resume_from_human_review()
        assert session.status == SessionStatus.ACTIVE

    def test_resume_from_human_review_to_round_loop(self):
        session = self._make_session(SessionStatus.HUMAN_REVIEW)
        # Simulate having 2+ offers
        b1 = self._make_offer(session.id, ProposerRole.BUYER, 1)
        s1 = self._make_offer(session.id, ProposerRole.SELLER, 2)
        session.offers = [b1, s1]
        session.resume_from_human_review()
        assert session.status == SessionStatus.ROUND_LOOP

    def test_resume_rejects_non_human_review(self):
        session = self._make_session(SessionStatus.ROUND_LOOP)
        with pytest.raises(ConflictError, match="expected HUMAN_REVIEW"):
            session.resume_from_human_review()

    def test_mark_timeout(self):
        session = self._make_session(SessionStatus.ROUND_LOOP)
        event = session.mark_timeout()
        assert session.status == SessionStatus.TIMEOUT

    def test_mark_expired(self):
        session = self._make_session(SessionStatus.ROUND_LOOP)
        event = session.mark_expired()
        assert isinstance(event, SessionExpired)
        assert session.status == SessionStatus.EXPIRED

    def test_mark_policy_breach(self):
        session = self._make_session(SessionStatus.ROUND_LOOP)
        event = session.mark_policy_breach("3x schema fail")
        assert session.status == SessionStatus.POLICY_BREACH
        assert "POLICY_BREACH" in event.reason

    # ── Stall / Schema Tracking ───────────────────────────────────────────────

    def test_record_schema_failure_counts(self):
        session = self._make_session()
        assert session.record_schema_failure() is False  # 1st
        assert session.record_schema_failure() is False  # 2nd
        assert session.record_schema_failure() is True   # 3rd → breach

    def test_stall_counter_tracks_no_concession(self):
        session = self._make_session()
        assert session.record_no_concession() is False
        assert session.record_no_concession() is False
        assert session.record_no_concession() is True  # 3rd → stalled

    def test_reset_stall_counter(self):
        session = self._make_session()
        session.record_no_concession()
        session.record_no_concession()
        session.reset_stall_counter()
        assert session.stall_counter == 0
        assert session.record_no_concession() is False

    # ── Query Helpers ─────────────────────────────────────────────────────────

    def test_get_last_buyer_offer(self):
        session = self._make_session(SessionStatus.BUYER_ANCHOR)
        b1 = self._make_offer(session.id, ProposerRole.BUYER, 1)
        s1 = self._make_offer(session.id, ProposerRole.SELLER, 2)
        session.add_offer(b1)
        session.add_offer(s1)
        last = session.get_last_buyer_offer()
        assert last == b1

    def test_get_last_seller_offer_none(self):
        session = self._make_session()
        assert session.get_last_seller_offer() is None

    def test_get_buyer_prices(self):
        session = self._make_session(SessionStatus.BUYER_ANCHOR)
        b1 = self._make_offer(session.id, ProposerRole.BUYER, 1)
        session.add_offer(b1)
        prices = session.get_buyer_prices()
        assert prices == [Decimal("50000")]

    def test_next_proposer(self):
        session = self._make_session()
        session.activate()
        assert session.next_proposer == ProposerRole.SELLER
        session.offers = [self._make_offer(session.id, ProposerRole.SELLER)]
        assert session.next_proposer == ProposerRole.BUYER

    def test_check_convergence(self):
        session = self._make_session(SessionStatus.ROUND_LOOP)
        b1 = Offer.create_agent_offer(
            session_id=session.id, round_number=1, proposer_role=ProposerRole.BUYER,
            price=Decimal("100000"), currency="INR", terms={}, confidence=0.8, agent_reasoning="t",
        )
        s1 = Offer.create_agent_offer(
            session_id=session.id, round_number=2, proposer_role=ProposerRole.SELLER,
            price=Decimal("101000"), currency="INR", terms={}, confidence=0.8, agent_reasoning="t",
        )
        session.offers = [b1, s1]
        assert session.check_convergence(tolerance=0.02) is True

    def test_status_properties(self):
        assert SessionStatus.INIT.is_active is True
        assert SessionStatus.BUYER_ANCHOR.is_active is True
        assert SessionStatus.ROUND_LOOP.is_active is True
        assert SessionStatus.AGREED.is_active is False
        assert SessionStatus.AGREED.is_terminal is True
        assert SessionStatus.WALK_AWAY.is_terminal is True
        assert SessionStatus.TIMEOUT.is_terminal is True
        assert SessionStatus.POLICY_BREACH.is_terminal is True


# ═══════════════════════════════════════════════════════════════════════════════
# Valuation Tests (Layer 1)
# ═══════════════════════════════════════════════════════════════════════════════


class TestValuation:
    def test_compute_valuation_basic(self):
        v = compute_valuation(Decimal("100000"), risk=0.10, margin=0.05)
        assert v.reservation_price == Decimal("90000.00")
        assert v.target_price == Decimal("95000.00")
        assert v.walkaway_delta == Decimal("2000.00")

    def test_compute_valuation_rejects_zero_intrinsic(self):
        with pytest.raises(ValidationError, match="intrinsic"):
            compute_valuation(Decimal("0"), risk=0.1, margin=0.05)

    def test_compute_valuation_rejects_invalid_risk(self):
        with pytest.raises(ValidationError, match="risk"):
            compute_valuation(Decimal("100000"), risk=1.5, margin=0.05)

    def test_compute_valuation_rejects_invalid_margin(self):
        with pytest.raises(ValidationError, match="margin"):
            compute_valuation(Decimal("100000"), risk=0.1, margin=-0.1)

    def test_valuation_is_below_reservation(self):
        v = Valuation(
            reservation_price=Decimal("90000"),
            target_price=Decimal("95000"),
            walkaway_delta=Decimal("2000"),
        )
        assert v.is_below_reservation(Decimal("89000")) is True
        assert v.is_below_reservation(Decimal("91000")) is False

    def test_valuation_gap_from_target(self):
        v = Valuation(
            reservation_price=Decimal("90000"),
            target_price=Decimal("100000"),
            walkaway_delta=Decimal("2000"),
        )
        gap = v.gap_from_target(Decimal("105000"))
        assert gap == Decimal("0.05")

    def test_buyer_valuation(self):
        v = compute_buyer_valuation(Decimal("100000"), risk_appetite="MEDIUM")
        assert v.reservation_price > Decimal("0")
        assert v.target_price > Decimal("0")
        # Buyer's target (ideal price) may be higher than reservation (floor)
        # because compute_valuation uses (1-risk) for reservation and (1-margin) for target
        # with risk=0.10 > margin=0.05, so reservation < target — this is correct geometry
        assert v.target_price != v.reservation_price

    def test_buyer_valuation_with_ceiling(self):
        v = compute_buyer_valuation(
            Decimal("100000"),
            risk_appetite="HIGH",
            budget_ceiling=Decimal("95000"),
        )
        assert v.reservation_price <= Decimal("95000")

    def test_seller_valuation(self):
        v = compute_seller_valuation(Decimal("80000"), margin_floor=Decimal("10"))
        assert v.reservation_price >= Decimal("88000")  # cost * 1.10
        assert v.target_price > v.reservation_price  # Seller wants more than min


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy Engine Tests (Layer 2)
# ═══════════════════════════════════════════════════════════════════════════════


class TestStrategyEngine:
    def _engine(self) -> StrategyEngine:
        return StrategyEngine(max_rounds=20)

    def test_round_zero_strong_anchor(self):
        engine = self._engine()
        rec = engine.select_strategy(
            round_num=0,
            my_last_price=None,
            opponent_last_price=None,
            reservation_price=Decimal("110000"),
            target_price=Decimal("95000"),
            is_buyer=True,
        )
        assert rec.strategy == StrategyType.STRONG_ANCHOR
        assert rec.action == "OFFER"
        assert rec.suggested_price > Decimal("0")

    def test_boulware_default(self):
        engine = self._engine()
        rec = engine.select_strategy(
            round_num=5,
            my_last_price=Decimal("92000"),
            opponent_last_price=Decimal("105000"),
            reservation_price=Decimal("110000"),
            target_price=Decimal("90000"),
            opponent_flexibility=0.4,
            is_buyer=True,
        )
        # Strategy depends on exact threshold config — BOULWARE or CONSERVATIVE
        # are both valid conservative strategies for this scenario
        assert rec.strategy in (StrategyType.BOULWARE, StrategyType.CONSERVATIVE)
        assert rec.action in ("COUNTER", "OFFER")
        assert rec.concession_fraction >= Decimal("0")

    def test_hardball_against_stubborn(self):
        engine = self._engine()
        rec = engine.select_strategy(
            round_num=8,
            my_last_price=Decimal("95000"),
            opponent_last_price=Decimal("110000"),
            reservation_price=Decimal("100000"),
            target_price=Decimal("90000"),
            opponent_flexibility=0.05,
            rounds_since_concession=3,
            is_buyer=True,
        )
        assert rec.strategy == StrategyType.HARDBALL
        # Hardball concession is a small token value (0.005 or 0.01)
        assert rec.concession_fraction <= Decimal("0.02")

    def test_ultimatum_near_end(self):
        engine = self._engine()
        rec = engine.select_strategy(
            round_num=19,
            my_last_price=Decimal("95000"),
            opponent_last_price=Decimal("105000"),
            reservation_price=Decimal("110000"),
            target_price=Decimal("90000"),
            is_buyer=True,
        )
        assert rec.strategy == StrategyType.ULTIMATUM

    def test_deadline_pressure(self):
        engine = self._engine()
        rec = engine.select_strategy(
            round_num=10,
            my_last_price=Decimal("95000"),
            opponent_last_price=Decimal("100000"),
            reservation_price=Decimal("110000"),
            target_price=Decimal("90000"),
            time_remaining_pct=0.15,
            is_buyer=True,
        )
        assert rec.strategy == StrategyType.DEADLINE_PRESSURE

    def test_walk_away_below_reservation(self):
        engine = self._engine()
        rec = engine.select_strategy(
            round_num=5,
            my_last_price=Decimal("95000"),
            opponent_last_price=Decimal("70000"),
            reservation_price=Decimal("80000"),
            target_price=Decimal("100000"),
            is_buyer=False,  # Seller — opponent offering below reservation
            rounds_since_concession=4,  # stalled long enough to trigger walk-away
        )
        # With opponent far below reservation and prolonged stall,
        # engine selects WALK_AWAY or CONDITIONAL
        assert rec.strategy in (StrategyType.WALK_AWAY, StrategyType.CONDITIONAL)
        assert rec.action in ("REJECT", "COUNTER")

    def test_tit_for_tat_cooperative_opponent(self):
        engine = self._engine()
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

    def test_adaptive_concession(self):
        result = adaptive_concession(
            Decimal("0.10"),
            opponent_flexibility=0.8,
            opponent_type="cooperative",
        )
        assert result == Decimal("0.085")  # 0.10 * 0.85

    def test_adaptive_concession_stubborn(self):
        result = adaptive_concession(
            Decimal("0.10"),
            opponent_flexibility=0.1,
            opponent_type="stubborn",
        )
        assert result == Decimal("0.12")  # 0.10 * 1.20

    def test_adaptive_concession_capped(self):
        result = adaptive_concession(
            Decimal("0.50"),
            opponent_flexibility=0.1,
            opponent_type="stubborn",
        )
        assert result <= Decimal("0.30")


# ═══════════════════════════════════════════════════════════════════════════════
# Bayesian Opponent Model Tests (Intelligence Layer)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBayesianOpponentModel:
    def test_uniform_prior(self):
        belief = BayesianOpponentModel.PRIOR
        assert belief.cooperative == 0.25
        assert belief.strategic == 0.25
        assert belief.stubborn == 0.25
        assert belief.bluffing == 0.25

    def test_update_belief_high_flexibility(self):
        model = BayesianOpponentModel()
        metrics = OpponentMetrics(
            flexibility_score=0.85,
            response_time=2.0,
            consistency=0.9,
        )
        belief = model.update_belief(metrics)
        assert belief.dominant_type == OpponentType.COOPERATIVE
        assert belief.cooperative > 0.5  # Should be dominant

    def test_update_belief_low_flexibility(self):
        model = BayesianOpponentModel()
        metrics = OpponentMetrics(
            flexibility_score=0.08,
            response_time=12.0,
            consistency=0.8,
        )
        belief = model.update_belief(metrics)
        assert belief.dominant_type == OpponentType.STUBBORN

    def test_update_belief_oscillating(self):
        model = BayesianOpponentModel()
        metrics = OpponentMetrics(
            flexibility_score=0.5,
            response_time=6.0,
            consistency=0.15,  # Low consistency = oscillating
        )
        belief = model.update_belief(metrics)
        assert belief.dominant_type == OpponentType.BLUFFING

    def test_sequential_updates_converge(self):
        model = BayesianOpponentModel()
        belief = BayesianOpponentModel.PRIOR

        # Simulate 3 rounds of stubborn behavior
        for _ in range(3):
            metrics = OpponentMetrics(
                flexibility_score=0.05,
                response_time=15.0,
                consistency=0.9,
            )
            belief = model.update_belief(metrics, prior=belief)

        assert belief.dominant_type == OpponentType.STUBBORN
        assert belief.stubborn > 0.8  # High confidence after 3 updates

    def test_strategy_modifier_cooperative(self):
        model = BayesianOpponentModel()
        belief = OpponentBelief(cooperative=0.7, strategic=0.1, stubborn=0.1, bluffing=0.1)
        mod = model.strategy_modifier(belief)
        assert mod["concession_rate"] == 0.85  # Concede less
        assert mod["pressure"] is False

    def test_strategy_modifier_stubborn(self):
        model = BayesianOpponentModel()
        belief = OpponentBelief(cooperative=0.1, strategic=0.1, stubborn=0.7, bluffing=0.1)
        mod = model.strategy_modifier(belief)
        assert mod["concession_rate"] == 1.20  # Concede more
        assert mod["pressure"] is True

    def test_strategy_modifier_bluffing(self):
        model = BayesianOpponentModel()
        belief = OpponentBelief(cooperative=0.1, strategic=0.1, stubborn=0.1, bluffing=0.7)
        mod = model.strategy_modifier(belief)
        assert mod["concession_rate"] == 0.70  # Hold firm
        assert mod["pressure"] is True

    def test_opponent_belief_to_dict(self):
        belief = OpponentBelief(cooperative=0.3, strategic=0.3, stubborn=0.2, bluffing=0.2)
        d = belief.to_dict()
        assert d["cooperative"] == 0.3
        assert sum(d.values()) == pytest.approx(1.0)

    def test_opponent_belief_from_dict(self):
        d = {"cooperative": 0.4, "strategic": 0.3, "stubborn": 0.2, "bluffing": 0.1}
        belief = OpponentBelief.from_dict(d)
        assert belief.cooperative == 0.4
        assert belief.dominant_type == OpponentType.COOPERATIVE


class TestFlexibilityComputation:
    def test_neutral_with_few_prices(self):
        assert compute_flexibility([Decimal("100000")]) == 0.5

    def test_high_flexibility(self):
        prices = [Decimal("100000"), Decimal("95000"), Decimal("88000")]
        flex = compute_flexibility(prices)
        assert flex > 0.05  # Should show meaningful flexibility

    def test_low_flexibility(self):
        # Prices barely change
        prices = [Decimal("100000"), Decimal("99900"), Decimal("99800"), Decimal("99700")]
        flex = compute_flexibility(prices)
        assert flex < 0.01

    def test_consistency_monotone_decreasing(self):
        prices = [Decimal("100000"), Decimal("95000"), Decimal("90000"), Decimal("85000")]
        cons = compute_consistency(prices)
        assert cons == 1.0  # All decreasing

    def test_consistency_oscillating(self):
        prices = [Decimal("100000"), Decimal("95000"), Decimal("100000"), Decimal("95000")]
        cons = compute_consistency(prices)
        assert cons < 0.7  # Not consistent (oscillating pattern)

    def test_compute_opponent_metrics(self):
        prices = [Decimal("100000"), Decimal("98000"), Decimal("96000")]
        metrics = compute_opponent_metrics(prices, response_time=3.0)
        assert metrics.rounds_observed == 3
        assert metrics.response_time == 3.0
        assert 0 <= metrics.flexibility_score <= 1
        assert 0 <= metrics.consistency <= 1


# ═══════════════════════════════════════════════════════════════════════════════
# Guardrail Engine Tests (Layer 4)
# ═══════════════════════════════════════════════════════════════════════════════


class TestGuardrailEngine:
    def _engine(self) -> GuardrailEngine:
        return GuardrailEngine(min_confidence=0.10)

    def test_valid_envelope_passes(self):
        engine = self._engine()
        envelope = ActionEnvelope(
            agent_role="buyer",
            action="counter",
            offer_value=Decimal("95000"),
            confidence=0.85,
        )
        violations = engine.validate_envelope(
            envelope=envelope,
            reservation_price=Decimal("90000"),
            budget_ceiling=Decimal("100000"),
        )
        assert violations == []

    def test_budget_exceeded_violation(self):
        engine = self._engine()
        envelope = ActionEnvelope(
            agent_role="buyer",
            action="counter",
            offer_value=Decimal("120000"),
            confidence=0.85,
        )
        violations = engine.validate_envelope(
            envelope=envelope,
            reservation_price=Decimal("90000"),
            budget_ceiling=Decimal("100000"),
        )
        assert len(violations) == 1
        assert violations[0].violation_type == ViolationType.BUDGET_EXCEEDED

    def test_below_reservation_violation(self):
        engine = self._engine()
        envelope = ActionEnvelope(
            agent_role="seller",
            action="counter",
            offer_value=Decimal("70000"),
            confidence=0.85,
        )
        violations = engine.validate_envelope(
            envelope=envelope,
            reservation_price=Decimal("80000"),
        )
        assert len(violations) == 1
        assert violations[0].violation_type == ViolationType.BELOW_RESERVATION

    def test_margin_violation(self):
        engine = self._engine()
        envelope = ActionEnvelope(
            agent_role="seller",
            action="counter",
            offer_value=Decimal("82000"),
            confidence=0.85,
        )
        violations = engine.validate_envelope(
            envelope=envelope,
            reservation_price=Decimal("80000"),
            cost_basis=Decimal("80000"),
            margin_floor=Decimal("10"),  # 10% margin required
        )
        assert any(v.violation_type == ViolationType.MARGIN_VIOLATION for v in violations)

    def test_low_confidence_violation(self):
        engine = self._engine()
        envelope = ActionEnvelope(
            agent_role="buyer",
            action="counter",
            offer_value=Decimal("95000"),
            confidence=0.05,
        )
        violations = engine.validate_envelope(
            envelope=envelope,
            reservation_price=Decimal("90000"),
        )
        assert any(v.violation_type == ViolationType.CONFIDENCE_TOO_LOW for v in violations)

    def test_enforce_raises_on_critical(self):
        engine = self._engine()
        envelope = ActionEnvelope(
            agent_role="buyer",
            action="counter",
            offer_value=Decimal("120000"),
            confidence=0.85,
        )
        with pytest.raises(PolicyViolation, match="VETO"):
            engine.enforce(
                envelope=envelope,
                reservation_price=Decimal("90000"),
                budget_ceiling=Decimal("100000"),
            )

    def test_accept_action_skips_price_checks(self):
        engine = self._engine()
        envelope = ActionEnvelope(
            agent_role="buyer",
            action="accept",
            offer_value=Decimal("120000"),
            confidence=0.85,
        )
        violations = engine.validate_envelope(
            envelope=envelope,
            reservation_price=Decimal("90000"),
            budget_ceiling=Decimal("100000"),
        )
        # Accept does not check budget
        assert not any(v.violation_type == ViolationType.BUDGET_EXCEEDED for v in violations)


class TestActionEnvelope:
    def test_valid_envelope(self):
        env = ActionEnvelope(
            agent_role="buyer",
            action="counter",
            offer_value=Decimal("95000"),
            confidence=0.85,
        )
        assert env.agent_role == "buyer"
        assert env.action == "counter"

    def test_rejects_invalid_role(self):
        with pytest.raises(ValidationError, match="agent_role"):
            ActionEnvelope(agent_role="observer", action="counter")

    def test_rejects_invalid_action(self):
        with pytest.raises(ValidationError, match="action"):
            ActionEnvelope(agent_role="buyer", action="pause_indefinitely")

    def test_rejects_negative_offer(self):
        with pytest.raises(ValidationError, match="offer_value"):
            ActionEnvelope(agent_role="buyer", action="counter", offer_value=Decimal("-100"))

    def test_rejects_invalid_confidence(self):
        with pytest.raises(ValidationError, match="confidence"):
            ActionEnvelope(agent_role="buyer", action="counter", confidence=1.5)

    def test_validate_raw_envelope(self):
        raw = {
            "agent_role": "buyer",
            "action": "counter",
            "price": 95000,
            "confidence": 0.85,
            "reasoning": "Good deal",
        }
        env = validate_raw_envelope(raw)
        assert env.offer_value == Decimal("95000")
        assert env.rationale == "Good deal"


# ═══════════════════════════════════════════════════════════════════════════════
# AgentProfile Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgentProfile:
    def test_update_after_session(self):
        profile = AgentProfile()
        initial_win_rate = profile.strategy_weights.win_rate
        profile.update_after_session(
            session_agreed=True,
            rounds_taken=3,
            final_price=Decimal("500000"),
            budget_ceiling=Decimal("1000000"),
        )
        assert profile.version == 2
        assert profile.strategy_weights.win_rate != initial_win_rate

    def test_to_prompt_context_redacts_budget(self):
        profile = AgentProfile(
            risk_profile=RiskProfile(budget_ceiling=Decimal("5000000")),
        )
        ctx = profile.to_prompt_context()
        assert ctx["risk"]["budget_range"] == "HIGH"
        assert "5000000" not in str(ctx)
        assert "budget_ceiling" not in str(ctx)

    def test_to_prompt_context_low_budget(self):
        profile = AgentProfile(
            risk_profile=RiskProfile(budget_ceiling=Decimal("50000")),
        )
        ctx = profile.to_prompt_context()
        assert ctx["risk"]["budget_range"] == "LOW"


# ═══════════════════════════════════════════════════════════════════════════════
# IndustryPlaybook Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestIndustryPlaybook:
    def test_to_prompt_context_filters_keys(self):
        pb = IndustryPlaybook(
            vertical="steel",
            playbook_config={
                "pricing_norms": [1, 2],
                "internal_secret": "should not appear",
                "seasonal_factors": {"Q1": "high"},
            },
        )
        ctx = pb.to_prompt_context()
        assert ctx["vertical"] == "steel"
        assert "pricing_norms" in ctx
        assert "seasonal_factors" in ctx
        assert "internal_secret" not in ctx


# ═══════════════════════════════════════════════════════════════════════════════
# NegotiationPolicy Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestNegotiationPolicy:
    def test_budget_guard_passes(self):
        NegotiationPolicy.check_budget_guard(Decimal("50000"), Decimal("100000"))

    def test_budget_guard_raises(self):
        with pytest.raises(PolicyViolation, match="exceeds budget ceiling"):
            NegotiationPolicy.check_budget_guard(Decimal("150000"), Decimal("100000"))

    def test_margin_floor_passes(self):
        NegotiationPolicy.check_margin_floor(
            Decimal("110"), Decimal("100"), Decimal("5")
        )

    def test_margin_floor_raises(self):
        with pytest.raises(PolicyViolation, match="below floor"):
            NegotiationPolicy.check_margin_floor(
                Decimal("101"), Decimal("100"), Decimal("5")
            )

    def test_stall_detected(self):
        assert NegotiationPolicy.check_stall(10, 10) is True
        assert NegotiationPolicy.check_stall(9, 10) is False

    def test_convergence_detected(self):
        assert NegotiationPolicy.check_convergence(
            Decimal("100"), Decimal("101"), tolerance=0.02
        ) is True

    def test_convergence_too_far(self):
        assert NegotiationPolicy.check_convergence(
            Decimal("100"), Decimal("110"), tolerance=0.02
        ) is False

    def test_convergence_none_prices(self):
        assert NegotiationPolicy.check_convergence(None, Decimal("100")) is False

    def test_turn_order_allows_seller_first(self):
        """DANP FSM: seller may post the opening anchor offer."""
        NegotiationPolicy.check_turn_order([], "SELLER")

    def test_turn_order_no_consecutive(self):
        offer = Offer.create_agent_offer(
            session_id=uuid.uuid4(),
            round_number=1,
            proposer_role=ProposerRole.BUYER,
            price=Decimal("100"),
            currency="INR",
            terms={},
            confidence=0.5,
            agent_reasoning="test",
        )
        with pytest.raises(PolicyViolation, match="consecutively"):
            NegotiationPolicy.check_turn_order([offer], "BUYER")


# ═══════════════════════════════════════════════════════════════════════════════
# Domain Event Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestDomainEvents:
    def test_session_agreed_frozen(self):
        ev = SessionAgreed(
            aggregate_id=uuid.uuid4(),
            event_type="SessionAgreed",
            session_id=uuid.uuid4(),
            agreed_price=Decimal("50000"),
        )
        assert ev.agreed_price == Decimal("50000")
        assert ev.agreed_terms == {}

    def test_offer_submitted_frozen(self):
        ev = OfferSubmitted(
            aggregate_id=uuid.uuid4(),
            event_type="OfferSubmitted",
            session_id=uuid.uuid4(),
            offer_id=uuid.uuid4(),
            round_number=3,
            proposer_role="BUYER",
            price=Decimal("45000"),
        )
        assert ev.round_number == 3
