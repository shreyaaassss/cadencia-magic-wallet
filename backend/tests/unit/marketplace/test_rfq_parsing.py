"""Tests for §6: RFQ Parsing & Matching Quality.

Covers: variant budget inheritance fix, data-driven commodity dict,
case-insensitive category matching.
"""
from __future__ import annotations

import pytest


class TestVariantBudgetInheritance:
    """§6.2 FP2: Variants must NOT inherit full total RFQ budget."""

    def test_per_item_budget_used_when_available(self):
        from src.marketplace.infrastructure.rfq_parser import build_parsed_variants
        parsed = {
            "product": None,
            "budget_max": 165000,
            "items": [
                {"product": "Sony Camera", "quantity": 5, "budget_total": 150000},
                {"product": "Tripod", "quantity": 3, "budget_total": 15000},
            ],
        }
        variants = build_parsed_variants(parsed)
        # First variant is the parent; items start at index 1
        item_variants = [v for v in variants if v.get("product")]
        camera = next((v for v in item_variants if "Camera" in v.get("product", "")), None)
        tripod = next((v for v in item_variants if "Tripod" in v.get("product", "")), None)
        assert camera is not None, "Camera variant not found"
        assert tripod is not None, "Tripod variant not found"
        assert camera["budget_max"] == 150000
        assert tripod["budget_max"] == 15000

    def test_even_split_when_no_item_budget(self):
        """Items without budgets get even share of remaining total."""
        from src.marketplace.infrastructure.rfq_parser import build_parsed_variants
        parsed = {
            "product": None,
            "budget_max": 100000,
            "items": [
                {"product": "Item A", "quantity": 2},
                {"product": "Item B", "quantity": 2},
            ],
        }
        variants = build_parsed_variants(parsed)
        item_variants = [v for v in variants if v.get("items") is None and v.get("product")]
        for v in item_variants:
            assert v.get("budget_max", 0) <= 50001, \
                f"Variant inherited full budget instead of split: {v.get('budget_max')}"

    def test_mixed_budget_items(self):
        """Mix of items with/without budgets — remainder split evenly."""
        from src.marketplace.infrastructure.rfq_parser import build_parsed_variants
        parsed = {
            "product": None,
            "budget_max": 200000,
            "items": [
                {"product": "Camera", "quantity": 1, "budget_total": 100000},
                {"product": "Tripod", "quantity": 1},  # no budget
                {"product": "Bag", "quantity": 1},       # no budget
            ],
        }
        variants = build_parsed_variants(parsed)
        tripod = next((v for v in variants if v.get("product") == "Tripod"), None)
        bag = next((v for v in variants if v.get("product") == "Bag"), None)
        # Remaining budget = 200000 - 100000 = 100000, split across 2 items = 50000 each
        assert tripod is not None
        assert tripod.get("budget_max", 0) == 50000.0
        assert bag is not None
        assert bag.get("budget_max", 0) == 50000.0


class TestDataDrivenCommodities:
    """§1/§6: _COMMODITIES dict must be extendable from DB."""

    def test_extend_commodities_from_db(self):
        from src.marketplace.infrastructure.rfq_parser import StubDocumentParser
        # Extend with DB products
        StubDocumentParser.extend_commodities_from_db([
            {"product_category": "furniture", "product_name": "office chair"},
            {"product_category": "furniture", "product_name": "standing desk"},
        ])
        assert "furniture" in StubDocumentParser._COMMODITIES
        assert "office chair" in StubDocumentParser._COMMODITIES["furniture"]
        assert "standing desk" in StubDocumentParser._COMMODITIES["furniture"]

    def test_extend_does_not_duplicate(self):
        from src.marketplace.infrastructure.rfq_parser import StubDocumentParser
        StubDocumentParser.extend_commodities_from_db([
            {"product_category": "steel", "product_name": "steel"},  # already exists
        ])
        # "steel" should appear exactly once
        assert StubDocumentParser._COMMODITIES["steel"].count("steel") == 1
