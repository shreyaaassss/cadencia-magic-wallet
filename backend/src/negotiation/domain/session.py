# context.md §3 — Hexagonal Architecture: zero framework imports in domain layer.
# NegotiationSession aggregate root — enforces DANP state machine invariants.
# DANP FSM: INIT → SELLER_ANCHOR → BUYER_RESPONSE → ROUND_LOOP → AGREED
#            ROUND_LOOP → WALK_AWAY | STALLED | TIMEOUT | POLICY_BREACH
# Legacy path (in-flight sessions): BUYER_ANCHOR → SELLER_RESPONSE → ROUND_LOOP

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum

from src.shared.domain.base_entity import BaseEntity
from src.shared.domain.exceptions import ConflictError, PolicyViolation
from src.negotiation.domain.offer import Offer, ProposerRole
from src.negotiation.domain.value_objects import OfferValue, RoundNumber

SESSION_TTL_HOURS: int = 24
MAX_ROUNDS: int = 20
STALL_ROUNDS: int = 3  # No concession for 3 rounds → STALLED
MAX_SCHEMA_FAILURES: int = 3  # 3x invalid schema → POLICY_BREACH
CONVERGENCE_TOLERANCE: float = 0.02  # 2% gap → AGREED


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class SessionStatus(str, Enum):
    """
    Full DANP FSM states (9 states per spec).

    Transitions:
        INIT → SELLER_ANCHOR               (CreateSession — seller quotes first)
        SELLER_ANCHOR → BUYER_RESPONSE     (Seller's catalog anchor posted)
        BUYER_RESPONSE → ROUND_LOOP        (Buyer's counter)
        ROUND_LOOP → ROUND_LOOP            (Counter)
        ROUND_LOOP → AGREED                (Gap <= 2% or prices crossed)
    Legacy (in-flight sessions only):
        BUYER_ANCHOR → SELLER_RESPONSE → ROUND_LOOP
        ROUND_LOOP → STALLED              (No concession x3)
        ROUND_LOOP → WALK_AWAY             (Reject)
        ROUND_LOOP → TIMEOUT               (TTL expired)
        ROUND_LOOP → POLICY_BREACH         (3x schema failure)
        STALLED → HUMAN_REVIEW             (Escalate)
        HUMAN_REVIEW → ACTIVE (resume)     (Admin resumes)

    Legacy mapping for backward compatibility:
        ACTIVE = covers INIT, SELLER_ANCHOR, BUYER_RESPONSE, BUYER_ANCHOR, SELLER_RESPONSE, ROUND_LOOP
        AGREED = AGREED
        FAILED = WALK_AWAY, POLICY_BREACH
        EXPIRED = TIMEOUT
        HUMAN_REVIEW = STALLED → HUMAN_REVIEW
    """

    # === DANP States ===
    INIT = "INIT"
    SELLER_ANCHOR = "SELLER_ANCHOR"    # New: seller quotes catalog price first
    BUYER_RESPONSE = "BUYER_RESPONSE"  # New: buyer counters seller's anchor
    BUYER_ANCHOR = "BUYER_ANCHOR"      # Legacy: kept for in-flight sessions
    SELLER_RESPONSE = "SELLER_RESPONSE"  # Legacy: kept for in-flight sessions
    ROUND_LOOP = "ROUND_LOOP"
    AGREED = "AGREED"
    WALK_AWAY = "WALK_AWAY"
    STALLED = "STALLED"
    TIMEOUT = "TIMEOUT"
    POLICY_BREACH = "POLICY_BREACH"

    # === Legacy/Compat States ===
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    HUMAN_REVIEW = "HUMAN_REVIEW"

    @property
    def is_active(self) -> bool:
        """True if the session is in a state that accepts offers."""
        return self in _ACTIVE_STATES

    @property
    def is_terminal(self) -> bool:
        """True if the session has completed (no more turns)."""
        return self in _TERMINAL_STATES


