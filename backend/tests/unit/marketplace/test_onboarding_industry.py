"""Tests for §1: Industry-Specific Onboarding fixes.

Covers: free-form product_category, free-form unit, industry taxonomies,
capacity_unit column, nullable shift_pattern.
"""
from __future__ import annotations

import pytest
from decimal import Decimal


class TestProductCategoryFreeForm:
    """§1: product_category enum -> free-form str."""

    def test_steel_category_still_valid(self):
        """Existing steel values must still be accepted in the schema."""
        from src.marketplace.api.schemas import CatalogueItemCreateRequest
        req = CatalogueItemCreateRequest(
            product_name="TMT Bar Fe500D",
            hsn_code="72142000",
            product_category="TMT_BAR",
            unit="MT",
            price_per_unit_inr=55000,
            moq=10,
            max_order_qty=1000,
            lead_time_days=7,
        )
        assert req.product_category == "TMT_BAR"

    def test_non_steel_category_accepted(self):
        """Free-form non-steel categories must be accepted."""
        from src.marketplace.api.schemas import CatalogueItemCreateRequest
        req = CatalogueItemCreateRequest(
            product_name="Sony Alpha A7 IV",
            hsn_code="85258020",
            product_category="Mirrorless Camera",
            unit="PIECE",
            price_per_unit_inr=280000,
            moq=1,
            max_order_qty=100,
            lead_time_days=3,
        )
        assert req.product_category == "Mirrorless Camera"

    def test_agri_categories(self):
        """Agriculture categories must work."""
        from src.marketplace.api.schemas import CatalogueItemCreateRequest
        for category in ["Basmati Rice Grade A", "Wheat (Sharbati)", "Mustard Oil (Crude)"]:
            req = CatalogueItemCreateRequest(
                product_name=category,
                hsn_code="10063020",
                product_category=category,
                unit="KG",
                price_per_unit_inr=80,
                moq=1000,
                max_order_qty=100000,
                lead_time_days=2,
            )
            assert req.product_category == category

    def test_custom_unit_accepted(self):
        """Non-standard units (LITRE, BOX, ROLL, etc.) must be accepted."""
        from src.marketplace.api.schemas import CatalogueItemCreateRequest
        for unit in ["LITRE", "BOX", "ROLL", "SQFT", "RMETRE"]:
            req = CatalogueItemCreateRequest(
                product_name="Test Product",
                hsn_code="38140000",
                product_category="Chemical",
                unit=unit,
                price_per_unit_inr=500,
                moq=10,
                max_order_qty=10000,
                lead_time_days=3,
            )
            assert req.unit == unit

    def test_category_max_length_100(self):
        """product_category max length is 100 chars."""
        from src.marketplace.api.schemas import CatalogueItemCreateRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CatalogueItemCreateRequest(
                product_name="Test",
                hsn_code="12345678",
                product_category="X" * 101,  # 101 chars — should fail
                unit="MT",
                price_per_unit_inr=100,
                moq=1,
                max_order_qty=100,
                lead_time_days=1,
            )


class TestCapacityProfileUnitAgnostic:
    """§1: capacity_unit column — not hardcoded to MT."""

    def test_capacity_unit_field_exists_in_schema(self):
        """SellerCapacityProfileRequest must have capacity_unit field."""
        from src.marketplace.api.schemas import SellerCapacityProfileRequest
        req = SellerCapacityProfileRequest(
            monthly_production_capacity_mt=500,
            capacity_unit="MT",
            shift_pattern="DOUBLE_SHIFT",
        )
        assert req.capacity_unit == "MT"

    def test_capacity_unit_pieces(self):
        """Electronics seller can set capacity in PIECES."""
        from src.marketplace.api.schemas import SellerCapacityProfileRequest
        req = SellerCapacityProfileRequest(
            monthly_production_capacity_mt=2000,
            capacity_unit="PIECES",
            shift_pattern=None,
        )
        assert req.capacity_unit == "PIECES"
        assert req.shift_pattern is None

    def test_shift_pattern_optional(self):
        """shift_pattern can be None (trading offices)."""
        from src.marketplace.api.schemas import SellerCapacityProfileRequest
        req = SellerCapacityProfileRequest(
            monthly_production_capacity_mt=100,
            capacity_unit="UNITS",
            shift_pattern=None,
        )
        assert req.shift_pattern is None

    def test_capacity_unit_in_model(self):
        """SellerCapacityProfileModel must have capacity_unit column."""
        from src.marketplace.infrastructure.models import SellerCapacityProfileModel
        assert hasattr(SellerCapacityProfileModel, "capacity_unit")

    def test_shift_pattern_nullable_in_model(self):
        """SellerCapacityProfileModel.shift_pattern must be nullable."""
        from src.marketplace.infrastructure.models import SellerCapacityProfileModel
        col = SellerCapacityProfileModel.__table__.c.shift_pattern
        assert col.nullable is True


class TestIndustryTaxonomyModel:
    """§1.4: industry_taxonomies table exists and is queryable."""

    def test_model_exists(self):
        """IndustryTaxonomyModel must be importable."""
        from src.marketplace.infrastructure.models import IndustryTaxonomyModel
        assert IndustryTaxonomyModel.__tablename__ == "industry_taxonomies"

    def test_model_has_required_columns(self):
        """Must have all planned columns."""
        from src.marketplace.infrastructure.models import IndustryTaxonomyModel
        columns = {c.name for c in IndustryTaxonomyModel.__table__.columns}
        expected = {"id", "industry_code", "display_name", "parent_code",
                    "default_units", "default_certifications", "capacity_unit",
                    "is_manufacturing", "created_at"}
        assert expected.issubset(columns), f"Missing columns: {expected - columns}"
