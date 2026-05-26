"""
MultiPartyNegotiationOrchestrator — spawns parallel bilateral sessions for a single RFQ.

Blueprint implementation: architecture is wired, full multi-session coordination
requires additional API endpoints and is scoped for post-MVP.
Competitive pressure context is available immediately.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog

log = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from src.negotiation.domain.session import NegotiationSession


class MultiPartyNegotiationOrchestrator:
    """
    Spawns parallel bilateral sessions for a single RFQ.

    Design:
    - Each seller gets a separate NegotiationSession (bilateral).
    - Competitive pressure (HIGH/MODERATE/LOW) is injected into each session's context.
    - Auto-awards to the lowest AGREED price among parallel sessions.
    """

    def __init__(self, rfq_id: uuid.UUID) -> None:
        self.rfq_id = rfq_id
        self.active_sessions: dict[uuid.UUID, "NegotiationSession"] = {}  # seller_id → session

    def register_session(
        self, seller_id: uuid.UUID, session: "NegotiationSession"
    ) -> None:
        """Register a bilateral session for a specific seller."""
        self.active_sessions[seller_id] = session
        log.info(
            "orchestrator_session_registered",
            rfq_id=str(self.rfq_id),
            seller_id=str(seller_id),
            total_active=len(self.active_sessions),
        )

    def inject_competitive_context(self) -> dict:
        """
        Return competitive pressure context for injection into negotiation prompts.
        Does not reveal competitor prices — only pressure level.
        """
        n = len(self.active_sessions)
        if n > 3:
            level = "HIGH"
            hint = f"You are competing with {n} other vendors for this order."
        elif n > 1:
            level = "MODERATE"
            hint = f"You are one of {n} vendors being evaluated for this order."
        else:
            level = "LOW"
            hint = "You are the primary vendor under consideration for this order."

        return {
            "competitive_pressure": level,
            "competitive_hint": hint,
            "active_vendor_count": n,
        }

    def select_best_agreement(self) -> "NegotiationSession | None":
        """
        Auto-award: select session with lowest agreed price among all AGREED sessions.
        Returns None if no sessions have reached AGREED status.
        """
        from src.negotiation.domain.session import SessionStatus

        agreed = [
            s for s in self.active_sessions.values()
            if s.status == SessionStatus.AGREED and s.agreed_price is not None
        ]
        if not agreed:
            log.info(
                "orchestrator_no_agreements",
                rfq_id=str(self.rfq_id),
                total_sessions=len(self.active_sessions),
            )
            return None

        best = min(agreed, key=lambda s: s.agreed_price.amount)  # type: ignore[union-attr]
        log.info(
            "orchestrator_best_agreement_selected",
            rfq_id=str(self.rfq_id),
            session_id=str(best.id),
            agreed_price=str(best.agreed_price.amount if best.agreed_price else 0),
        )
        return best

    def get_summary(self) -> dict:
        """Return summary of all sessions for monitoring."""
        from src.negotiation.domain.session import SessionStatus

        return {
            "rfq_id": str(self.rfq_id),
            "total_sessions": len(self.active_sessions),
            "agreed": sum(
                1 for s in self.active_sessions.values()
                if s.status == SessionStatus.AGREED
            ),
            "active": sum(
                1 for s in self.active_sessions.values()
                if s.status == SessionStatus.ACTIVE
            ),
            "failed": sum(
                1 for s in self.active_sessions.values()
                if s.status in (SessionStatus.WALK_AWAY, SessionStatus.TIMEOUT)
            ),
        }
