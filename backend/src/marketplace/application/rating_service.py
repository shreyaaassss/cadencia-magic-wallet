"""Seller rating service.

Buyers can rate sellers after escrow is RELEASED. One rating per escrow.
Validates: only buyer can rate, only after RELEASED, max 1 per escrow.
"""

from __future__ import annotations

import uuid

import structlog

log = structlog.get_logger(__name__)


class SellerRatingService:
    """Manages post-delivery seller ratings."""

    def __init__(self, session: object) -> None:
        self._session = session

    async def submit_rating(
        self,
        escrow_id: uuid.UUID,
        buyer_enterprise_id: uuid.UUID,
        rating: int,
        feedback_text: str | None = None,
        delivery_quality: int | None = None,
        communication_quality: int | None = None,
    ) -> dict:
        """Submit a seller rating for a completed escrow."""
        from sqlalchemy import select

        from src.marketplace.infrastructure.models import SellerRatingModel
        from src.settlement.infrastructure.models import EscrowContractModel

        # Validate escrow exists and is RELEASED
        escrow = await self._session.execute(
            select(EscrowContractModel).where(EscrowContractModel.id == escrow_id)
        )
        escrow_row = escrow.scalar_one_or_none()
        if not escrow_row:
            raise ValueError("Escrow not found")
        if escrow_row.status != "RELEASED":
            raise ValueError("Can only rate after escrow is released")
        if str(escrow_row.buyer_enterprise_id) != str(buyer_enterprise_id):
            raise ValueError("Only the buyer can rate this escrow")

        # Check for existing rating
        existing = await self._session.execute(
            select(SellerRatingModel).where(SellerRatingModel.escrow_id == escrow_id)
        )
        if existing.scalar_one_or_none():
            raise ValueError("Rating already submitted for this escrow")

        # Create rating
        rating_model = SellerRatingModel(
            id=uuid.uuid4(),
            escrow_id=escrow_id,
            session_id=escrow_row.session_id,
            buyer_enterprise_id=buyer_enterprise_id,
            seller_enterprise_id=escrow_row.seller_enterprise_id,
            rating=rating,
            feedback_text=feedback_text,
            delivery_quality=delivery_quality,
            communication_quality=communication_quality,
        )
        self._session.add(rating_model)
        await self._session.commit()

        log.info("seller_rating_submitted", escrow_id=str(escrow_id), rating=rating)
        return {"id": str(rating_model.id), "rating": rating}

    async def get_seller_ratings(
        self,
        seller_enterprise_id: uuid.UUID,
        limit: int = 20,
    ) -> dict:
        """Get ratings for a seller with average scores."""
        from sqlalchemy import func as sa_func
        from sqlalchemy import select

        from src.marketplace.infrastructure.models import SellerRatingModel

        # Aggregate
        avg_result = await self._session.execute(
            select(
                sa_func.avg(SellerRatingModel.rating).label("avg_rating"),
                sa_func.count(SellerRatingModel.id).label("total_ratings"),
            ).where(SellerRatingModel.seller_enterprise_id == seller_enterprise_id)
        )
        agg = avg_result.one()

        # Recent ratings
        recent = await self._session.execute(
            select(SellerRatingModel)
            .where(SellerRatingModel.seller_enterprise_id == seller_enterprise_id)
            .order_by(SellerRatingModel.created_at.desc())
            .limit(limit)
        )
        ratings = recent.scalars().all()

        return {
            "avg_rating": round(float(agg.avg_rating or 0), 1),
            "total_ratings": agg.total_ratings or 0,
            "ratings": [
                {
                    "rating": r.rating,
                    "feedback_text": r.feedback_text,
                    "delivery_quality": r.delivery_quality,
                    "communication_quality": r.communication_quality,
                    "created_at": str(r.created_at),
                }
                for r in ratings
            ],
        }
