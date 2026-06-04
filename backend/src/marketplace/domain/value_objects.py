# context.md §3 — Hexagonal Architecture: zero framework imports in domain layer.
# Pure Python frozen dataclasses. stdlib only.

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from src.shared.domain.base_value_object import BaseValueObject
from src.shared.domain.exceptions import ValidationError

_VALID_CURRENCIES = {"INR", "USDC"}
_HSN_PATTERN = re.compile(r"^\d{4,8}$")


@dataclass(frozen=True)
class HSNCode(BaseValueObject):
    """HSN tariff classification code (4–8 digits)."""

    value: str = ""

    def __post_init__(self) -> None:
        if not _HSN_PATTERN.match(self.value):
            raise ValidationError(
                f"HSN code must be 4–8 digits, got '{self.value}'.",
                field="hsn_code",
            )


@dataclass(frozen=True)
class BudgetRange(BaseValueObject):
    """Budget range with min/max values and currency."""

    min_value: Decimal = Decimal("0")
    max_value: Decimal = Decimal("0")
    currency: str = "INR"

    def __post_init__(self) -> None:
        if self.min_value < Decimal("0"):
            raise ValidationError(
                f"Budget min_value must be >= 0, got {self.min_value}.",
                field="min_value",
            )
        if self.max_value < Decimal("0"):
            raise ValidationError(
                f"Budget max_value must be >= 0, got {self.max_value}.",
                field="max_value",
            )
        if self.min_value > self.max_value:
            raise ValidationError(
                f"Budget min_value ({self.min_value}) > max_value ({self.max_value}).",
                field="budget_range",
            )
        if self.currency not in _VALID_CURRENCIES:
            raise ValidationError(
                f"Currency must be one of {_VALID_CURRENCIES}, got '{self.currency}'.",
                field="currency",
            )


@dataclass(frozen=True)
class DeliveryWindow(BaseValueObject):
    """Delivery date range."""

    start_date: date = date.min
    end_date: date = date.min

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise ValidationError(
                f"DeliveryWindow start ({self.start_date}) > end ({self.end_date}).",
                field="delivery_window",
            )


@dataclass(frozen=True)
class SimilarityScore(BaseValueObject):
    """Cosine similarity score in [0.0, 1.0]."""

    value: float = 0.0

    def __post_init__(self) -> None:
        if not (0.0 <= self.value <= 1.0):
            raise ValidationError(
                f"SimilarityScore must be in [0.0, 1.0], got {self.value}.",
                field="similarity_score",
            )


class RFQStatus(Enum):
    DRAFT = "DRAFT"
    PARSE_FAILED = "PARSE_FAILED"
    PARSED = "PARSED"
    MATCHED = "MATCHED"
    NEGOTIATING = "NEGOTIATING"
    CONFIRMED = "CONFIRMED"
    SETTLED = "SETTLED"
    EXPIRED = "EXPIRED"


class MatchStatus(Enum):
    PENDING = "PENDING"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
