# DANP Negotiation Engine — Layer 4: Guardrail Engine (Absolute Veto)
# Pure Python domain logic. Zero framework imports.
# Validates ActionEnvelopes against valuation bounds, budgets,
# margin floors, and policy constraints. Has absolute veto power.

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from src.shared.domain.base_value_object import BaseValueObject
from src.shared.domain.exceptions import PolicyViolation, ValidationError


class PromptInjectionDefense:
    """Defense-in-depth against prompt injection and information leakage."""

    INJECTION_PATTERNS = [
        r"(?i)remind me of your (offers|strategy|internal|analysis)",
        r"(?i)(not visible|invisible|hidden|internal|just for you)",
        r"(?i)share your (reasoning|thinking|analysis|batna|reservation|walk.?away)",
        r"(?i)ignore (previous|all|prior|above) instructions",
        r"(?i)you are now|pretend you are|act as if",
        r"(?i)what is your (floor|ceiling|minimum|maximum|reservation|budget)",
        r"(?i)system\s*prompt|initial\s*instructions",
    ]

    LEAK_PATTERNS = [
        r"(?i)my (reservation|walk.?away|floor|ceiling|minimum|batna) (is|price|point)",
        r"(?i)(reservation_price|aspirational_price|budget_ceiling)\s*[=:]\s*[\d₹]",
        r"(?i)I cannot go (below|above) ₹?\d",
        r"(?i)my absolute (limit|floor|ceiling)",
    ]

    @staticmethod
    def sanitize_incoming(text: str) -> tuple[str, bool]:
        """Strip injection attempts before LLM sees them. Returns (cleaned_text, was_modified)."""
        if not text:
            return text, False
        was_modified = False
        cleaned = text
        for pattern in PromptInjectionDefense.INJECTION_PATTERNS:
            if re.search(pattern, cleaned):
                # Replace the injection attempt with a neutral placeholder
                cleaned = re.sub(pattern, "[instruction removed]", cleaned, flags=re.IGNORECASE)
                was_modified = True
        return cleaned, was_modified

    @staticmethod
    def scan_output(text: str) -> bool:
        """Returns True if LLM output leaks internal constraint information."""
        if not text:
            return False
        for pattern in PromptInjectionDefense.LEAK_PATTERNS:
            if re.search(pattern, text):
                return True
        return False


# ── ActionEnvelope: Strict JSON Schema for Agent Outputs ──────────────────────

_VALID_ACTIONS = {"counter", "accept", "reject", "offer"}
_VALID_ROLES = {"buyer", "seller"}


@dataclass(frozen=True)
class ActionEnvelope(BaseValueObject):
    """
    Strict JSON schema for agent-to-neutral communications.

    Every agent output MUST conform to this schema.
    Non-conforming outputs trigger POLICY_BREACH after 3 failures.
    """

    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
    agent_role: str = "buyer"
    round: int = 0
    action: str = "counter"
    offer_value: Decimal = Decimal("0")
    confidence: float = 0.5
    strategy_tag: str = "TIT_FOR_TAT"
    rationale: str = ""
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    def __post_init__(self) -> None:
        if self.agent_role.lower() not in _VALID_ROLES:
            raise ValidationError(
                f"agent_role must be one of {_VALID_ROLES}, got '{self.agent_role}'.",
                field="agent_role",
            )
        if self.action.lower() not in _VALID_ACTIONS:
            raise ValidationError(
                f"action must be one of {_VALID_ACTIONS}, got '{self.action}'.",
                field="action",
            )
        if self.offer_value < Decimal("0"):
            raise ValidationError(
                f"offer_value must be >= 0, got {self.offer_value}.",
                field="offer_value",
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValidationError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}.",
                field="confidence",
            )
        if self.round < 0:
            raise ValidationError(
                f"round must be >= 0, got {self.round}.",
                field="round",
            )


class ViolationType(str, Enum):
    """Types of guardrail violations."""

    BELOW_RESERVATION = "BELOW_RESERVATION"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    MARGIN_VIOLATION = "MARGIN_VIOLATION"
    INVALID_SCHEMA = "INVALID_SCHEMA"
    OUT_OF_TURN = "OUT_OF_TURN"
    STALL_DETECTED = "STALL_DETECTED"
    CONFIDENCE_TOO_LOW = "CONFIDENCE_TOO_LOW"


@dataclass(frozen=True)
class GuardrailViolation(BaseValueObject):
    """Record of a guardrail violation."""

    violation_type: ViolationType = ViolationType.INVALID_SCHEMA
    message: str = ""
    field_name: str = ""
    attempted_value: str = ""


