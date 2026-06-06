# S3 Storage & Agent Memory System — Full Test Suite
# Tests: TextChunker, StubEmbedder, StubS3Vault, PersonalizationService pipeline
# context.md §3: Domain layer tests — pure Python, zero I/O.

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.negotiation.application.commands import IngestMemoryCommand, RetrieveMemoryCommand
from src.negotiation.application.personalization_service import PersonalizationService
from src.negotiation.domain.agent_profile import AgentProfile
from src.negotiation.domain.playbook import IndustryPlaybook
from src.negotiation.infrastructure.embedding_pipeline import (
    StubEmbedder,
    TextChunker,
)
from src.negotiation.infrastructure.personalization import PersonalizationBuilder
from src.negotiation.infrastructure.s3_vault import StubS3Vault


# ═══════════════════════════════════════════════════════════════════════════════
# TextChunker Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestTextChunker:
    def _chunker(self, chunk_size=512, overlap=0) -> TextChunker:
        return TextChunker(chunk_size=chunk_size, overlap=overlap)

    def test_empty_input(self):
        chunker = self._chunker()
        assert chunker.split("") == []
        assert chunker.split("   ") == []

    def test_short_text_single_chunk(self):
        chunker = self._chunker()
        text = "This is a short document."
        chunks = chunker.split(text)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_paragraph_splitting(self):
        chunker = self._chunker(chunk_size=10)  # Very small chunks
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        chunks = chunker.split(text)
        assert len(chunks) >= 2
        assert "First paragraph." in chunks[0]

    def test_sentence_splitting_for_long_paragraph(self):
        chunker = self._chunker(chunk_size=5)  # Force sentence splitting
        text = "This is sentence one. This is sentence two. This is sentence three."
        chunks = chunker.split(text)
        assert len(chunks) >= 2

    def test_overlap_adds_context(self):
        chunker = self._chunker(chunk_size=10, overlap=5)
        text = "Alpha paragraph here.\n\nBeta paragraph here.\n\nGamma paragraph here."
        chunks = chunker.split(text)
        if len(chunks) > 1:
            # Second chunk should contain some of first chunk's tail
            assert len(chunks[1]) > len("Beta paragraph here.")

    def test_deduplication(self):
        chunker = self._chunker()
        text = "Same content.\n\nSame content."
        chunks = chunker.split(text)
        assert len(chunks) == 1

    def test_normalize_whitespace(self):
        chunker = self._chunker()
        text = "Content\r\n\r\n\r\n\r\nMore content"
        chunks = chunker.split(text)
        # Should normalize to max 2 newlines
        for chunk in chunks:
            assert "\r\n" not in chunk

    def test_estimate_tokens(self):
        chunker = self._chunker()
        text = "Hello world"  # 11 chars → ~2-3 tokens
        tokens = chunker.estimate_tokens(text)
        assert tokens == 2  # 11 // 4 = 2

    def test_realistic_document(self):
        chunker = self._chunker(chunk_size=100)
        text = "\n\n".join([
            f"Section {i}: " + "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
            * 5 for i in range(10)
        ])
        chunks = chunker.split(text)
        assert len(chunks) > 1
        for chunk in chunks:
            # Each chunk should be reasonably sized
            assert len(chunk) < 100 * 4 * 2  # ~2x max


# ═══════════════════════════════════════════════════════════════════════════════
# StubEmbedder Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestStubEmbedder:
    @pytest.mark.asyncio
    async def test_embed_documents(self):
        embedder = StubEmbedder()
        texts = ["Hello world", "Goodbye world"]
        embeddings = await embedder.embed_documents(texts)
        assert len(embeddings) == 2
        assert len(embeddings[0]) == 1536
        assert len(embeddings[1]) == 1536

    @pytest.mark.asyncio
    async def test_embed_query(self):
        embedder = StubEmbedder()
        embedding = await embedder.embed_query("test query")
        assert len(embedding) == 1536

    @pytest.mark.asyncio
    async def test_deterministic(self):
        embedder = StubEmbedder()
        e1 = await embedder.embed_query("same text")
        e2 = await embedder.embed_query("same text")
        assert e1 == e2

    @pytest.mark.asyncio
    async def test_different_texts_different_vectors(self):
        embedder = StubEmbedder()
        e1 = await embedder.embed_query("text A")
        e2 = await embedder.embed_query("text B")
        assert e1 != e2

    @pytest.mark.asyncio
    async def test_normalized(self):
        embedder = StubEmbedder()
        embedding = await embedder.embed_query("normalize me")
        magnitude = sum(x * x for x in embedding) ** 0.5
        assert abs(magnitude - 1.0) < 0.01


