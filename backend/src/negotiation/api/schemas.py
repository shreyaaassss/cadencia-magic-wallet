# context.md §3: FastAPI/Pydantic imports ONLY in api/ layer.
# Updated for DANP negotiation engine with intelligence endpoint.

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_serializer


class CreateSessionRequest(BaseModel):
    match_id: uuid.UUID
    rfq_id: uuid.UUID
    buyer_enterprise_id: uuid.UUID
    seller_enterprise_id: uuid.UUID


class HumanOverrideRequest(BaseModel):
    price: Decimal = Field(gt=0, description="Override price in INR")
    currency: str = Field(default="INR")
    terms: dict = Field(default_factory=dict)


class TerminateRequest(BaseModel):
    reason: str = Field(default="Admin terminated")


class OfferResponse(BaseModel):
    offer_id: uuid.UUID
    session_id: uuid.UUID
    round_number: int
    proposer_role: str
    price: Decimal
    currency: str = "INR"
    terms: dict
    confidence: float | None
    is_human_override: bool
    agent_reasoning: str | None = None
    created_at: datetime

    @field_serializer('price')
    def serialize_price(self, value: Decimal) -> float:
        return float(value)


class SessionResponse(BaseModel):
    session_id: uuid.UUID
    rfq_id: uuid.UUID
    match_id: uuid.UUID
    buyer_enterprise_id: uuid.UUID
    seller_enterprise_id: uuid.UUID
    status: str
    agreed_price: Decimal | None
    agreed_currency: str | None
    agreed_terms: dict | None
    round_count: int
    offers: list[OfferResponse]
    created_at: datetime
    completed_at: datetime | None
    expires_at: datetime
    schema_failure_count: int = 0
    stall_counter: int = 0
    deal_quality_score: dict | float | None = None  # ZOPA position (dict) or score (float)
    product_context: dict | None = None      # Per-product context (multi-product RFQs)

    @field_serializer('agreed_price')
    def serialize_agreed_price(self, value: Decimal | None) -> float | None:
        return float(value) if value is not None else None


class IntelligenceResponse(BaseModel):
    """Debug endpoint response — Bayesian beliefs + metrics."""

    session_id: str
    round_count: int
    status: str
    buyer_intelligence: dict
    seller_intelligence: dict
    convergence: bool
    stall_counter: int
    schema_failures: int
