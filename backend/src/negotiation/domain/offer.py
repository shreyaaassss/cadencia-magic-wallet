# context.md §3 — Hexagonal Architecture: zero framework imports in domain layer.
# Offer entity — immutable after creation.

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from src.negotiation.domain.value_objects import (
    Confidence,
    OfferValue,
    RoundNumber,
)
from src.shared.domain.base_entity import BaseEntity


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class ProposerRole(str, Enum):
    BUYER = "BUYER"
    SELLER = "SELLER"


@dataclass
class Offer(BaseEntity):
    """
    Single offer in a negotiation round — immutable after creation.

    agent_reasoning is stored for audit trail but NEVER sent to counterparty
    (filtered in OfferResponse schema).

    context.md §6.2: LLM reasoning stored per offer for audit.
    """

    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
    round_number: RoundNumber = field(default_factory=lambda: RoundNumber(value=0))
    proposer_role: ProposerRole = ProposerRole.BUYER
    price: OfferValue = field(
        default_factory=lambda: OfferValue(amount=Decimal("1"), currency="INR")
    )
    terms: dict = field(default_factory=dict)
    confidence: Confidence | None = None
    agent_reasoning: str | None = None
    is_human_override: bool = False

    # ── Factories ─────────────────────────────────────────────────────────────

    @classmethod
    def create_agent_offer(
        cls,
        session_id: uuid.UUID,
        round_number: int,
        proposer_role: ProposerRole,
        price: Decimal,
        currency: str,
        terms: dict,
        confidence: float,
        agent_reasoning: str,
    ) -> "Offer":
        """Create an LLM-generated offer. is_human_override=False."""
        return cls(
            session_id=session_id,
            round_number=RoundNumber(value=round_number),
            proposer_role=proposer_role,
            price=OfferValue(amount=price, currency=currency),
            terms=terms,
            confidence=Confidence(value=confidence),
            agent_reasoning=agent_reasoning,
            is_human_override=False,
        )

    @classmethod
    def create_human_offer(
        cls,
        session_id: uuid.UUID,
        round_number: int,
        proposer_role: ProposerRole,
        price: Decimal,
        currency: str,
        terms: dict,
    ) -> "Offer":
        """Create a human override offer. confidence=None, is_human_override=True."""
        return cls(
            session_id=session_id,
            round_number=RoundNumber(value=round_number),
            proposer_role=proposer_role,
            price=OfferValue(amount=price, currency=currency),
            terms=terms,
            confidence=None,
            agent_reasoning="HUMAN_OVERRIDE",
            is_human_override=True,
        )
