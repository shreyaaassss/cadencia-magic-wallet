# context.md §3 — pure domain logic, no framework imports.
# Research basis: AI can reliably assess trust/respect (CUI'25).
# Talk time and sentiment predict negotiation outcomes (Di Stasi 2024).

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.negotiation.domain.session import NegotiationSession


class RelationalQualityScorer:
    """
    Pure-math quality scoring for completed negotiations.

    Measures trust, respect, and equitability from offer sequence data.
    No LLM required — derived entirely from price behavior.
    """

    def score(self, session: "NegotiationSession") -> dict:
        """Compute full relational quality score for a completed session."""
        offers = session.offers
        if len(offers) < 2:
            return {"trust": 0.5, "respect": 0.5, "equitability": 0.5, "composite": 0.5}

        trust = self._compute_trust(offers)
        respect = self._compute_respect(offers)
        equitability = self._compute_equitability(session)
        composite = round(0.40 * trust + 0.35 * respect + 0.25 * equitability, 4)

        return {
            "trust": round(trust, 4),
            "respect": round(respect, 4),
            "equitability": round(equitability, 4),
            "composite": composite,
        }

    def _compute_trust(self, offers: list) -> float:
        """
        Consistency of concession direction + no sudden reversals.
        1.0 = perfectly monotone concessions (high trust).
        0.0 = erratic / oscillating behavior (low trust).
        """
        from collections import defaultdict
        by_role: dict = defaultdict(list)
        for o in offers:
            by_role[o.proposer_role.value].append(float(o.price.amount))

        scores = []
        for role, prices in by_role.items():
            if len(prices) < 2:
                scores.append(0.5)
                continue
            directions = []
            for i in range(1, len(prices)):
                diff = prices[i] - prices[i - 1]
                directions.append(1 if diff > 0 else (-1 if diff < 0 else 0))
            if not directions or directions[0] == 0:
                scores.append(0.5)
                continue
            same_dir = sum(1 for d in directions if d == directions[0])
            scores.append(same_dir / len(directions))

        return sum(scores) / len(scores) if scores else 0.5

    def _compute_respect(self, offers: list) -> float:
        """
        Reasonable counter-offers — not absurdly far from opponent's last.
        Score drops when counter-offers jump > 30% away from opponent's last price.
        """
        if len(offers) < 2:
            return 0.5

        reasonable_count = 0
        total_pairs = 0

        for i in range(1, len(offers)):
            prev_offer = offers[i - 1]
            curr_offer = offers[i]
            # Only score cross-role pairs (counter-offers)
            if prev_offer.proposer_role == curr_offer.proposer_role:
                continue
            prev_price = float(prev_offer.price.amount)
            curr_price = float(curr_offer.price.amount)
            if prev_price <= 0:
                continue
            gap_pct = abs(curr_price - prev_price) / prev_price
            total_pairs += 1
            if gap_pct <= 0.30:
                reasonable_count += 1

        if total_pairs == 0:
            return 0.5
        return reasonable_count / total_pairs

    def _compute_equitability(self, session: "NegotiationSession") -> float:
        """
        Balanced total concession between buyer and seller.
        1.0 = both sides conceded equally. 0.0 = one side did all conceding.
        """
        buyer_prices = session.get_buyer_prices()
        seller_prices = session.get_seller_prices()

        if not buyer_prices or not seller_prices:
            return 0.5

        buyer_concession = abs(
            float(buyer_prices[-1]) - float(buyer_prices[0])
        ) if len(buyer_prices) > 1 else 0.0

        seller_concession = abs(
            float(seller_prices[0]) - float(seller_prices[-1])
        ) if len(seller_prices) > 1 else 0.0

        total = buyer_concession + seller_concession
        if total <= 0:
            return 0.5

        # Perfect equity = 0.5/0.5 split → score 1.0
        buyer_share = buyer_concession / total
        seller_share = seller_concession / total
        # Distance from perfect equity (0.5/0.5)
        imbalance = abs(buyer_share - seller_share)
        return max(0.0, 1.0 - 2 * imbalance)
