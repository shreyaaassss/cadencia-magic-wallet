"""Tests for §3 + §4: Catalogue architecture, commercial constraints, versioning.

Covers: specification_text, floor_price validation, bulk pricing tier wiring,
catalogue versioning columns, change log model.
"""
from __future__ import annotations

import pytest
from decimal import Decimal


class TestSpecificationTextField:
    """§3/§9.4: specification_text must be accepted in schema."""

    def test_spec_text_accepted(self):
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
            specification_text="IS:1786 Fe500D, Rib type: Lug, Length: 12m",
        )
        assert req.specification_text == "IS:1786 Fe500D, Rib type: Lug, Length: 12m"

    def test_spec_text_optional(self):
        from src.marketplace.api.schemas import CatalogueItemCreateRequest
        req = CatalogueItemCreateRequest(
            product_name="Test",
            hsn_code="72142000",
            product_category="PLATE",
            unit="MT",
            price_per_unit_inr=60000,
            moq=5,
            max_order_qty=500,
            lead_time_days=3,
        )
        assert req.specification_text is None


class TestCatalogueCommercialFields:
    """§4.5: New commercial fields on catalogue_items."""

    def test_floor_price_stored_in_schema(self):
        from src.marketplace.api.schemas import CatalogueItemCreateRequest
        req = CatalogueItemCreateRequest(
            product_name="Steel with floor price",
            hsn_code="72142000",
            product_category="TMT_BAR",
            unit="MT",
            price_per_unit_inr=55000,
            floor_price_inr=48000,
            max_discount_pct=12.5,
            negotiation_enabled=True,
            moq=10,
            max_order_qty=1000,
            lead_time_days=7,
        )
        assert req.floor_price_inr == 48000
        assert req.max_discount_pct == 12.5
        assert req.negotiation_enabled is True

    def test_floor_price_must_be_below_list_price(self):
        """floor_price > list price must be rejected."""
        from src.marketplace.api.schemas import CatalogueItemCreateRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="floor_price_inr must be <= price_per_unit_inr"):
            CatalogueItemCreateRequest(
                product_name="Invalid floor",
                hsn_code="72142000",
                product_category="TMT_BAR",
                unit="MT",
                price_per_unit_inr=50000,
                floor_price_inr=60000,  # INVALID
                moq=10,
                max_order_qty=1000,
                lead_time_days=7,
            )

    def test_negotiation_enabled_default_true(self):
        from src.marketplace.api.schemas import CatalogueItemCreateRequest
        req = CatalogueItemCreateRequest(
            product_name="Default negotation",
            hsn_code="72142000",
            product_category="HR_COIL",
            unit="MT",
            price_per_unit_inr=65000,
            moq=5,
            max_order_qty=500,
            lead_time_days=5,
        )
        assert req.negotiation_enabled is True

    def test_commercial_fields_in_model(self):
        """CatalogueItemModel must have all commercial columns."""
        from src.marketplace.infrastructure.models import CatalogueItemModel
        columns = {c.name for c in CatalogueItemModel.__table__.columns}
        expected = {"floor_price_inr", "max_discount_pct", "negotiation_enabled",
                    "approval_threshold_inr", "validity_end_date", "payment_terms",
                    "region_restrictions"}
        assert expected.issubset(columns), f"Missing: {expected - columns}"


class TestBulkPricingTierWiring:
    """§4.4: bulk_pricing_tiers must be usable via domain entity."""

    def test_bulk_tier_applied_for_large_qty(self):
        from src.marketplace.domain.catalogue_item import CatalogueItem, BulkPricingTier
        item = CatalogueItem(
            product_name="Steel",
            product_category="TMT_BAR",
            unit="MT",
            price_per_unit_inr=Decimal("55000"),
            bulk_pricing_tiers=[
                BulkPricingTier(min_qty=Decimal("1"), max_qty=Decimal("99"), price_per_unit_inr=Decimal("55000")),
                BulkPricingTier(min_qty=Decimal("100"), max_qty=None, price_per_unit_inr=Decimal("50000")),
            ],
            moq=Decimal("10"),
            max_order_qty=Decimal("10000"),
            lead_time_days=7,
        )
        assert item.get_price_for_quantity(Decimal("100")) == Decimal("50000")
        assert item.get_price_for_quantity(Decimal("50")) == Decimal("55000")

    def test_no_tiers_returns_base_price(self):
        from src.marketplace.domain.catalogue_item import CatalogueItem
        item = CatalogueItem(
            product_name="Camera",
            product_category="DSLR",
            unit="PIECE",
            price_per_unit_inr=Decimal("280000"),
            moq=Decimal("1"),
            max_order_qty=Decimal("50"),
            lead_time_days=3,
        )
        assert item.get_price_for_quantity(Decimal("10")) == Decimal("280000")


class TestGuardrailCostBasis:
    """§7.3: GuardrailEngine cost_basis must enforce margin floor."""

    def test_margin_floor_enforced_when_cost_basis_provided(self, guardrail_engine):
        from src.negotiation.domain.guardrails import ActionEnvelope
        envelope = ActionEnvelope(
            offer_value=Decimal("45000"),
            action="counter",
            agent_role="seller",  # margin check only runs for seller
        )
        violations = guardrail_engine.validate_envelope(
            envelope=envelope,
            reservation_price=Decimal("48000"),
            budget_ceiling=None,
            margin_floor=Decimal("10"),
            cost_basis=Decimal("50000"),  # min acceptable = 55000
        )
        assert any("margin" in v.message.lower() or "Margin" in v.message for v in violations), \
            f"Margin floor violation not detected: {[v.message for v in violations]}"

    def test_no_violation_when_above_margin_floor(self, guardrail_engine):
        from src.negotiation.domain.guardrails import ActionEnvelope
        envelope = ActionEnvelope(
            offer_value=Decimal("58000"),  # above 50000 + 10%
            action="counter",
            agent_role="seller",
        )
        violations = guardrail_engine.validate_envelope(
            envelope=envelope,
            reservation_price=Decimal("55000"),
            budget_ceiling=None,
            margin_floor=Decimal("10"),
            cost_basis=Decimal("50000"),
        )
        margin_violations = [v for v in violations if "margin" in v.message.lower() or "Margin" in v.message]
        assert len(margin_violations) == 0, f"False positive: {[v.message for v in margin_violations]}"


class TestCatalogueVersioning:
    """§3.4: Versioning columns and change log model."""

    def test_version_columns_in_model(self):
        from src.marketplace.infrastructure.models import CatalogueItemModel
        columns = {c.name for c in CatalogueItemModel.__table__.columns}
        assert "version" in columns
        assert "status" in columns
        assert "previous_version_id" in columns
        assert "price_updated_at" in columns

    def test_change_log_model_exists(self):
        from src.marketplace.infrastructure.models import CatalogueChangeLogModel
        assert CatalogueChangeLogModel.__tablename__ == "catalogue_change_log"
        columns = {c.name for c in CatalogueChangeLogModel.__table__.columns}
        expected = {"id", "catalogue_item_id", "field_name", "old_value", "new_value", "changed_by", "changed_at"}
        assert expected.issubset(columns)
