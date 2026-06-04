"""
SQLAlchemy ORM models for the marketplace bounded context.

Tables: rfqs, capability_profiles, matches, addresses, catalogue_items,
        seller_capacity_profiles, pincode_geocodes
context.md §11 — Database Schema.

Vector indexes:
    rfqs.embedding:                 HNSW (m=16, ef_construction=64)
    capability_profiles.embedding:  IVFFlat (lists=100, cosine distance)
"""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.infrastructure.db.base import Base


class RFQModel(Base):
    """
    RFQ (Request for Quotation) aggregate root (marketplace bounded context).

    status: DRAFT | PARSED | MATCHED | CONFIRMED | SETTLED
    embedding: 1536-dimensional float32 vector for semantic matching.
    HNSW index: context.md §11 (m=16, ef_construction=64).
    """

    __tablename__ = "rfqs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','PARSE_FAILED','PARSED','MATCHED','NEGOTIATING','CONFIRMED','SETTLED','EXPIRED')",
            name="ck_rfqs_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("enterprises.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="DRAFT"
    )
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # LLM-extracted structured fields (context.md §8)
    product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hsn_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    budget_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    delivery_window_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    geography: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parsed_fields: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    all_products: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # All products in multi-product RFQ
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # pgvector 1536-dim embedding (context.md §11)
    embedding: Mapped[list | None] = mapped_column(Vector(1536), nullable=True)
    confirmed_match_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # Enhanced onboarding: delivery precision fields
    delivery_pincode: Mapped[str | None] = mapped_column(String(6), nullable=True)
    delivery_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    delivery_state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    max_acceptable_lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requires_test_certificate: Mapped[bool | None] = mapped_column(
        Boolean, server_default="false", nullable=True
    )
    preferred_payment_terms: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    matches: Mapped[list[MatchModel]] = relationship("MatchModel", back_populates="rfq")


_rfqs_enterprise_status_idx = Index(
    "ix_rfqs_enterprise_id_status", RFQModel.enterprise_id, RFQModel.status
)
# HNSW vector index created via raw SQL in Alembic migration (context.md §11)