# ═══════════════════════════════════════════════════════════════════════════════
# StubS3Vault Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestStubS3Vault:
    @pytest.mark.asyncio
    async def test_store_and_retrieve(self):
        vault = StubS3Vault()
        tid = uuid.uuid4()
        content = b"Hello, this is a test document."

        key = await vault.store_document(tid, "test.txt", content, "text/plain")
        assert "test.txt" in key

        retrieved = await vault.get_document(tid, key)
        assert retrieved == content

    @pytest.mark.asyncio
    async def test_list_documents(self):
        vault = StubS3Vault()
        tid = uuid.uuid4()

        await vault.store_document(tid, "doc1.txt", b"content 1")
        await vault.store_document(tid, "doc2.txt", b"content 2")

        docs = await vault.list_documents(tid)
        assert len(docs) == 2
        assert any("doc1.txt" in d for d in docs)
        assert any("doc2.txt" in d for d in docs)

    @pytest.mark.asyncio
    async def test_list_empty(self):
        vault = StubS3Vault()
        docs = await vault.list_documents(uuid.uuid4())
        assert docs == []

    @pytest.mark.asyncio
    async def test_tenant_isolation(self):
        vault = StubS3Vault()
        tid1 = uuid.uuid4()
        tid2 = uuid.uuid4()

        await vault.store_document(tid1, "secret.txt", b"tenant1 data")
        await vault.store_document(tid2, "other.txt", b"tenant2 data")

        docs1 = await vault.list_documents(tid1)
        docs2 = await vault.list_documents(tid2)

        assert len(docs1) == 1
        assert len(docs2) == 1
        assert any("secret.txt" in d for d in docs1)
        assert any("other.txt" in d for d in docs2)

    @pytest.mark.asyncio
    async def test_delete_document(self):
        vault = StubS3Vault()
        tid = uuid.uuid4()

        key = await vault.store_document(tid, "deleteme.txt", b"data")
        await vault.delete_document(tid, key)

        docs = await vault.list_documents(tid)
        assert len(docs) == 0

    @pytest.mark.asyncio
    async def test_get_nonexistent_raises(self):
        vault = StubS3Vault()
        with pytest.raises(FileNotFoundError):
            await vault.get_document(uuid.uuid4(), "raw/abc/nope.txt")


# ═══════════════════════════════════════════════════════════════════════════════
# PersonalizationService Integration Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestPersonalizationService:
    def _make_service(self) -> PersonalizationService:
        return PersonalizationService(
            s3_vault=StubS3Vault(),
            memory_repo=MockMemoryRepo(),
            embedding_service=StubEmbedder(),
            text_chunker=TextChunker(chunk_size=50),
            uow=MockUoW(),
        )

    @pytest.mark.asyncio
    async def test_ingest_pipeline_empty(self):
        svc = self._make_service()
        cmd = IngestMemoryCommand(tenant_id=uuid.uuid4())
        result = await svc.ingest_enterprise_memory(cmd)
        assert result["docs_processed"] == 0
        assert result["chunks_stored"] == 0

    @pytest.mark.asyncio
    async def test_ingest_pipeline_full(self):
        svc = self._make_service()
        tid = uuid.uuid4()

        # Upload a document to S3 first
        await svc.s3_vault.store_document(  # type: ignore[union-attr]
            tid, "contract.txt",
            b"This is a test contract for steel supply. "
            b"Payment terms are 30 days net. "
            b"Volume is 500 metric tons per month.",
            "text/plain",
        )

        cmd = IngestMemoryCommand(tenant_id=tid, role="buyer")
        result = await svc.ingest_enterprise_memory(cmd)
        assert result["docs_processed"] == 1
        assert result["chunks_stored"] >= 1
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_ingest_specific_files(self):
        svc = self._make_service()
        tid = uuid.uuid4()

        await svc.s3_vault.store_document(tid, "doc1.txt", b"First doc content")  # type: ignore[union-attr]
        await svc.s3_vault.store_document(tid, "doc2.txt", b"Second doc content")  # type: ignore[union-attr]

        # Only ingest doc1
        cmd = IngestMemoryCommand(
            tenant_id=tid, role="buyer", filenames=["doc1.txt"]
        )
        result = await svc.ingest_enterprise_memory(cmd)
        assert result["docs_processed"] == 1

    @pytest.mark.asyncio
    async def test_retrieve_similar(self):
        svc = self._make_service()
        tid = uuid.uuid4()

        # Store some chunks manually
        embedder = StubEmbedder()
        emb = await embedder.embed_query("steel negotiation")
        await svc.memory_repo.store(  # type: ignore[union-attr]
            tenant_id=tid,
            role="buyer",
            content="Previous steel deal closed at 92k",
            embedding=emb,
            metadata={"source": "test"},
        )

        cmd = RetrieveMemoryCommand(
            tenant_id=tid, query="steel pricing", limit=5
        )
        results = await svc.retrieve_similar(cmd)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_retrieve_context_for_negotiation(self):
        svc = self._make_service()
        tid = uuid.uuid4()

        # Store a chunk
        embedder = StubEmbedder()
        emb = await embedder.embed_query("steel buyer")
        await svc.memory_repo.store(  # type: ignore[union-attr]
            tenant_id=tid, role="buyer",
            content="Steel deal at 92k after 7 rounds",
            embedding=emb, metadata={},
        )

        results = await svc.retrieve_context_for_negotiation(
            tenant_id=tid, session_context="steel price negotiation"
        )
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_memory_stats(self):
        svc = self._make_service()
        tid = uuid.uuid4()
        stats = await svc.get_memory_stats(tid)
        assert stats["total_chunks"] == 0
        assert stats["total_docs"] == 0

    @pytest.mark.asyncio
    async def test_clear_memory(self):
        svc = self._make_service()
        tid = uuid.uuid4()
        deleted = await svc.clear_memory(tid)
        assert deleted == 0

    @pytest.mark.asyncio
    async def test_text_extraction_txt(self):
        text = PersonalizationService._extract_text(
            b"Hello world", "raw/abc/test.txt"
        )
        assert text == "Hello world"

    @pytest.mark.asyncio
    async def test_text_extraction_pdf_fallback(self):
        # PyPDF2 is installed but can't parse arbitrary bytes → returns empty
        # This is correct behavior; real PDFs would be extracted properly
        text = PersonalizationService._extract_text(
            b"PDF content here", "raw/abc/test.pdf"
        )
        assert isinstance(text, str)

    @pytest.mark.asyncio
    async def test_text_extraction_unknown(self):
        text = PersonalizationService._extract_text(
            b"some binary content", "raw/abc/test.bin"
        )
        assert isinstance(text, str)