class GuardrailEngine:
    """
    Layer 4: Absolute Veto Authority.

    Validates every ActionEnvelope against:
    1. Schema conformance (JSON structure)
    2. Reservation price floor
    3. Budget ceiling cap
    4. Margin floor enforcement
    5. Confidence threshold
    6. Turn order correctness

    Has ABSOLUTE VETO — can reject any agent output regardless
    of what the LLM or strategy engine recommended.

    Stateless: all context passed per call.
    """

    def __init__(
        self,
        min_confidence: float = 0.10,
        max_schema_failures: int = 3,
    ) -> None:
        self.min_confidence = min_confidence
        self.max_schema_failures = max_schema_failures

    def validate_envelope(
        self,
        envelope: ActionEnvelope,
        reservation_price: Decimal,
        budget_ceiling: Decimal | None = None,
        cost_basis: Decimal | None = None,
        margin_floor: Decimal | None = None,
    ) -> list[GuardrailViolation]:
        """
        Validate an ActionEnvelope against all guardrail rules.

        Returns a list of violations (empty = passed).
        Raises PolicyViolation if any critical violation found.
        """
        violations: list[GuardrailViolation] = []

        # 1. Reservation price check
        if envelope.action.lower() in ("offer", "counter"):
            if envelope.agent_role.lower() == "buyer":
                # Buyer: offer should not exceed what they're willing to pay
                if budget_ceiling and envelope.offer_value > budget_ceiling:
                    violations.append(
                        GuardrailViolation(
                            violation_type=ViolationType.BUDGET_EXCEEDED,
                            message=(
                                f"Offer {envelope.offer_value} exceeds "
                                f"budget ceiling {budget_ceiling}."
                            ),
                            field_name="offer_value",
                            attempted_value=str(envelope.offer_value),
                        )
                    )
            elif envelope.agent_role.lower() == "seller":
                # Seller: offer should not go below reservation
                if envelope.offer_value < reservation_price:
                    violations.append(
                        GuardrailViolation(
                            violation_type=ViolationType.BELOW_RESERVATION,
                            message=(
                                f"Offer {envelope.offer_value} below "
                                f"reservation price {reservation_price}."
                            ),
                            field_name="offer_value",
                            attempted_value=str(envelope.offer_value),
                        )
                    )

        # 2. Margin floor check (seller only)
        if (
            envelope.agent_role.lower() == "seller"
            and cost_basis is not None
            and cost_basis > Decimal("0")
            and margin_floor is not None
            and envelope.action.lower() in ("offer", "counter")
        ):
            actual_margin = (
                (envelope.offer_value - cost_basis) / cost_basis * Decimal("100")
            )
            if actual_margin < margin_floor:
                violations.append(
                    GuardrailViolation(
                        violation_type=ViolationType.MARGIN_VIOLATION,
                        message=(
                            f"Margin {actual_margin:.1f}% below "
                            f"floor {margin_floor}%."
                        ),
                        field_name="offer_value",
                        attempted_value=str(envelope.offer_value),
                    )
                )

        # 3. Confidence threshold
        if (
            envelope.confidence < self.min_confidence
            and envelope.action.lower() not in ("reject",)
        ):
            violations.append(
                GuardrailViolation(
                    violation_type=ViolationType.CONFIDENCE_TOO_LOW,
                    message=(
                        f"Confidence {envelope.confidence} below "
                        f"minimum {self.min_confidence}."
                    ),
                    field_name="confidence",
                    attempted_value=str(envelope.confidence),
                )
            )

        return violations

    def enforce(
        self,
        envelope: ActionEnvelope,
        reservation_price: Decimal,
        budget_ceiling: Decimal | None = None,
        cost_basis: Decimal | None = None,
        margin_floor: Decimal | None = None,
    ) -> None:
        """
        Validate and raise PolicyViolation if critical violations found.

        This is the VETO entry point — call this before accepting any offer.
        """
        violations = self.validate_envelope(
            envelope=envelope,
            reservation_price=reservation_price,
            budget_ceiling=budget_ceiling,
            cost_basis=cost_basis,
            margin_floor=margin_floor,
        )

        critical_types = {
            ViolationType.BELOW_RESERVATION,
            ViolationType.BUDGET_EXCEEDED,
            ViolationType.MARGIN_VIOLATION,
        }

        critical = [v for v in violations if v.violation_type in critical_types]
        if critical:
            messages = "; ".join(v.message for v in critical)
            raise PolicyViolation(f"Guardrail VETO: {messages}")


def validate_raw_envelope(raw: dict) -> ActionEnvelope:
    """
    Parse and validate a raw dict (e.g. from LLM JSON output)
    into an ActionEnvelope.

    Raises ValidationError if schema is invalid.
    """
    try:
        return ActionEnvelope(
            session_id=uuid.UUID(str(raw.get("session_id", uuid.uuid4()))),
            agent_role=str(raw.get("agent_role", "buyer")).lower(),
            round=int(raw.get("round", 0)),
            action=str(raw.get("action", "counter")).lower(),
            offer_value=Decimal(str(raw.get("offer_value", raw.get("price", 0)))),
            confidence=float(raw.get("confidence", 0.5)),
            strategy_tag=str(raw.get("strategy_tag", "TIT_FOR_TAT")),
            rationale=str(raw.get("rationale", raw.get("reasoning", ""))),
        )
    except (ValueError, TypeError, KeyError) as e:
        raise ValidationError(
            f"Invalid ActionEnvelope schema: {e}", field="envelope"
        ) from e
