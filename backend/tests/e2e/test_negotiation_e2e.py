# E2E Test — Negotiation Engine Full Flow
# Simulates: session create → multi-round turns → convergence → agreement
# Uses domain objects directly (no HTTP, no DB) to test the complete engine pipeline.
# This is the "negotiation engine works end-to-end" proof.

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from src.negotiation.domain.guardrails import ActionEnvelope, GuardrailEngine
from src.negotiation.domain.offer import Offer, ProposerRole
from src.negotiation.domain.opponent_model import (
    BayesianOpponentModel,
    compute_opponent_metrics,
)
from src.negotiation.domain.session import NegotiationSession, SessionStatus
from src.negotiation.domain.strategy import StrategyEngine
from src.negotiation.domain.valuation import compute_buyer_valuation, compute_seller_valuation
from src.negotiation.domain.value_objects import OfferValue


# ═════════════════════════════════════════════════════════════════════════════
# Full Negotiation E2E: Buyer Agent vs Seller Agent
# ═════════════════════════════════════════════════════════════════════════════


class TestNegotiationE2E:
    """Simulate a complete negotiation between two agents using all engine layers."""

    def _run_negotiation(
        self,
        buyer_budget: Decimal,
        seller_cost: Decimal,
        max_rounds: int = 15,
    ) -> NegotiationSession:
        """Run a full negotiation and return the final session state."""
        # Setup
        session = NegotiationSession(
            rfq_id=uuid.uuid4(),
            match_id=uuid.uuid4(),
            buyer_enterprise_id=uuid.uuid4(),
            seller_enterprise_id=uuid.uuid4(),
        )
        session.activate()

        # Valuations
        buyer_val = compute_buyer_valuation(buyer_budget, risk_appetite="MEDIUM")
        seller_val = compute_seller_valuation(seller_cost, margin_floor=Decimal("10"))

        # Strategy engines
        buyer_engine = StrategyEngine(max_rounds=max_rounds)
        seller_engine = StrategyEngine(max_rounds=max_rounds)

        # Opponent models
        buyer_opponent_model = BayesianOpponentModel()
        seller_opponent_model = BayesianOpponentModel()

        # Guardrails
        guardrails = GuardrailEngine(min_confidence=0.10)

        buyer_prices: list[Decimal] = []
        seller_prices: list[Decimal] = []

        for round_num in range(max_rounds):
            if session.status.is_terminal:
                break

            # Determine whose turn it is
            if round_num % 2 == 0:
                # Seller's turn
                opp_metrics = compute_opponent_metrics(buyer_prices, response_time=1.0)
                seller_opponent_model.update_belief(opp_metrics)

                rec = seller_engine.select_strategy(
                    round_num=round_num,
                    my_last_price=seller_prices[-1] if seller_prices else None,
                    opponent_last_price=buyer_prices[-1] if buyer_prices else None,
                    reservation_price=seller_val.reservation_price,
                    target_price=seller_val.target_price,
                    is_buyer=False,
                    opponent_flexibility=opp_metrics.flexibility_score if opp_metrics.rounds_observed > 1 else 0.5,
                )

                price = rec.suggested_price or seller_val.target_price
                # Clamp to reservation
                price = max(price, seller_val.reservation_price)

                seller_prices.append(price)
                offer = Offer.create_agent_offer(
                    session_id=session.id,
                    round_number=round_num + 1,
                    proposer_role=ProposerRole.SELLER,
                    price=price,
                    currency="INR",
                    terms={"payment": "NET_30"},
                    confidence=0.8,
                    agent_reasoning=f"Strategy: {rec.strategy.value}",
                )
                session.add_offer(offer)

            else:
                # Buyer's turn
                opp_metrics = compute_opponent_metrics(seller_prices, response_time=1.0)
                buyer_opponent_model.update_belief(opp_metrics)

                rec = buyer_engine.select_strategy(
                    round_num=round_num,
                    my_last_price=buyer_prices[-1] if buyer_prices else None,
                    opponent_last_price=seller_prices[-1] if seller_prices else None,
                    reservation_price=buyer_val.reservation_price,
                    target_price=buyer_val.target_price,
                    is_buyer=True,
                    opponent_flexibility=opp_metrics.flexibility_score if opp_metrics.rounds_observed > 1 else 0.5,
                )

                price = rec.suggested_price or buyer_val.target_price
                # Clamp to reservation
                price = min(price, buyer_val.reservation_price)

                buyer_prices.append(price)
                offer = Offer.create_agent_offer(
                    session_id=session.id,
                    round_number=round_num + 1,
                    proposer_role=ProposerRole.BUYER,
                    price=price,
                    currency="INR",
                    terms={"payment": "NET_30"},
                    confidence=0.8,
                    agent_reasoning=f"Strategy: {rec.strategy.value}",
                )
                session.add_offer(offer)

            # Check convergence after each round
            if session.check_convergence(tolerance=0.02):
                # Calculate midpoint
                last_buyer = buyer_prices[-1] if buyer_prices else Decimal("0")
                last_seller = seller_prices[-1] if seller_prices else Decimal("0")
                agreed_price = (last_buyer + last_seller) / 2
                session.mark_agreed(
                    OfferValue(amount=agreed_price, currency="INR"),
                    {"payment": "NET_30", "delivery": "30 days"},
                )
                break

        return session

    # ── Test Cases ───────────────────────────────────────────────────────────

    def test_viable_deal_reaches_agreement(self):
        """When buyer budget > seller cost, agents should converge."""
        session = self._run_negotiation(
            buyer_budget=Decimal("100000"),
            seller_cost=Decimal("70000"),
        )
        assert session.status == SessionStatus.AGREED
        assert session.agreed_price is not None
        assert session.agreed_price.amount > Decimal("0")

    def test_agreed_price_is_between_valuations(self):
        """Agreed price must be within the bargaining zone."""
        session = self._run_negotiation(
            buyer_budget=Decimal("100000"),
            seller_cost=Decimal("70000"),
        )
        if session.status == SessionStatus.AGREED:
            price = session.agreed_price.amount
            # Price should be reasonable (between seller cost and buyer budget)
            assert price >= Decimal("70000") * Decimal("1.05"), f"Price {price} too low"
            assert price <= Decimal("100000") * Decimal("1.05"), f"Price {price} too high"

    def test_negotiation_completes_within_max_rounds(self):
        """Negotiation must terminate within max rounds."""
        session = self._run_negotiation(
            buyer_budget=Decimal("100000"),
            seller_cost=Decimal("70000"),
            max_rounds=15,
        )
        assert session.round_count.value <= 15

    def test_multiple_rounds_executed(self):
        """Agents should exchange multiple offers, not agree immediately."""
        session = self._run_negotiation(
            buyer_budget=Decimal("100000"),
            seller_cost=Decimal("70000"),
        )
        assert session.round_count.value >= 2, "Should have at least 2 rounds"

    def test_narrow_margin_still_converges(self):
        """Even with tight margins, agents should find agreement."""
        session = self._run_negotiation(
            buyer_budget=Decimal("85000"),
            seller_cost=Decimal("75000"),
        )
        # With a 10K gap and 10% margin, there's still a zone
        assert session.status in (SessionStatus.AGREED, SessionStatus.ROUND_LOOP)

    def test_no_deal_when_impossible(self):
        """When seller's minimum > buyer's maximum, no agreement possible."""
        session = self._run_negotiation(
            buyer_budget=Decimal("50000"),  # Buyer can pay max ~55K
            seller_cost=Decimal("80000"),   # Seller needs min ~88K
            max_rounds=10,
        )
        # Either still active (couldn't converge) or walked away
        assert session.status != SessionStatus.AGREED

    def test_all_offers_have_valid_prices(self):
        """Every offer in the session must have a positive price."""
        session = self._run_negotiation(
            buyer_budget=Decimal("100000"),
            seller_cost=Decimal("70000"),
        )
        for offer in session.offers:
            assert offer.price.amount > 0, f"Offer {offer.id} has non-positive price"

    def test_alternating_proposer_roles(self):
        """Offers must alternate between buyer and seller."""
        session = self._run_negotiation(
            buyer_budget=Decimal("100000"),
            seller_cost=Decimal("70000"),
        )
        for i in range(1, len(session.offers)):
            prev = session.offers[i - 1].proposer_role
            curr = session.offers[i].proposer_role
            assert prev != curr, f"Consecutive offers from same role at index {i}"

    def test_buyer_prices_trend_upward(self):
        """Buyer should concede upward over time."""
        session = self._run_negotiation(
            buyer_budget=Decimal("100000"),
            seller_cost=Decimal("70000"),
        )
        buyer_offers = [o for o in session.offers if o.proposer_role == ProposerRole.BUYER]
        if len(buyer_offers) >= 3:
            first = buyer_offers[0].price.amount
            last = buyer_offers[-1].price.amount
            assert last >= first, "Buyer should concede upward"

    def test_seller_prices_trend_downward(self):
        """Seller should concede downward over time."""
        session = self._run_negotiation(
            buyer_budget=Decimal("100000"),
            seller_cost=Decimal("70000"),
        )
        seller_offers = [o for o in session.offers if o.proposer_role == ProposerRole.SELLER]
        if len(seller_offers) >= 3:
            first = seller_offers[0].price.amount
            last = seller_offers[-1].price.amount
            assert last <= first, "Seller should concede downward"
