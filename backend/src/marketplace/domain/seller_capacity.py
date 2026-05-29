# Hexagonal Architecture: zero framework imports. Pure Python domain entity.

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from src.shared.domain.base_entity import BaseEntity
from src.shared.domain.exceptions import ValidationError


class OperatingSchedule(str, Enum):
    STANDARD_HOURS   = "STANDARD_HOURS"    # 9-6 Mon-Fri
    EXTENDED_HOURS   = "EXTENDED_HOURS"    # Early/late shifts
    TWENTY_FOUR_SEVEN = "TWENTY_FOUR_SEVEN" # 24x7 operations
    PROJECT_BASED    = "PROJECT_BASED"     # Milestone / project delivery
    ON_DEMAND        = "ON_DEMAND"         # Triggered on order
    SEASONAL         = "SEASONAL"          # Peak-season dependent


class ServiceCoverage(str, Enum):
    LOCAL         = "LOCAL"         # City / ~200 km
    REGIONAL      = "REGIONAL"      # State / ~1 000 km
    NATIONAL      = "NATIONAL"      # All India
    INTERNATIONAL = "INTERNATIONAL" # Cross-border


class VolumeUnit(str, Enum):
    MT       = "MT"
    UNITS    = "UNITS"
    KG       = "KG"
    LITRES   = "LITRES"
    HOURS    = "HOURS"
    LICENCES = "LICENCES"
    PROJECTS = "PROJECTS"
    SQ_FT    = "SQ_FT"
    CUSTOM   = "CUSTOM"


@dataclass
class SellerCapacityProfile(BaseEntity):
    """
    Seller operational capacity and fulfilment profile — industry-agnostic.

    Replaces the manufacturing-centric design (MT, shift patterns, delivery
    radius) with a generalised schema that works for raw materials, software,
    services, FMCG, healthcare, etc.
    """

    enterprise_id: uuid.UUID = field(default_factory=uuid.uuid4)

    # ── Volume ────────────────────────────────────────────────────────────────
    monthly_volume: Decimal = Decimal("0")          # Numeric quantity per month
    volume_unit: VolumeUnit = VolumeUnit.MT         # Unit for monthly_volume
    current_utilization_pct: int = 0
    available_volume: Decimal | None = None         # Computed from utilisation

    # ── Operations ───────────────────────────────────────────────────────────
    num_production_lines: int = 1                   # Lines / teams / streams
    operating_schedule: OperatingSchedule = OperatingSchedule.STANDARD_HOURS
    avg_dispatch_days: int = 3                      # Avg lead / fulfillment time

    # ── Logistics / Reach ─────────────────────────────────────────────────────
    service_coverage: ServiceCoverage = ServiceCoverage.NATIONAL
    has_own_transport: bool = False
    fulfillment_method: list[str] = field(default_factory=list)
    ex_works_available: bool = True

    def __post_init__(self) -> None:
        if self.available_volume is None:
            self.available_volume = self._compute_available()

    def _compute_available(self) -> Decimal:
        if self.monthly_volume <= Decimal("0"):
            return Decimal("0")
        utilization = Decimal(str(self.current_utilization_pct)) / Decimal("100")
        return self.monthly_volume * (Decimal("1") - utilization)

    def validate(self) -> None:
        if self.monthly_volume <= Decimal("0"):
            raise ValidationError(
                "Monthly volume must be > 0.",
                field="monthly_volume",
            )
        if not 0 <= self.current_utilization_pct <= 100:
            raise ValidationError(
                "Utilization must be 0–100%.",
                field="current_utilization_pct",
            )
        if self.avg_dispatch_days < 1:
            raise ValidationError(
                "Average dispatch/fulfillment days must be >= 1.",
                field="avg_dispatch_days",
            )

    def can_fulfill_order(self, qty: Decimal, delivery_window_days: int) -> bool:
        """
        Generic capacity check — unit-agnostic numeric comparison.

        Works for MT, units, hours, licences, etc. The caller must ensure
        the RFQ quantity is expressed in the same unit as monthly_volume.
        """
        available = self.available_volume or self._compute_available()
        months_available = max(
            Decimal(str(delivery_window_days)) / Decimal("30"),
            Decimal("1"),
        )
        total_producible = available * months_available
        return qty <= total_producible

    def update_utilization(self, new_pct: int) -> None:
        if not 0 <= new_pct <= 100:
            raise ValidationError("Utilization must be 0–100%.", field="current_utilization_pct")
        self.current_utilization_pct = new_pct
        self.available_volume = self._compute_available()
        self.touch()

    def decrement_capacity(self, qty: Decimal) -> None:
        """Reduce available volume after order confirmation."""
        if self.available_volume is not None:
            self.available_volume = max(Decimal("0"), self.available_volume - qty)
            self.touch()