# Active states: session accepts offers
_ACTIVE_STATES = {
    SessionStatus.INIT,
    SessionStatus.SELLER_ANCHOR,
    SessionStatus.BUYER_RESPONSE,
    SessionStatus.BUYER_ANCHOR,      # legacy
    SessionStatus.SELLER_RESPONSE,   # legacy
    SessionStatus.ROUND_LOOP,
    SessionStatus.ACTIVE,
}

# Terminal states: session is done
_TERMINAL_STATES = {
    SessionStatus.AGREED,
    SessionStatus.WALK_AWAY,
    SessionStatus.TIMEOUT,
    SessionStatus.POLICY_BREACH,
    SessionStatus.FAILED,
    SessionStatus.EXPIRED,
}


@dataclass
class NegotiationSession(BaseEntity):
    """
    Negotiation session aggregate root.

    Enforces the DANP state machine with full 9-state transitions:
        INIT → BUYER_ANCHOR → SELLER_RESPONSE → ROUND_LOOP → AGREED
        ROUND_LOOP → WALK_AWAY | STALLED | TIMEOUT | POLICY_BREACH
        STALLED → HUMAN_REVIEW → ACTIVE (resume)

    All state transitions are guarded by explicit policy methods.
    No I/O — pure Python domain logic.
    """

    rfq_id: uuid.UUID = field(default_factory=uuid.uuid4)
    match_id: uuid.UUID = field(default_factory=uuid.uuid4)
    buyer_enterprise_id: uuid.UUID = field(default_factory=uuid.uuid4)
    seller_enterprise_id: uuid.UUID = field(default_factory=uuid.uuid4)
    status: SessionStatus = SessionStatus.INIT
    agreed_price: OfferValue | None = None
    agreed_terms: dict | None = None
    round_count: RoundNumber = field(default_factory=lambda: RoundNumber(value=0))
    offers: list[Offer] = field(default_factory=list)
    completed_at: datetime | None = None
    expires_at: datetime = field(
        default_factory=lambda: _utcnow() + timedelta(hours=SESSION_TTL_HOURS)
    )
    schema_failure_count: int = 0
    stall_counter: int = 0  # Consecutive rounds without concession

    # ── DANP State Transitions ─────────────────────────────────────────────────

    def activate(self) -> "SessionCreated":
        """INIT → SELLER_ANCHOR (session activated, waiting for seller's catalog anchor)."""
        from src.negotiation.domain.events import SessionCreated

        if self.status not in (SessionStatus.INIT, SessionStatus.ACTIVE):
            raise ConflictError(
                f"Cannot activate session {self.id}: "
                f"status is '{self.status.value}', expected INIT."
            )
        self.status = SessionStatus.SELLER_ANCHOR
        self.touch()
        return SessionCreated(
            aggregate_id=self.id,
            event_type="SessionCreated",
            session_id=self.id,
            rfq_id=self.rfq_id,
            match_id=self.match_id,
            buyer_enterprise_id=self.buyer_enterprise_id,
            seller_enterprise_id=self.seller_enterprise_id,
        )

    def transition(self, offer: Offer) -> SessionStatus:
        """
        Advance the DANP FSM based on submitted offer.

        Returns the new status after transition.
        """
        # New FSM path: seller anchors first
        if self.status == SessionStatus.SELLER_ANCHOR:
            if offer.proposer_role == ProposerRole.SELLER:
                self.status = SessionStatus.BUYER_RESPONSE
        elif self.status == SessionStatus.BUYER_RESPONSE:
            if offer.proposer_role == ProposerRole.BUYER:
                self.status = SessionStatus.ROUND_LOOP
        # Legacy FSM path: buyer anchored first (in-flight sessions)
        elif self.status == SessionStatus.BUYER_ANCHOR:
            if offer.proposer_role == ProposerRole.BUYER:
                self.status = SessionStatus.SELLER_RESPONSE
        elif self.status == SessionStatus.SELLER_RESPONSE:
            if offer.proposer_role == ProposerRole.SELLER:
                self.status = SessionStatus.ROUND_LOOP
        # ROUND_LOOP stays in ROUND_LOOP unless terminal
        # ACTIVE transitions to ROUND_LOOP-equivalent
        elif self.status == SessionStatus.ACTIVE:
            if len(self.offers) >= 2:
                self.status = SessionStatus.ROUND_LOOP
            elif len(self.offers) == 0:
                self.status = SessionStatus.SELLER_ANCHOR
            elif len(self.offers) == 1:
                self.status = SessionStatus.BUYER_RESPONSE

        self.touch()
        return self.status

    # ── Offer Management ───────────────────────────────────────────────────────

    def add_offer(self, offer: Offer) -> "OfferSubmitted":
        """
        Add an offer to the session and increment round count.

        Guards:
          - ConflictError if status is terminal
          - ConflictError if round_count >= MAX_ROUNDS
          - ConflictError if offer.session_id != self.id
        """
        from src.negotiation.domain.events import OfferSubmitted

        if not self.status.is_active and self.status != SessionStatus.HUMAN_REVIEW:
            raise ConflictError(
                f"Cannot add offer to session {self.id}: "
                f"status is '{self.status.value}', expected an active state."
            )
        if self.round_count.value >= MAX_ROUNDS:
            raise ConflictError(
                f"Session {self.id} has reached max rounds ({MAX_ROUNDS})."
            )
        if offer.session_id != self.id:
            raise ConflictError(
                f"Offer session_id {offer.session_id} does not match "
                f"session id {self.id}."
            )
        self.offers.append(offer)
        object.__setattr__(
            self,
            "round_count",
            RoundNumber(value=self.round_count.value + 1),
        )

        # Advance DANP FSM
        self.transition(offer)

        self.touch()
        return OfferSubmitted(
            aggregate_id=self.id,
            event_type="OfferSubmitted",
            session_id=self.id,
            offer_id=offer.id,
            round_number=self.round_count.value,
            proposer_role=offer.proposer_role.value,
            price=offer.price.amount,
            is_human_override=offer.is_human_override,
        )

    def mark_agreed(
        self, agreed_price: OfferValue, agreed_terms: dict
    ) -> "SessionAgreed":
        """Transition to AGREED — price gap <= 2%."""
        from src.negotiation.domain.events import SessionAgreed

        if not self.status.is_active:
            raise ConflictError(
                f"Cannot agree session {self.id}: "
                f"status is '{self.status.value}', expected an active state."
            )
        self.status = SessionStatus.AGREED
        self.agreed_price = agreed_price
        self.agreed_terms = agreed_terms
        self.completed_at = _utcnow()
        self.touch()
        return SessionAgreed(
            aggregate_id=self.id,
            event_type="SessionAgreed",
            session_id=self.id,
            rfq_id=self.rfq_id,
            match_id=self.match_id,
            buyer_enterprise_id=self.buyer_enterprise_id,
            seller_enterprise_id=self.seller_enterprise_id,
            agreed_price=agreed_price.amount,
            agreed_currency=agreed_price.currency,
            agreed_terms=agreed_terms or {},
        )

    def mark_walk_away(self, reason: str = "Agent rejected") -> "SessionFailed":
        """Transition to WALK_AWAY — agent explicitly rejected."""
        from src.negotiation.domain.events import SessionFailed

        if not self.status.is_active and self.status != SessionStatus.HUMAN_REVIEW:
            raise ConflictError(
                f"Cannot walk away session {self.id}: "
                f"status is '{self.status.value}'."
            )
        self.status = SessionStatus.WALK_AWAY
        self.completed_at = _utcnow()
        self.touch()
        return SessionFailed(
            aggregate_id=self.id,
            event_type="SessionFailed",
            session_id=self.id,
            reason=f"WALK_AWAY: {reason}",
            round_count=self.round_count.value,
        )

    def mark_failed(self, reason: str) -> "SessionFailed":
        """Transition ACTIVE|HUMAN_REVIEW → FAILED."""
        from src.negotiation.domain.events import SessionFailed

        if not self.status.is_active and self.status != SessionStatus.HUMAN_REVIEW:
            raise ConflictError(
                f"Cannot fail session {self.id}: "
                f"status is '{self.status.value}'."
            )
        self.status = SessionStatus.FAILED
        self.completed_at = _utcnow()
        self.touch()
        return SessionFailed(
            aggregate_id=self.id,
            event_type="SessionFailed",
            session_id=self.id,
            reason=reason,
            round_count=self.round_count.value,
        )

    def mark_stalled(self) -> "SessionEscalated":
        """Transition to STALLED — no concession for 3+ rounds."""
        from src.negotiation.domain.events import SessionEscalated

        if not self.status.is_active:
            raise ConflictError(
                f"Cannot stall session {self.id}: "
                f"status is '{self.status.value}'."
            )
        self.status = SessionStatus.STALLED
        self.touch()
        return SessionEscalated(
            aggregate_id=self.id,
            event_type="SessionEscalated",
            session_id=self.id,
            round_count=self.round_count.value,
            escalation_reason="stall_detected",
        )

    def escalate_to_human_review(self) -> "SessionEscalated":
        """Transition STALLED|ACTIVE → HUMAN_REVIEW."""
        from src.negotiation.domain.events import SessionEscalated

        if self.status not in (
            SessionStatus.STALLED,
            SessionStatus.ACTIVE,
            SessionStatus.ROUND_LOOP,
            SessionStatus.BUYER_ANCHOR,
            SessionStatus.SELLER_RESPONSE,
        ):
            raise ConflictError(
                f"Cannot escalate session {self.id}: "
                f"status is '{self.status.value}', expected STALLED or active."
            )
        self.status = SessionStatus.HUMAN_REVIEW
        self.touch()
        return SessionEscalated(
            aggregate_id=self.id,
            event_type="SessionEscalated",
            session_id=self.id,
            round_count=self.round_count.value,
            escalation_reason="stall_detected",
        )

    def resume_from_human_review(self) -> None:
        """Transition HUMAN_REVIEW → ROUND_LOOP (or ACTIVE for compat)."""
        if self.status != SessionStatus.HUMAN_REVIEW:
            raise ConflictError(
                f"Cannot resume session {self.id}: "
                f"status is '{self.status.value}', expected HUMAN_REVIEW."
            )
        # Resume to ROUND_LOOP if we have enough offers, else ACTIVE
        if len(self.offers) >= 2:
            self.status = SessionStatus.ROUND_LOOP
        else:
            self.status = SessionStatus.ACTIVE
        self.touch()

    def mark_timeout(self) -> "SessionExpired":
        """Transition to TIMEOUT — 24h TTL expired."""
        from src.negotiation.domain.events import SessionExpired

        if self.status.is_terminal:
            raise ConflictError(
                f"Cannot timeout session {self.id}: "
                f"status is '{self.status.value}'."
            )
        self.status = SessionStatus.TIMEOUT
        self.completed_at = _utcnow()
        self.touch()
        return SessionExpired(
            aggregate_id=self.id,
            event_type="SessionExpired",
            session_id=self.id,
        )

    def mark_expired(self) -> "SessionExpired":
        """Transition ACTIVE|HUMAN_REVIEW → EXPIRED (legacy compat)."""
        from src.negotiation.domain.events import SessionExpired

        if self.status.is_terminal:
            raise ConflictError(
                f"Cannot expire session {self.id}: "
                f"status is '{self.status.value}'."
            )
        self.status = SessionStatus.EXPIRED
        self.completed_at = _utcnow()
        self.touch()
        return SessionExpired(
            aggregate_id=self.id,
            event_type="SessionExpired",
            session_id=self.id,
        )

    def mark_policy_breach(self, reason: str = "Schema validation failed 3x") -> "SessionFailed":
        """Transition to POLICY_BREACH — 3x schema failures."""
        from src.negotiation.domain.events import SessionFailed

        if self.status.is_terminal:
            raise ConflictError(
                f"Cannot breach session {self.id}: "
                f"status is '{self.status.value}'."
            )
        self.status = SessionStatus.POLICY_BREACH
        self.completed_at = _utcnow()
        self.touch()
        return SessionFailed(
            aggregate_id=self.id,
            event_type="SessionFailed",
            session_id=self.id,
            reason=f"POLICY_BREACH: {reason}",
            round_count=self.round_count.value,
        )

    def record_schema_failure(self) -> bool:
        """
        Record a schema validation failure.

        Returns True if max failures reached (should transition to POLICY_BREACH).
        """
        self.schema_failure_count += 1
        self.touch()
        return self.schema_failure_count >= MAX_SCHEMA_FAILURES

    def record_no_concession(self) -> bool:
        """
        Record a round with no meaningful concession.

        Returns True if stall threshold reached.
        """
        self.stall_counter += 1
        self.touch()
        return self.stall_counter >= STALL_ROUNDS

    def reset_stall_counter(self) -> None:
        """Reset stall counter when concession is detected."""
        self.stall_counter = 0
        self.touch()

    # ── Query Helpers ──────────────────────────────────────────────────────────

    def get_last_buyer_offer(self) -> Offer | None:
        """Most recent offer from ProposerRole.BUYER, or None."""
        for offer in reversed(self.offers):
            if offer.proposer_role == ProposerRole.BUYER:
                return offer
        return None

    def get_last_seller_offer(self) -> Offer | None:
        """Most recent offer from ProposerRole.SELLER, or None."""
        for offer in reversed(self.offers):
            if offer.proposer_role == ProposerRole.SELLER:
                return offer
        return None

    def get_buyer_prices(self) -> list[Decimal]:
        """All buyer offer prices in chronological order."""
        return [
            o.price.amount
            for o in self.offers
            if o.proposer_role == ProposerRole.BUYER
        ]

    def get_seller_prices(self) -> list[Decimal]:
        """All seller offer prices in chronological order."""
        return [
            o.price.amount
            for o in self.offers
            if o.proposer_role == ProposerRole.SELLER
        ]

    def is_expired(self) -> bool:
        """True if current time > expires_at."""
        return _utcnow() > self.expires_at

    def is_agreed(self) -> bool:
        """True if status is AGREED."""
        return self.status == SessionStatus.AGREED

    def check_convergence(self, tolerance: float = CONVERGENCE_TOLERANCE) -> bool:
        """Check if buyer and seller prices have converged within tolerance."""
        last_buyer = self.get_last_buyer_offer()
        last_seller = self.get_last_seller_offer()
        if not last_buyer or not last_seller:
            return False
        buyer_price = last_buyer.price.amount
        seller_price = last_seller.price.amount
        if buyer_price <= Decimal("0"):
            return False
        gap = abs(seller_price - buyer_price) / buyer_price
        return float(gap) <= tolerance

    @property
    def next_proposer(self) -> ProposerRole:
        """
        Determine whose turn it is next.

        New sessions (SELLER_ANCHOR): seller goes first.
        Legacy in-flight sessions (BUYER_ANCHOR): buyer goes first.
        All subsequent rounds: strict alternation.
        """
        if not self.offers:
            # Legacy sessions activated before the FSM flip keep buyer-first
            if self.status == SessionStatus.BUYER_ANCHOR:
                return ProposerRole.BUYER
            return ProposerRole.SELLER
        last = self.offers[-1].proposer_role
        return ProposerRole.SELLER if last == ProposerRole.BUYER else ProposerRole.BUYER


# Avoid circular import — domain events imported lazily inside methods.
# Explicit re-imports at module bottom for type-checkers.
from src.negotiation.domain.events import (  # noqa: E402, F401
    OfferSubmitted,
    SessionAgreed,
    SessionEscalated,
    SessionExpired,
    SessionFailed,
)
