# Marketplace API schemas — Pydantic models matching the frontend TypeScript contracts.

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional, Self

from pydantic import BaseModel, Field, field_validator, model_validator


# ── Requests ──────────────────────────────────────────────────────────────────


class UploadRFQRequest(BaseModel):
    raw_text: str = Field(..., min_length=10, max_length=50000)
    document_type: str = Field(default="free_text")


class ConfirmRFQRequest(BaseModel):
    """POST /rfq/:id/confirm — frontend sends seller_enterprise_id, not match_id."""
    seller_enterprise_id: str    # UUID as string — matches what frontend sends


class CapabilityProfileUpdateRequest(BaseModel):
    """PUT /marketplace/capability-profile — matches frontend form fields."""
    industry: str = ""
    products: list[str] = Field(default_factory=list)
    geographies: list[str] = Field(default_factory=list)
    min_order_value: float = 0.0
    max_order_value: float = 0.0
    description: str = ""

    @field_validator("min_order_value", "max_order_value")
    @classmethod
    def validate_positive(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Order values must be non-negative")
        return v


# Legacy request — kept for backward compat if needed
class UpdateCapabilityProfileRequest(BaseModel):
    industry_vertical: str | None = None
    product_categories: list[str] = Field(default_factory=list)
    geography_scope: list[str] = Field(default_factory=list)
    trade_volume_min: Decimal | None = None
    trade_volume_max: Decimal | None = None
    profile_text: str | None = None


# ── Responses ─────────────────────────────────────────────────────────────────


class RFQResponse(BaseModel):
    """Matches frontend RFQ TypeScript interface exactly."""
    id: uuid.UUID
    raw_text: str = ""                                    # ADDED
    status: str                                           # DRAFT | PARSED | MATCHED | CONFIRMED
    parsed_fields: Optional[dict] = None                  # Record<string, string> | null
    created_at: str = ""                                  # ADDED — ISO 8601

    @field_validator("created_at", mode="before")
    @classmethod
    def serialize_datetime(cls, v: object) -> str:
        if isinstance(v, datetime):
            return v.isoformat().replace("+00:00", "Z")
        return str(v) if v else ""


class RFQSubmitResponse(BaseModel):
    """POST /marketplace/rfq — 202 response."""
    rfq_id: str                                           # UUID as string
    status: str = "DRAFT"
    message: str = "RFQ submitted for processing."


class MatchResponse(BaseModel):
    """Matches frontend SellerMatch TypeScript interface exactly."""
    enterprise_id: str                                    # RENAMED from seller_enterprise_id
    enterprise_name: str = ""                             # ADDED — from Enterprise join
    score: float                                          # RENAMED from similarity_score (0-100)
    rank: int
    capabilities: list[str] = Field(default_factory=list) # ADDED — from capability profile


class ConfirmRFQResponse(BaseModel):
    """POST /rfq/:id/confirm — response."""
    message: str = "Negotiation session created"
    session_id: str                                       # UUID of NegotiationSession


class CapabilityProfileResponse(BaseModel):
    """Matches frontend CapabilityProfile TypeScript interface exactly."""
    industry: str = ""
    geographies: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
    min_order_value: float = 0.0
    max_order_value: float = 0.0
    description: str = ""
    embedding_status: str = "outdated"                    # active | queued | failed | outdated
    last_embedded: Optional[str] = None                   # ISO 8601 or null


class CapabilityProfileUpdateResponse(BaseModel):
    """PUT /marketplace/capability-profile — response."""
    message: str = "Seller profile updated successfully"
    embedding_status: str = "queued"


class EmbeddingRecomputeResponse(BaseModel):
    """POST /marketplace/capability-profile/embeddings — response."""
    message: str = "Embeddings recomputation queued. Profile will be active for matching in ~30 seconds."


class IncomingRFQResponse(BaseModel):
    """GET /marketplace/incoming-rfqs — seller view of matched RFQs."""
    match_id: uuid.UUID
    rfq_id: uuid.UUID
    raw_text: str = ""
    status: str
    parsed_fields: Optional[dict] = None
    created_at: str = ""
    similarity_score: float = 0.0
    rank: int = 0
    match_status: str = "PENDING"
    buyer_enterprise_id: uuid.UUID

    @field_validator("created_at", mode="before")
    @classmethod
    def serialize_datetime(cls, v: object) -> str:
        if isinstance(v, datetime):
            return v.isoformat().replace("+00:00", "Z")
        return str(v) if v else ""


# ── Enhanced Onboarding Schemas ──────────────────────────────────────────────


class CatalogueItemCreateRequest(BaseModel):
    """POST /marketplace/catalogue — create a seller catalogue entry."""
    product_name: str = Field(min_length=3, max_length=200)
    hsn_code: str = Field(pattern=r"^\d{4,8}$")
    product_category: Literal[
        "HR_COIL", "CR_COIL", "TMT_BAR", "WIRE_ROD", "BILLET", "SLAB",
        "PLATE", "PIPE", "SHEET", "ANGLE", "CHANNEL", "BEAM", "CUSTOM"
    ]
    grade: Optional[str] = Field(None, max_length=100)
    specification_text: Optional[str] = Field(None, max_length=2000)
    unit: Literal["MT", "KG", "PIECE", "BUNDLE", "COIL"] = "MT"
    price_per_unit_inr: float = Field(gt=0)
    bulk_pricing_tiers: Optional[list[dict]] = None
    moq: float = Field(gt=0)
    max_order_qty: float = Field(gt=0)
    lead_time_days: int = Field(ge=1, le=180)
    in_stock_qty: float = 0
    certifications: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_qty(self) -> Self:
        if self.max_order_qty < self.moq:
            raise ValueError("max_order_qty must be >= moq")
        return self


class CatalogueItemUpdateRequest(BaseModel):
    """PUT /marketplace/catalogue/:id — partial update."""
    product_name: Optional[str] = Field(None, min_length=3, max_length=200)
    hsn_code: Optional[str] = Field(None, pattern=r"^\d{4,8}$")
    product_category: Optional[Literal[
        "HR_COIL", "CR_COIL", "TMT_BAR", "WIRE_ROD", "BILLET", "SLAB",
        "PLATE", "PIPE", "SHEET", "ANGLE", "CHANNEL", "BEAM", "CUSTOM"
    ]] = None
    grade: Optional[str] = Field(None, max_length=100)
    specification_text: Optional[str] = Field(None, max_length=2000)
    unit: Optional[Literal["MT", "KG", "PIECE", "BUNDLE", "COIL"]] = None
    price_per_unit_inr: Optional[float] = Field(None, gt=0)
    bulk_pricing_tiers: Optional[list[dict]] = None
    moq: Optional[float] = Field(None, gt=0)
    max_order_qty: Optional[float] = Field(None, gt=0)
    lead_time_days: Optional[int] = Field(None, ge=1, le=180)
    in_stock_qty: Optional[float] = None
    certifications: Optional[list[str]] = None


class CatalogueItemResponse(BaseModel):
    """Catalogue item response."""
    id: uuid.UUID
    product_name: str
    hsn_code: str
    product_category: str
    grade: Optional[str] = None
    specification_text: Optional[str] = None
    unit: str = "MT"
    price_per_unit_inr: float
    bulk_pricing_tiers: Optional[list[dict]] = None
    moq: float
    max_order_qty: float
    lead_time_days: int
    in_stock_qty: float = 0
    is_active: bool = True
    certifications: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def serialize_dt(cls, v: object) -> str:
        if isinstance(v, datetime):
            return v.isoformat().replace("+00:00", "Z")
        return str(v) if v else ""


class SellerCapacityProfileRequest(BaseModel):
    """PUT /marketplace/capacity-profile — create/update capacity data."""
    monthly_production_capacity_mt: float = Field(gt=0)
    current_utilization_pct: int = Field(default=0, ge=0, le=100)
    num_production_lines: int = Field(default=1, ge=1)
    shift_pattern: Literal[
        "SINGLE_SHIFT", "DOUBLE_SHIFT", "TRIPLE_SHIFT", "CONTINUOUS"
    ] = "SINGLE_SHIFT"
    avg_dispatch_days: int = Field(default=3, ge=1, le=90)
    max_delivery_radius_km: Optional[int] = Field(None, ge=50, le=5000)
    has_own_transport: bool = False
    preferred_transport_modes: list[Literal["ROAD", "RAIL", "SEA", "AIR"]] = Field(default_factory=list)
    ex_works_available: bool = True


class SellerCapacityProfileResponse(BaseModel):
    """Capacity profile response."""
    id: uuid.UUID
    enterprise_id: uuid.UUID
    monthly_production_capacity_mt: float
    current_utilization_pct: int = 0
    available_capacity_mt: Optional[float] = None
    num_production_lines: int = 1
    shift_pattern: str = "SINGLE_SHIFT"
    avg_dispatch_days: int = 3
    max_delivery_radius_km: Optional[int] = None
    has_own_transport: bool = False
    preferred_transport_modes: list[str] = Field(default_factory=list)
    ex_works_available: bool = True
    created_at: str = ""
    updated_at: str = ""

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def serialize_dt(cls, v: object) -> str:
        if isinstance(v, datetime):
            return v.isoformat().replace("+00:00", "Z")
        return str(v) if v else ""


class AddressResponse(BaseModel):
    """Address response."""
    id: uuid.UUID
    address_type: str
    address_line1: str
    address_line2: Optional[str] = None
    city: str
    state: str
    pincode: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_primary: bool = True


class PincodeGeocodeResponse(BaseModel):
    """Pincode lookup response."""
    pincode: str
    city: str
    state: str
    latitude: float
    longitude: float


class EnhancedMatchResponse(BaseModel):
    """Match response with delivery feasibility and scoring breakdown."""
    enterprise_id: str
    enterprise_name: str = ""
    score: float
    rank: int
    capabilities: list[str] = Field(default_factory=list)
    semantic_score: Optional[float] = None
    delivery_feasibility_score: Optional[float] = None
    capacity_score: Optional[float] = None
    price_score: Optional[float] = None
    proximity_score: Optional[float] = None
    composite_score: Optional[float] = None
    estimated_delivery_days: Optional[int] = None
    distance_km: Optional[int] = None
