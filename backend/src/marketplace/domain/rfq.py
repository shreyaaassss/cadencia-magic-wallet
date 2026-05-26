# context.md §3 — Hexagonal Architecture: zero framework imports.
# RFQ aggregate root with state machine: DRAFT → PARSED → MATCHED → CONFIRMED → SETTLED

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from src.marketplace.domain.value_objects import (
    BudgetRange,
    DeliveryWindow,
    HSNCode,
    RFQStatus,
)
from src.shared.domain.base_entity import BaseEntity
from src.shared.domain.exceptions import ConflictError, ValidationError


@dataclass
class RFQ(BaseEntity):
    """RFQ aggregate root (marketplace bounded context)."""

    buyer_enterprise_id: uuid.UUID = field(default_factory=uuid.uuid4)
    raw_document: str | None = None
    parsed_fields: dict | None = None
    hsn_code: HSNCode | None = None
    budget_range: BudgetRange | None = None
    delivery_window: DeliveryWindow | None = None
    geography_pref: str = "IN"
    status: RFQStatus = RFQStatus.DRAFT
    confirmed_match_id: uuid.UUID | None = None
    expires_at: datetime | None = None
    embedding: list[float] | None = None
    all_products: list | None = None  # All product names from multi-product RFQ

    def mark_parsed(self, parsed_fields: dict) -> dict:
        """
        Transition: DRAFT → PARSED.

        Accepts partial extraction — missing fields stored as None.
        Returns event payload for RFQParsed.
        """
        if self.status != RFQStatus.DRAFT:
            raise ConflictError(
                f"Cannot parse RFQ in status {self.status.value}, expected DRAFT."
            )
        if not parsed_fields.get("product"):
            raise ValidationError(
                "Parsed fields must include at least 'product'.",
                field="parsed_fields",
            )

        self.parsed_fields = parsed_fields
        self.status = RFQStatus.PARSED

        # Extract typed value objects — partial OK
        hsn_raw = parsed_fields.get("hsn_code")
        if hsn_raw:
            try:
                self.hsn_code = HSNCode(value=str(hsn_raw))
            except ValidationError:
                self.hsn_code = None  # Graceful: bad HSN stored as None

        budget_min = parsed_fields.get("budget_min")
        budget_max = parsed_fields.get("budget_max")
        if budget_min is not None and budget_max is not None:
            try:
                self.budget_range = BudgetRange(
                    min_value=Decimal(str(budget_min)),
                    max_value=Decimal(str(budget_max)),
                )
            except (ValidationError, Exception):
                self.budget_range = None

        dw_start = parsed_fields.get("delivery_window_start")
        dw_end = parsed_fields.get("delivery_window_end")
        if dw_start and dw_end:
            try:
                self.delivery_window = DeliveryWindow(
                    start_date=date.fromisoformat(str(dw_start)),
                    end_date=date.fromisoformat(str(dw_end)),
                )
            except (ValidationError, ValueError):
                self.delivery_window = None

        geo = parsed_fields.get("geography")
        if geo:
            self.geography_pref = str(geo)

        self.touch()

        return {
            "rfq_id": self.id,
            "buyer_enterprise_id": self.buyer_enterprise_id,
            "hsn_code": str(self.hsn_code.value) if self.hsn_code else None,
            "has_budget": self.budget_range is not None,
            "has_delivery_window": self.delivery_window is not None,
        }

    def mark_matched(self, match_count: int) -> dict:
        """Transition: PARSED → MATCHED."""
        if self.status != RFQStatus.PARSED:
            raise ConflictError(
                f"Cannot match RFQ in status {self.status.value}, expected PARSED."
            )
        if match_count <= 0:
            raise ValidationError(
                "match_count must be > 0 to transition to MATCHED.",
                field="match_count",
            )
        self.status = RFQStatus.MATCHED
        self.touch()
        return {
            "rfq_id": self.id,
            "buyer_enterprise_id": self.buyer_enterprise_id,
            "match_count": match_count,
        }

    def start_negotiations(self, match_count: int) -> dict:
        """Transition: MATCHED → NEGOTIATING."""
        if self.status != RFQStatus.MATCHED:
            raise ConflictError(
                f"Cannot start negotiations for RFQ in status {self.status.value}, expected MATCHED."
            )
        if match_count <= 0:
            raise ValidationError(
                "match_count must be > 0 to start negotiations.",
                field="match_count",
            )
        self.status = RFQStatus.NEGOTIATING
        self.touch()
        return {
            "rfq_id": self.id,
            "buyer_enterprise_id": self.buyer_enterprise_id,
            "match_count": match_count,
        }

    def confirm(self, selected_match_id: uuid.UUID) -> dict:
        """Transition: MATCHED|NEGOTIATING → CONFIRMED."""
        if self.status not in (RFQStatus.MATCHED, RFQStatus.NEGOTIATING):
            raise ConflictError(
                f"Cannot confirm RFQ in status {self.status.value}, expected MATCHED or NEGOTIATING."
            )
        self.status = RFQStatus.CONFIRMED
        self.confirmed_match_id = selected_match_id
        self.touch()
        return {
            "rfq_id": self.id,
            "match_id": selected_match_id,
            "buyer_enterprise_id": self.buyer_enterprise_id,
        }

    def mark_settled(self) -> dict:
        """Transition: CONFIRMED → SETTLED."""
        if self.status != RFQStatus.CONFIRMED:
            raise ConflictError(
                f"Cannot settle RFQ in status {self.status.value}, expected CONFIRMED."
            )
        self.status = RFQStatus.SETTLED
        self.touch()
        return {"rfq_id": self.id}

    def mark_expired(self) -> None:
        """Transition: any (except CONFIRMED / SETTLED) → EXPIRED."""
        if self.status in (RFQStatus.CONFIRMED, RFQStatus.SETTLED):
            raise ConflictError(
                f"Cannot expire RFQ in status {self.status.value}."
            )
        self.status = RFQStatus.EXPIRED
        self.touch()