class CapabilityProfileModel(Base):
    """
    Seller capability profile (marketplace bounded context).

    embedding: 1536-dim float32 vector for IVFFlat cosine matching.
    context.md §11: IVFFlat index (lists=100, cosine distance).
    Target: Top-5 query < 2s at 10,000 rows.
    """

    __tablename__ = "capability_profiles"
    __table_args__ = (
        UniqueConstraint("enterprise_id", name="uq_capability_profiles_enterprise_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("enterprises.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    commodities: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    hsn_codes: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    min_order_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_order_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    industry_vertical: Mapped[str | None] = mapped_column(String(200), nullable=True)
    geographies_served: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    certifications: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    profile_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # pgvector 1536-dim embedding (context.md §11)
    embedding: Mapped[list | None] = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


# IVFFlat vector index created via raw SQL in Alembic migration (context.md §11)


class MatchModel(Base):
    """
    Match entity linking an RFQ to a ranked seller (marketplace bounded context).

    score: cosine similarity score from pgvector search.
    rank:  position in ranked results (1 = best match).
    """

    __tablename__ = "matches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    rfq_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rfqs.id", ondelete="CASCADE"),
        nullable=False,
    )
    seller_enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("enterprises.id", ondelete="CASCADE"),
        nullable=False,
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    # Enhanced onboarding: scoring breakdown
    semantic_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    delivery_feasibility_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    capacity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    proximity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    composite_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_delivery_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distance_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Fix 1: pointer to the specific catalogue item used during matchmaking.
    # Nullable for backward compat with existing match rows (SET NULL on item delete).
    matched_catalogue_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("catalogue_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    matched_rfq_variant: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # Which product variant this match is for
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    rfq: Mapped[RFQModel] = relationship("RFQModel", back_populates="matches")


_matches_rfq_idx = Index("ix_matches_rfq_id", MatchModel.rfq_id)
_matches_seller_idx = Index("ix_matches_seller_enterprise_id", MatchModel.seller_enterprise_id)


# ── Enhanced Onboarding Models ───────────────────────────────────────────────


class AddressModel(Base):
    """Reusable address entity for enterprise facilities and delivery sites."""

    __tablename__ = "addresses"
    __table_args__ = (
        CheckConstraint(
            "address_type IN ('FACILITY','DELIVERY','REGISTERED_OFFICE','WAREHOUSE')",
            name="ck_addresses_address_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("enterprises.id", ondelete="CASCADE"),
        nullable=False,
    )
    address_type: Mapped[str] = mapped_column(String(30), nullable=False)
    address_line1: Mapped[str] = mapped_column(String(500), nullable=False)
    address_line2: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(50), nullable=False)
    pincode: Mapped[str] = mapped_column(String(6), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


_addresses_enterprise_idx = Index("ix_addresses_enterprise_id", AddressModel.enterprise_id)
_addresses_pincode_idx = Index("ix_addresses_pincode", AddressModel.pincode)


class CatalogueItemModel(Base):
    """Seller product catalogue with pricing tiers, MOQ, and lead times.

    Fix 3: product_category is now a free-form indexed string (max 100 chars).
    The previous steel-specific enum CHECK constraint has been dropped so that
    any industry (cameras, electronics, chemicals, textiles, etc.) can use
    meaningful category labels instead of being forced into 'CUSTOM'.
    """

    __tablename__ = "catalogue_items"
    __table_args__ = (
        CheckConstraint("moq > 0", name="ck_catalogue_moq_positive"),
        CheckConstraint("max_order_qty >= moq", name="ck_catalogue_max_gte_moq"),
        CheckConstraint("price_per_unit_inr > 0", name="ck_catalogue_price_positive"),
        CheckConstraint("lead_time_days BETWEEN 1 AND 180", name="ck_catalogue_lead_time"),
        # NOTE: ck_catalogue_product_category (steel enum) removed in migration 017.
        # product_category is now free-form — any industry can use descriptive labels.
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("enterprises.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    hsn_code: Mapped[str] = mapped_column(String(8), nullable=False)
    product_category: Mapped[str] = mapped_column(String(50), nullable=False)
    grade: Mapped[str | None] = mapped_column(String(100), nullable=True)
    specification_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str] = mapped_column(String(20), server_default="MT", nullable=False)
    price_per_unit_inr: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    bulk_pricing_tiers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    moq: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    max_order_qty: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    in_stock_qty: Mapped[float | None] = mapped_column(Numeric(12, 4), server_default="0", nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    certifications: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


_catalogue_enterprise_idx = Index("ix_catalogue_items_enterprise_id", CatalogueItemModel.enterprise_id)
_catalogue_category_idx = Index("ix_catalogue_items_category", CatalogueItemModel.product_category)


class SellerCapacityProfileModel(Base):
    """Seller production capacity and logistics data."""

    __tablename__ = "seller_capacity_profiles"
    __table_args__ = (
        UniqueConstraint("enterprise_id", name="uq_seller_capacity_enterprise_id"),
        CheckConstraint("monthly_production_capacity_mt > 0", name="ck_capacity_positive"),
        CheckConstraint("current_utilization_pct BETWEEN 0 AND 100", name="ck_utilization_range"),
        CheckConstraint(
            "shift_pattern IN ('SINGLE_SHIFT','DOUBLE_SHIFT','TRIPLE_SHIFT','CONTINUOUS')",
            name="ck_shift_pattern",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("enterprises.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    monthly_production_capacity_mt: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    current_utilization_pct: Mapped[int | None] = mapped_column(Integer, server_default="0", nullable=True)
    available_capacity_mt: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    num_production_lines: Mapped[int | None] = mapped_column(Integer, server_default="1", nullable=True)
    shift_pattern: Mapped[str] = mapped_column(String(30), server_default="SINGLE_SHIFT", nullable=False)
    avg_dispatch_days: Mapped[int] = mapped_column(Integer, server_default="3", nullable=False)
    max_delivery_radius_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_own_transport: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    preferred_transport_modes: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    ex_works_available: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PincodeGeocodeModel(Base):
    """Indian pincode geocoding lookup table (~19,000 rows)."""

    __tablename__ = "pincode_geocodes"

    pincode: Mapped[str] = mapped_column(String(6), primary_key=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(50), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    region: Mapped[str | None] = mapped_column(String(20), nullable=True)


_pincode_state_idx = Index("ix_pincode_geocodes_state", PincodeGeocodeModel.state)
