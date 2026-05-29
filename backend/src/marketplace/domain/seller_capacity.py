# Hexagonal Architecture: zero framework imports. Pure Python domain entity.

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from src.shared.domain.base_entity import BaseEntity
from src.shared.domain.exceptions import ValidationError


class ShiftPattern(str, Enum):
    SINGLE_SHIFT = "SINGLE_SHIFT"
    DOUBLE_SHIFT = "DOUBLE_SHIFT"
    TRIPLE_SHIFT = "TRIPLE_SHIFT"
    CONTINUOUS = "CONTINUOUS"


class TransportMode(str, Enum):
    ROAD = "ROAD"
    RAIL = "RAIL"
    SEA = "SEA"
    AIR = "AIR"


@dataclass
class SellerCapacityProfile(BaseEntity):
    """
    Seller production capacity and logistics profile.

    Captures manufacturing capacity, dispatch timelines, delivery radius,
    and transport capabilities — critical for delivery feasibility checks.
    """

    enterprise_id: uuid.UUID = field(default_factory=uuid.uuid4)
    monthly_production_capacity_mt: Decimal = Decimal("0")
    current_utilization_pct: int = 0
    available_capacity_mt: Decimal | None = None
    num_production_lines: int = 1
    shift_pattern: ShiftPattern = ShiftPattern.SINGLE_SHIFT
    avg_dispatch_days: int = 3
    max_delivery_radius_km: int | None = None
    has_own_transport: bool = False
    preferred_transport_modes: list[str] = field(default_factory=list)
    ex_works_available: bool = True

    def __post_init__(self) -> None:
        if self.available_capacity_mt is None:
            self.available_capacity_mt = self._compute_available_capacity()

    def _compute_available_capacity(self) -> Decimal:
        """Compute available capacity from total capacity and utilization."""
        if self.monthly_production_capacity_mt <= Decimal("0"):
            return Decimal("0")
        utilization = Decimal(str(self.current_utilization_pct)) / Decimal("100")
        return self.monthly_production_capacity_mt * (Decimal("1") - utilization)

    def validate(self) -> None:
        if self.monthly_production_capacity_mt <= Decimal("0"):
            raise ValidationError(
                "Monthly production capacity must be > 0.",
                field="monthly_production_capacity_mt",
            )
        if not 0 <= self.current_utilization_pct <= 100:
            raise ValidationError(
                "Utilization must be 0-100%.",
                field="current_utilization_pct",
            )
        if self.avg_dispatch_days < 1:
            raise ValidationError(
                "Average dispatch days must be >= 1.",
                field="avg_dispatch_days",
            )

    def can_fulfill_order(self, qty_mt: Decimal, delivery_window_days: int) -> bool:
        """
        Check if seller can fulfill the order within the delivery window.

        Multi-month capacity: if delivery window spans multiple months,
        seller can produce across those months.
        """
        available = self.available_capacity_mt or self._compute_available_capacity()
        months_available = max(Decimal(str(delivery_window_days)) / Decimal("30"), Decimal("1"))
        total_producible = available * months_available
        return qty_mt <= total_producible

    def update_utilization(self, new_pct: int) -> None:
        if not 0 <= new_pct <= 100:
            raise ValidationError("Utilization must be 0-100%.", field="current_utilization_pct")
        self.current_utilization_pct = new_pct
        self.available_capacity_mt = self._compute_available_capacity()
        self.touch()

    def decrement_capacity(self, qty_mt: Decimal) -> None:
        """Reduce available capacity after order confirmation."""
        if self.available_capacity_mt is not None:
            self.available_capacity_mt = max(
                Decimal("0"),
                self.available_capacity_mt - qty_mt,
            )
            self.touch()
