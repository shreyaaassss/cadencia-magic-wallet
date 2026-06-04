# Agent Memory Embedding Pipeline — Text chunking + embedding for RAG.
# Infrastructure layer. Implements IEmbeddingService protocol.
#
# Components:
#   TextChunker     — Splits documents into 512-token semantic chunks
#   GeminiEmbedder  — Embeds chunks via Google Gemini API (1536-dim)
#   StubEmbedder    — Deterministic stub for testing (no API key needed)

from __future__ import annotations

import hashlib
import os
import re

import structlog

log = structlog.get_logger(__name__)

_DEFAULT_CHUNK_SIZE = int(os.getenv("S3_MEMORY_CHUNK_SIZE", "512"))
_EMBEDDING_DIM = 1536


# ═══════════════════════════════════════════════════════════════════════════════
# Text Chunker — Semantic 512-token splitting
# ═══════════════════════════════════════════════════════════════════════════════


class TextChunker:
    """
    Split raw text into overlapping chunks for embedding.

    Strategy:
      1. Split on paragraph boundaries (double newline)
      2. If paragraph > chunk_size tokens, split on sentence boundaries
      3. Overlap: 64 tokens between chunks for context continuity
      4. Strip empty chunks and normalize whitespace

    Token estimation: ~4 chars per token (GPT-family heuristic).
    """

    def __init__(
        self,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        overlap: int = 64,
        chars_per_token: int = 4,
    ) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.chars_per_token = chars_per_token
        self._max_chars = chunk_size * chars_per_token
        self._overlap_chars = overlap * chars_per_token

    def split(self, text: str) -> list[str]:
        """
        Split text into chunks of approximately `chunk_size` tokens.

        Returns list of non-empty text chunks.
        """
        if not text or not text.strip():
            return []

        # Normalize whitespace
        text = re.sub(r"\r\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()

        # 1. Try paragraph-level splitting
        paragraphs = text.split("\n\n")
        chunks: list[str] = []
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current_chunk) + len(para) + 2 <= self._max_chars:
                current_chunk = (
                    f"{current_chunk}\n\n{para}" if current_chunk else para
                )
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                # If single paragraph exceeds chunk size, split by sentences
                if len(para) > self._max_chars:
                    sentence_chunks = self._split_by_sentences(para)
                    chunks.extend(sentence_chunks)
                    current_chunk = ""
                else:
                    current_chunk = para

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        # 2. Add overlap between chunks
        if self._overlap_chars > 0 and len(chunks) > 1:
            chunks = self._add_overlap(chunks)

        # 3. Filter empty and deduplicate
        seen = set()
        result = []
        for chunk in chunks:
            chunk = chunk.strip()
            if chunk and chunk not in seen:
                seen.add(chunk)
                result.append(chunk)

        return result

    def _split_by_sentences(self, text: str) -> list[str]:
        """Split long text by sentence boundaries."""
        # Regex: split on . ! ? followed by whitespace or end
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks: list[str] = []
        current = ""

        for sentence in sentences:
            if len(current) + len(sentence) + 1 <= self._max_chars:
                current = f"{current} {sentence}" if current else sentence
            else:
                if current:
                    chunks.append(current.strip())
                current = sentence

        if current.strip():
            chunks.append(current.strip())

        return chunks

    def _add_overlap(self, chunks: list[str]) -> list[str]:
        """Add trailing overlap from previous chunk to each chunk."""
        result = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_tail = chunks[i - 1][-self._overlap_chars :]
            result.append(f"{prev_tail} {chunks[i]}")
        return result

    def estimate_tokens(self, text: str) -> int:
        """Approximate token count."""
        return len(text) // self.chars_per_token


# ═══════════════════════════════════════════════════════════════════════════════
# Embedding Services — Implements IEmbeddingService
# ═══════════════════════════════════════════════════════════════════════════════


class GeminiEmbedder:
    """
    Google Gemini embedding service.

    Produces 1536-dimensional float vectors for cosine similarity.
    Uses google-generativeai SDK (infrastructure-only import).

    Rate-limited to 50 req/min via shared LLM rate limiter.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "models/text-embedding-004",
    ) -> None:
        primary = (api_key or os.getenv("GEMINI_API_KEY", "")).strip()
        self._api_keys = [primary] if primary else []
        gk2 = os.getenv("GEMINI_API_KEY_2", "").strip()
        if gk2 and gk2 not in self._api_keys:
            self._api_keys.append(gk2)
        self._model = model
        self._client: object | None = None
        self._active_key_index = 0

    def _ensure_client(self) -> None:
        """Lazy-init Gemini client with current API key."""
        if self._client is None and self._api_keys:
            import google.generativeai as genai  # Infrastructure-only

            genai.configure(api_key=self._api_keys[self._active_key_index])
            self._client = genai

    async def embed_documents(
        self, texts: list[str]
    ) -> list[list[float]]:
        """Embed a batch of document chunks."""
        self._ensure_client()

        embeddings: list[list[float]] = []
        # Batch in groups of 20 to stay under rate limits
        batch_size = 20
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            try:
                result = self._client.embed_content(  # type: ignore[union-attr]
                    model=self._model,
                    content=batch,
                    task_type="retrieval_document",
                )
                if isinstance(result["embedding"], list) and isinstance(
                    result["embedding"][0], list
                ):
                    embeddings.extend(result["embedding"])
                else:
                    embeddings.append(result["embedding"])
            except Exception as e:
                log.warning("gemini_embed_failed", error=str(e), batch_size=len(batch))
                if self._active_key_index + 1 < len(self._api_keys):
                    self._active_key_index += 1
                    self._client = None
                    self._ensure_client()
                    return await self.embed_documents(texts)
                raise

        log.info("gemini_embedded", count=len(texts), dim=_EMBEDDING_DIM)
        return embeddings

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query for retrieval."""
        self._ensure_client()
        try:
            result = self._client.embed_content(  # type: ignore[union-attr]
                model=self._model,
                content=text,
                task_type="retrieval_query",
            )
            return result["embedding"]
        except Exception as e:
            log.warning("gemini_query_embed_failed", error=str(e))
            if self._active_key_index + 1 < len(self._api_keys):
                self._active_key_index += 1
                self._client = None
                self._ensure_client()
                return await self.embed_query(text)
            raise


class StubEmbedder:
    """
    Deterministic embedding stub for development and testing.

    Generates reproducible 1536-dim vectors from text hashing.
    No API key required.
    """

    def __init__(self, dim: int = _EMBEDDING_DIM) -> None:
        self._dim = dim

    def _hash_to_vector(self, text: str) -> list[float]:
        """Convert text to a deterministic normalized vector."""
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        # Repeat hash to fill dimension
        expanded = (h * (self._dim // len(h) + 1))[: self._dim]
        raw = [ord(c) / 128.0 - 0.5 for c in expanded]
        # L2-normalize
        magnitude = sum(x * x for x in raw) ** 0.5
        if magnitude > 0:
            return [x / magnitude for x in raw]
        return raw

    async def embed_documents(
        self, texts: list[str]
    ) -> list[list[float]]:
        return [self._hash_to_vector(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._hash_to_vector(text)