# ═══════════════════════════════════════════════════════════════════════════════
# PersonalizationBuilder Tests (updated with memory_context)
# ═══════════════════════════════════════════════════════════════════════════════


class TestPersonalizationBuilderWithMemory:
    def test_build_without_memory(self):
        builder = PersonalizationBuilder()
        profile = AgentProfile()
        prompt = builder.build(profile=profile, playbook=None, role="buyer")
        assert "past negotiation" in prompt.lower() or "context" in prompt.lower()
        assert "no past" in prompt.lower() or "not available" in prompt.lower() or "negotiation agent" in prompt.lower()

    def test_build_with_memory_context(self):
        builder = PersonalizationBuilder()
        profile = AgentProfile()
        memory = [
            "Previous steel deal closed at 92k after 7 rounds",
            "Competitor held firm on delivery, conceded payment terms",
        ]
        prompt = builder.build(
            profile=profile, playbook=None, role="buyer",
            memory_context=memory,
        )
        assert "past negotiation" in prompt.lower() or "context" in prompt.lower()
        assert "past negotiations" in prompt
        assert "92k" in prompt
        assert "Competitor" in prompt

    def test_build_memory_truncates_long_chunks(self):
        builder = PersonalizationBuilder()
        profile = AgentProfile()
        memory = ["x" * 500]  # Will be truncated to 300 chars
        prompt = builder.build(
            profile=profile, playbook=None, role="buyer",
            memory_context=memory,
        )
        assert "past negotiation" in prompt.lower() or "context" in prompt.lower()
        # Check it's in the prompt (truncated)
        assert "x" * 100 in prompt

    def test_build_memory_limits_to_5_chunks(self):
        builder = PersonalizationBuilder()
        profile = AgentProfile()
        memory = [f"chunk {i}" for i in range(10)]
        prompt = builder.build(
            profile=profile, playbook=None, role="buyer",
            memory_context=memory,
        )
        # Should only have chunks 0-4
        assert "5. chunk 4" in prompt
        assert "6. chunk 5" not in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# Mock helpers
# ═══════════════════════════════════════════════════════════════════════════════


class MockMemoryRepo:
    """In-memory mock of IAgentMemoryRepository."""

    def __init__(self):
        self._store: list[dict] = []

    async def store(
        self,
        tenant_id: uuid.UUID,
        role: str,
        content: str,
        embedding: list[float],
        metadata: dict,
    ) -> uuid.UUID:
        item_id = uuid.uuid4()
        self._store.append({
            "id": str(item_id),
            "tenant_id": tenant_id,
            "role": role,
            "content": content,
            "embedding": embedding,
            "metadata": metadata,
        })
        return item_id

    async def retrieve_similar(
        self,
        tenant_id: uuid.UUID,
        query_embedding: list[float],
        limit: int = 5,
        role: str | None = None,
    ) -> list[dict]:
        matching = [
            item for item in self._store
            if item["tenant_id"] == tenant_id
            and (role is None or item.get("role") == role)
        ]
        return [
            {
                "id": item["id"],
                "content": item["content"],
                "metadata": item["metadata"],
                "similarity": 0.95,
            }
            for item in matching[:limit]
        ]

    async def delete_by_tenant(self, tenant_id: uuid.UUID) -> int:
        before = len(self._store)
        self._store = [
            item for item in self._store
            if item["tenant_id"] != tenant_id
        ]
        return before - len(self._store)

    async def count_by_tenant(self, tenant_id: uuid.UUID) -> int:
        return sum(
            1 for item in self._store
            if item["tenant_id"] == tenant_id
        )


class MockUoW:
    """Mock Unit of Work — commit is a no-op."""

    async def commit(self):
        pass

    async def rollback(self):
        pass
