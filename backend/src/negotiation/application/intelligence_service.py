"""
NegotiationIntelligenceService — extracts behavioral intelligence from sessions.

Two extraction paths:
1. From completed transcripts (pure math, no LLM) — called at session completion.
2. From uploaded documents (lightweight LLM) — called at vault ingestion.

Updates AgentProfile.negotiation_intelligence JSONB via EMA merge.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog

log = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from src.negotiation.domain.agent_profile import AgentProfile


class NegotiationIntelligenceService:
    """
    Extracts negotiation intelligence from transcripts and uploaded documents.
    Updates AgentProfile with style signals for prompt injection.
    """

    def extract_from_transcript(self, transcript: dict) -> dict:
        """
        Pure-math extraction from session transcript — no LLM required.
        Computes behavioral signals from the offer price sequence.
        """
        rounds = transcript.get("rounds", [])
        if not rounds:
            return {}

        # Separate prices by role
        buyer_prices = [r["price"] for r in rounds if r["role"] == "buyer"]
        seller_prices = [r["price"] for r in rounds if r["role"] == "seller"]
        total_rounds = transcript.get("rounds_taken", len(rounds))
        outcome = transcript.get("outcome", "UNKNOWN")
        agreed_price = transcript.get("agreed_price")

        intelligence: dict = {
            "rounds_to_close": total_rounds,
            "outcome": outcome,
        }

        # Avg concession per round (buyer)
        if len(buyer_prices) >= 2:
            buyer_deltas = [
                abs(buyer_prices[i] - buyer_prices[i - 1]) / max(buyer_prices[i - 1], 1)
                for i in range(1, len(buyer_prices))
            ]
            intelligence["buyer_avg_concession_pct"] = round(
                sum(buyer_deltas) / len(buyer_deltas) * 100, 2
            )
            # Opening anchor relative to agreed price
            if agreed_price and buyer_prices[0] > 0:
                intelligence["buyer_opening_anchor_pct_below_agreed"] = round(
                    (agreed_price - buyer_prices[0]) / agreed_price * 100, 2
                )
            # Consistency (monotonicity)
            intelligence["buyer_consistency_score"] = _monotonicity(buyer_prices, ascending=True)
            # Style classification from curve shape
            intelligence["buyer_style"] = _classify_concession_style(buyer_deltas)

        if len(seller_prices) >= 2:
            seller_deltas = [
                abs(seller_prices[i] - seller_prices[i - 1]) / max(seller_prices[i - 1], 1)
                for i in range(1, len(seller_prices))
            ]
            intelligence["seller_avg_concession_pct"] = round(
                sum(seller_deltas) / len(seller_deltas) * 100, 2
            )
            intelligence["seller_consistency_score"] = _monotonicity(seller_prices, ascending=False)
            intelligence["seller_style"] = _classify_concession_style(seller_deltas)

        return intelligence

    async def extract_from_document(
        self,
        content: str,
        tenant_id: uuid.UUID,
        analysis_driver: object | None = None,
    ) -> dict:
        """
        LLM extraction of negotiation style signals from uploaded documents.
        Uses lightweight analysis driver (Groq/GPT-4.1-nano).
        Returns empty dict if driver unavailable.
        """
        if analysis_driver is None:
            return {}

        extraction_prompt = (
            "Analyze this procurement/negotiation document and extract:\n"
            "{\n"
            '  "preferred_discount_range_pct": [min, max],\n'
            '  "payment_terms_preference": "advance|net30|LC|flexible",\n'
            '  "negotiation_style": "collaborative|assertive|analytical|competitive",\n'
            '  "typical_concession_size_pct": number,\n'
            '  "common_terms_prioritized": ["quality", "delivery", "price"],\n'
            '  "walk_away_signals": ["phrases that indicate near-rejection"],\n'
            '  "deal_accelerators": ["phrases that indicate readiness to close"]\n'
            "}\n"
            "Return null for any field you cannot determine with confidence.\n"
            "Return ONLY valid JSON.\n\n"
            f"DOCUMENT:\n{content[:3000]}"
        )

        try:
            result = await analysis_driver.call(
                system_prompt="You are a procurement negotiation analyst. Extract structured data only.",
                user_content=extraction_prompt,
                temperature=0.0,
            )
            if isinstance(result, dict):
                log.info("document_intelligence_extracted", tenant_id=str(tenant_id))
                return result
        except Exception as exc:
            log.warning("document_intelligence_extraction_failed", error=str(exc))

        return {}

    def update_profile_intelligence(
        self, profile: "AgentProfile", new_signals: dict
    ) -> None:
        """
        EMA-merge new signals into existing negotiation_intelligence JSONB.
        Modifies profile in-place (caller must persist).
        """
        if not new_signals:
            return

        existing = getattr(profile, "negotiation_intelligence", None) or {}
        alpha = 0.3  # EMA weight for new data

        merged: dict = dict(existing)
        for key, new_val in new_signals.items():
            if key in existing and isinstance(new_val, (int, float)):
                # EMA merge for numeric values
                old_val = existing[key]
                if isinstance(old_val, (int, float)):
                    merged[key] = round(old_val * (1 - alpha) + new_val * alpha, 4)
                else:
                    merged[key] = new_val
            else:
                merged[key] = new_val

        # Update profile fields (these may not exist on older profiles — use setattr)
        try:
            object.__setattr__(profile, "negotiation_intelligence", merged)
        except (AttributeError, TypeError):
            profile.negotiation_intelligence = merged  # type: ignore[attr-defined]

        log.debug("profile_intelligence_updated", version=profile.version)


# ── Helper functions ──────────────────────────────────────────────────────────

def _monotonicity(prices: list[float], ascending: bool) -> float:
    """Score 0-1: how monotone the price sequence is in the expected direction."""
    if len(prices) < 2:
        return 1.0
    correct = 0
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i - 1]
        if ascending and diff >= 0:
            correct += 1
        elif not ascending and diff <= 0:
            correct += 1
    return round(correct / (len(prices) - 1), 4)


def _classify_concession_style(deltas: list[float]) -> str:
    """
    Classify concession curve shape:
    - boulware: slow then fast → 'assertive'
    - conceder: fast then slow → 'collaborative'
    - linear: consistent → 'analytical'
    """
    if len(deltas) < 3:
        return "unknown"
    first_half = sum(deltas[: len(deltas) // 2]) / max(len(deltas) // 2, 1)
    second_half = sum(deltas[len(deltas) // 2 :]) / max(len(deltas) - len(deltas) // 2, 1)
    ratio = second_half / max(first_half, 0.0001)
    if ratio > 1.5:
        return "assertive"   # Boulware: small early, big late
    elif ratio < 0.67:
        return "collaborative"  # Conceder: big early, small late
    else:
        return "analytical"   # Linear/consistent
