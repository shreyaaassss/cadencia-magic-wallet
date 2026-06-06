"""Tests for Audit §8.2: N+1 query batch optimization in matchmaker.

Verifies that find_enhanced_matches uses batch-prefetched data
instead of per-seller individual queries.
"""
from __future__ import annotations

import inspect

import pytest


class TestMatchmakerBatchPrefetch:
    """Audit §8.2: Matchmaker must batch-prefetch seller data."""

    def test_batch_prefetch_exists(self):
        """find_enhanced_matches must contain IN-clause batch prefetch."""
        from src.marketplace.infrastructure.pgvector_matchmaker import PgvectorMatchmaker
        source = inspect.getsource(PgvectorMatchmaker.find_enhanced_matches)
        assert ".in_(seller_ids)" in source or "in_(seller_ids)" in source, \
            "Batch prefetch with IN clause not found in find_enhanced_matches"

    def test_prefetched_dicts_used_in_loop(self):
        """Loop must use _prefetched_* dicts, not individual queries."""
        from src.marketplace.infrastructure.pgvector_matchmaker import PgvectorMatchmaker
        source = inspect.getsource(PgvectorMatchmaker.find_enhanced_matches)
        assert "_prefetched_caps" in source, "Capability profiles not prefetched"
        assert "_prefetched_addrs" in source, "Addresses not prefetched"
        assert "_prefetched_scaps" in source, "Seller capacity profiles not prefetched"
        assert "_prefetched_catalogues" in source, "Catalogue items not prefetched"
        assert "_prefetched_enterprises" in source, "Enterprises not prefetched"

    def test_no_per_seller_address_query_in_loop(self):
        """The loop must NOT contain individual address queries."""
        from src.marketplace.infrastructure.pgvector_matchmaker import PgvectorMatchmaker
        source = inspect.getsource(PgvectorMatchmaker.find_enhanced_matches)
        # The old pattern: select(AddressModel).where(AddressModel.enterprise_id == seller_id)
        # This should no longer appear INSIDE the loop body
        # Count occurrences — should be in prefetch only (1 occurrence), not in loop
        addr_query_count = source.count("AddressModel.enterprise_id.in_")
        individual_addr = source.count("AddressModel.enterprise_id == seller_id")
        assert individual_addr == 0, \
            f"Individual address query still in loop ({individual_addr} occurrences)"


class TestPerVariantEmbeddings:
    """§6.2 FP1: Multi-product RFQs must get per-variant embeddings."""

    def test_variant_embedding_generation_code_exists(self):
        """_parse_and_match_standalone must generate per-variant embeddings."""
        from src.marketplace.application.services import MarketplaceService
        source = inspect.getsource(MarketplaceService._parse_and_match_standalone)
        assert "variant_embeddings" in source, "Per-variant embeddings not generated"
        assert "v_embedding" in source, "Variant-specific embedding not used in matchmaker calls"
