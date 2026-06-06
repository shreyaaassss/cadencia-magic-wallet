"""Tests for §2: Embedding quality + §7.7: Geocode fallback.

Covers: embedding status model columns, rich embedding text composition,
geocode state centroid fallback code presence.
"""
from __future__ import annotations

import inspect

import pytest


class TestEmbeddingStatusTracking:
    """§3.3: embedding_status, embedding_version, last_embedded_at columns."""

    def test_capability_profile_model_has_tracking_columns(self):
        from src.marketplace.infrastructure.models import CapabilityProfileModel
        columns = {c.name for c in CapabilityProfileModel.__table__.columns}
        assert "embedding_status" in columns
        assert "embedding_version" in columns
        assert "last_embedded_at" in columns

    def test_embedding_status_default_outdated(self):
        from src.marketplace.infrastructure.models import CapabilityProfileModel
        col = CapabilityProfileModel.__table__.c.embedding_status
        assert col.server_default is not None
        # Default should be 'OUTDATED'
        default_text = str(col.server_default.arg)
        assert "OUTDATED" in default_text


class TestRichEmbeddingComposition:
    """§2: Embedding text must include all 7 data sources."""

    def test_recompute_queries_capacity_profile(self):
        """_recompute_embedding_standalone must query SellerCapacityProfileModel."""
        from src.marketplace.application.services import MarketplaceService
        source = inspect.getsource(MarketplaceService._recompute_embedding_standalone)
        assert "SellerCapacityProfileModel" in source, "Capacity profile not queried in embedding"

    def test_recompute_queries_enterprise(self):
        """_recompute_embedding_standalone must query EnterpriseModel."""
        from src.marketplace.application.services import MarketplaceService
        source = inspect.getsource(MarketplaceService._recompute_embedding_standalone)
        assert "EnterpriseModel" in source, "Enterprise data not queried in embedding"

    def test_recompute_includes_certifications(self):
        """Certifications must be included in embedding text."""
        from src.marketplace.application.services import MarketplaceService
        source = inspect.getsource(MarketplaceService._recompute_embedding_standalone)
        assert "Certifications" in source, "Certifications not in embedding text"

    def test_recompute_includes_payment_terms(self):
        """Payment terms must be included in embedding text."""
        from src.marketplace.application.services import MarketplaceService
        source = inspect.getsource(MarketplaceService._recompute_embedding_standalone)
        assert "Payment" in source, "Payment terms not in embedding text"

    def test_recompute_includes_capacity_data(self):
        """Monthly capacity data must be in embedding text."""
        from src.marketplace.application.services import MarketplaceService
        source = inspect.getsource(MarketplaceService._recompute_embedding_standalone)
        assert "Monthly capacity" in source, "Capacity data not in embedding"

    def test_recompute_includes_price_range(self):
        """Price range must be in embedding text."""
        from src.marketplace.application.services import MarketplaceService
        source = inspect.getsource(MarketplaceService._recompute_embedding_standalone)
        assert "Price range" in source, "Price range not in embedding"

    def test_recompute_includes_negotiation_history(self):
        """Negotiation insights must be in embedding text."""
        from src.marketplace.application.services import MarketplaceService
        source = inspect.getsource(MarketplaceService._recompute_embedding_standalone)
        assert "NegotiationInsightModel" in source, "Negotiation history not queried"

    def test_recompute_sets_embedding_status(self):
        """Must set COMPUTING before and ACTIVE/FAILED after."""
        from src.marketplace.application.services import MarketplaceService
        source = inspect.getsource(MarketplaceService._recompute_embedding_standalone)
        assert "COMPUTING" in source
        assert "ACTIVE" in source
        assert "FAILED" in source


class TestDistributedEmbeddingLock:
    """Audit §8.1: Redis-based distributed embedding lock."""

    def test_lock_functions_exist(self):
        from src.marketplace.application import services
        assert hasattr(services, "_acquire_embedding_lock")
        assert hasattr(services, "_release_embedding_lock")

    def test_lock_uses_redis(self):
        from src.marketplace.application.services import _acquire_embedding_lock
        source = inspect.getsource(_acquire_embedding_lock)
        assert "redis" in source.lower(), "Distributed lock does not use Redis"
        assert "nx=True" in source or "NX" in source, "Lock does not use SET NX"


class TestGeocodeFallback:
    """§7.7: Unknown pincode must fall back to state centroid."""

    def test_fallback_code_exists(self):
        """check_feasibility must contain state centroid fallback logic."""
        from src.marketplace.infrastructure.delivery_feasibility import DeliveryFeasibilityService
        source = inspect.getsource(DeliveryFeasibilityService.check_feasibility)
        assert "geocode_state_centroid_fallback" in source, "State centroid fallback not implemented"

    def test_fallback_uses_avg_coordinates(self):
        """Fallback must compute AVG(latitude), AVG(longitude) for state."""
        from src.marketplace.infrastructure.delivery_feasibility import DeliveryFeasibilityService
        source = inspect.getsource(DeliveryFeasibilityService.check_feasibility)
        assert "avg" in source.lower() or "AVG" in source, "Centroid not computed via AVG"


class TestCatalogueItemExpiry:
    """§7.5: Expired catalogue items must be deactivatable."""

    def test_expiry_method_exists(self):
        from src.marketplace.application.services import MarketplaceService
        assert hasattr(MarketplaceService, "deactivate_expired_catalogue_items")

    def test_validity_end_date_column_exists(self):
        from src.marketplace.infrastructure.models import CatalogueItemModel
        columns = {c.name for c in CatalogueItemModel.__table__.columns}
        assert "validity_end_date" in columns


class TestFullTextSearchIndex:
    """§3.2: Full-text search index on catalogue_items."""

    def test_fulltext_index_in_migration(self):
        """Migration 026 must create the GIN full-text search index."""
        from pathlib import Path
        migration_path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "026_fulltext_search_index_catalogue.py"
        source = migration_path.read_text()
        assert "to_tsvector" in source
        assert "GIN" in source or "gin" in source.lower()
