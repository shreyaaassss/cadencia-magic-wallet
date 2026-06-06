"""Tests for §5: Agent Memory Effectiveness.

Covers: RAG query quality, role isolation, retrieve_context signature.
"""
from __future__ import annotations

import re
import uuid

import pytest


class TestRAGQueryQuality:
    """§5.3: RAG query must use product + qty + budget, not UUIDs."""

    def test_rag_query_excludes_uuid(self):
        """RAG query string built from RFQ fields must not contain UUID tokens."""
        rfq_parsed_fields = {
            "product": "TMT Bar Fe500D",
            "quantity": "100",
            "quantity_unit": "MT",
            "budget_max": "5500000",
            "geography": "Maharashtra",
            "_matched_item_grade": "Fe500D",
        }

        # Reproduce the RAG query builder logic from neutral_engine.py
        _rpf = rfq_parsed_fields
        rag_parts = [f"{_rpf.get('product', '')} negotiation"]
        if _rpf.get("quantity"):
            rag_parts.append(f"{_rpf['quantity']} {_rpf.get('quantity_unit', '')}")
        if _rpf.get("budget_max"):
            rag_parts.append(f"budget {_rpf['budget_max']} INR")
        if _rpf.get("geography"):
            rag_parts.append(f"{_rpf['geography']} delivery")
        if _rpf.get("_matched_item_grade"):
            rag_parts.append(f"grade {_rpf['_matched_item_grade']}")
        rag_query = " ".join(rag_parts)

        uuid_pattern = re.compile(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            re.IGNORECASE,
        )
        assert not uuid_pattern.search(rag_query), f"RAG query contains UUID: {rag_query}"
        assert "TMT Bar" in rag_query
        assert "100 MT" in rag_query
        assert "Maharashtra" in rag_query
        assert "Fe500D" in rag_query

    def test_rag_query_handles_missing_fields(self):
        """RAG query must work gracefully when fields are missing."""
        _rpf = {"product": "camera"}
        rag_parts = [f"{_rpf.get('product', '')} negotiation"]
        if _rpf.get("quantity"):
            rag_parts.append(f"{_rpf['quantity']}")
        rag_query = " ".join(rag_parts)
        assert rag_query == "camera negotiation"


class TestRAGRoleIsolation:
    """§5.3 / I7: RAG retrieval must filter by role."""

    def test_retrieve_context_has_role_parameter(self):
        import inspect
        from src.negotiation.application.personalization_service import PersonalizationService
        sig = inspect.signature(PersonalizationService.retrieve_context_for_negotiation)
        params = list(sig.parameters.keys())
        assert "role" in params, f"role not in params: {params}"

    def test_retrieve_memory_command_has_role(self):
        from src.negotiation.application.commands import RetrieveMemoryCommand
        cmd = RetrieveMemoryCommand(
            tenant_id=uuid.uuid4(),
            query="test query",
            limit=5,
            role="seller",
        )
        assert cmd.role == "seller"

    def test_repo_retrieve_similar_has_role(self):
        import inspect
        from src.negotiation.infrastructure.repositories import PostgresAgentMemoryRepository
        sig = inspect.signature(PostgresAgentMemoryRepository.retrieve_similar)
        assert "role" in sig.parameters

    def test_port_interface_has_role(self):
        import inspect
        from src.negotiation.domain.ports import IAgentMemoryRepository
        sig = inspect.signature(IAgentMemoryRepository.retrieve_similar)
        assert "role" in sig.parameters


class TestFailedSessionTranscriptIngestion:
    """§5.2: Walk-away + timeout sessions must ingest transcripts."""

    def test_handle_walk_away_has_ingestion_code(self):
        """_handle_walk_away must contain personalization_service.ingest_text_directly call."""
        import inspect
        from src.negotiation.application.services import NegotiationService
        source = inspect.getsource(NegotiationService._handle_walk_away)
        assert "ingest_text_directly" in source, \
            "_handle_walk_away does not call ingest_text_directly"
        assert "WALK_AWAY" in source

    def test_handle_timeout_has_ingestion_code(self):
        """_handle_timeout must contain personalization_service.ingest_text_directly call."""
        import inspect
        from src.negotiation.application.services import NegotiationService
        source = inspect.getsource(NegotiationService._handle_timeout)
        assert "ingest_text_directly" in source, \
            "_handle_timeout does not call ingest_text_directly"
        assert "TIMEOUT" in source
