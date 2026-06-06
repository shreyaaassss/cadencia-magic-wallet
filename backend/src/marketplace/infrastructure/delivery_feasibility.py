# Delivery feasibility calculations for buyer-seller matching.
# Haversine distance, transit time estimation, capacity checks.

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.marketplace.infrastructure.models import PincodeGeocodeModel
from src.shared.infrastructure.logging import get_logger

log = get_logger(__name__)

_EARTH_RADIUS_KM = 6_371.0
_ROAD_DISTANCE_MULTIPLIER = 1.3
_BUFFER_DAYS = 2

# (max_km, transit_days)
_TRANSIT_BANDS: list[tuple[float, int]] = [
    (200, 2),
    (500, 3),
    (1_000, 5),
    (1_500, 7),
    (2_500, 10),
    (float("inf"), 15),
]


@dataclass
class DeliveryFeasibility:
    """Result of a delivery feasibility check between two pincodes."""
    is_feasible: bool
    distance_km: int
    transit_days: int
    total_days: int
    buffer_days: int = _BUFFER_DAYS
    urgency_level: str = "LOW"  # LOW, MODERATE, HIGH, CRITICAL


def _urgency_level(buffer_remaining: int) -> str:
    if buffer_remaining >= 10:
        return "LOW"
    if buffer_remaining >= 5:
        return "MODERATE"
    if buffer_remaining >= 2:
        return "HIGH"
    return "CRITICAL"


class DeliveryFeasibilityService:
    """Calculates delivery feasibility between Indian pincodes."""

    @staticmethod
    def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Great-circle distance between two points (km)."""
        lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return _EARTH_RADIUS_KM * c

    @staticmethod
    def estimate_transit_days(distance_km: float) -> int:
        """Estimate transit days from distance bands (Indian logistics)."""
        for max_km, days in _TRANSIT_BANDS:
            if distance_km <= max_km:
                return days
        return _TRANSIT_BANDS[-1][1]

    @staticmethod
    def compute_total_delivery_days(lead_time_days: int, distance_km: float) -> int:
        """Total = manufacturing lead + transit + buffer."""
        transit = DeliveryFeasibilityService.estimate_transit_days(distance_km)
        return lead_time_days + transit + _BUFFER_DAYS

    async def check_feasibility(
        self,
        seller_pincode: str,
        buyer_pincode: str,
        lead_time_days: int,
        delivery_window_days: int,
        session: AsyncSession,
    ) -> DeliveryFeasibility:
        """End-to-end feasibility check between seller and buyer pincodes."""
        stmt = select(PincodeGeocodeModel).where(
            PincodeGeocodeModel.pincode.in_([seller_pincode, buyer_pincode])
        )
        result = await session.execute(stmt)
        rows = {row.pincode: row for row in result.scalars().all()}

        seller_geo = rows.get(seller_pincode)
        buyer_geo = rows.get(buyer_pincode)

        # Fallback to state centroid when pincode not in geocode table.
        # New SEZs, developments, or pincodes not in seed data should not
        # silently mark the seller as infeasible.
        if seller_geo is None or buyer_geo is None:
            from sqlalchemy import func as sa_func

            # Try state-level centroid as fallback
            missing = []
            if seller_geo is None:
                missing.append(("seller", seller_pincode))
            if buyer_geo is None:
                missing.append(("buyer", buyer_pincode))

            for role, pincode in missing:
                # Derive state from pincode prefix (first 2 digits)
                state_stmt = (
                    select(
                        sa_func.avg(PincodeGeocodeModel.latitude).label("lat"),
                        sa_func.avg(PincodeGeocodeModel.longitude).label("lon"),
                    )
                    .where(PincodeGeocodeModel.pincode.like(f"{pincode[:2]}%"))
                )
                centroid_result = await session.execute(state_stmt)
                centroid = centroid_result.one_or_none()
                if centroid and centroid.lat is not None:
                    # Create a synthetic geo object
                    class _CentroidGeo:
                        def __init__(self, lat: float, lon: float):
                            self.latitude = lat
                            self.longitude = lon
                    geo = _CentroidGeo(centroid.lat, centroid.lon)
                    if role == "seller":
                        seller_geo = geo
                    else:
                        buyer_geo = geo
                    log.info("geocode_state_centroid_fallback", pincode=pincode, role=role)

            # If still missing after fallback, return infeasible
            if seller_geo is None or buyer_geo is None:
                log.warning(
                    "pincode_geocode_missing_no_fallback",
                    seller_pincode=seller_pincode,
                    buyer_pincode=buyer_pincode,
                )
                return DeliveryFeasibility(
                    is_feasible=False, distance_km=0, transit_days=0,
                    total_days=0, urgency_level="CRITICAL",
                )

        haversine_km = self.haversine_distance(
            seller_geo.latitude, seller_geo.longitude,
            buyer_geo.latitude, buyer_geo.longitude,
        )
        road_km = haversine_km * _ROAD_DISTANCE_MULTIPLIER
        transit_days = self.estimate_transit_days(road_km)
        total_days = lead_time_days + transit_days + _BUFFER_DAYS
        is_feasible = total_days <= delivery_window_days
        buffer_remaining = delivery_window_days - total_days
        urgency = _urgency_level(buffer_remaining)

        log.info(
            "delivery_feasibility_computed",
            seller_pincode=seller_pincode,
            buyer_pincode=buyer_pincode,
            road_km=round(road_km, 1),
            total_days=total_days,
            delivery_window_days=delivery_window_days,
            is_feasible=is_feasible,
            urgency_level=urgency,
        )

        return DeliveryFeasibility(
            is_feasible=is_feasible,
            distance_km=round(road_km),
            transit_days=transit_days,
            total_days=total_days,
            urgency_level=urgency,
        )

    @staticmethod
    async def check_capacity_feasibility(
        available_capacity_mt: Decimal,
        order_qty_mt: Decimal,
        delivery_window_days: int,
    ) -> bool:
        """Check if seller can produce qty within delivery window (pro-rata monthly capacity)."""
        if delivery_window_days <= 0:
            return False
        scaled_capacity = available_capacity_mt * Decimal(delivery_window_days) / Decimal(30)
        return order_qty_mt <= scaled_capacity
