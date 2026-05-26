# PersonalizationService — S3 → Chunk → Embed → pgvector pipeline.
# Orchestrates the full document ingestion and RAG retrieval flow.
# context.md §1.4 DIP: all dependencies injected via constructor.

from __future__ import annotations

import uuid

import structlog

from src.negotiation.application.commands import IngestMemoryCommand, RetrieveMemoryCommand

log = structlog.get_logger(__name__)


class PersonalizationService:
    """
    Orchestrates enterprise document ingestion and RAG retrieval.

    Pipeline:
      1. List raw docs from S3 tenant vault
      2. Download + extract text
      3. Chunk into 512-token segments
      4. Embed via Gemini (1536-dim)
      5. Store in pgvector (agent_memory table)

    Retrieval:
      Query → embed → cosine similarity Top-5 → inject into LLM prompt.
    """

    def __init__(
        self,
        s3_vault: object,         # IS3Vault
        memory_repo: object,      # IAgentMemoryRepository
        embedding_service: object, # IEmbeddingService
        text_chunker: object,     # TextChunker
        uow: object,             # Unit of Work
    ) -> None:
        self.s3_vault = s3_vault
        self.memory_repo = memory_repo
        self.embedding_service = embedding_service
        self.text_chunker = text_chunker
        self.uow = uow

    async def ingest_enterprise_memory(
        self, cmd: IngestMemoryCommand
    ) -> dict:
        """
        Full pipeline: S3 → chunks → embeddings → pgvector.

        Returns summary of ingestion results.
        """
        tenant_id = cmd.tenant_id
        role = cmd.role

        # 1. List raw docs from S3
        if cmd.filenames:
            doc_keys = [
                f"raw/{tenant_id.hex}/{fn}" for fn in cmd.filenames
            ]
        else:
            doc_keys = await self.s3_vault.list_documents(tenant_id)  # type: ignore[union-attr]

        if not doc_keys:
            log.info("ingest_no_docs", tenant_id=str(tenant_id))
            return {"tenant_id": str(tenant_id), "chunks_stored": 0, "docs_processed": 0}

        total_chunks = 0
        docs_processed = 0
        errors: list[str] = []

        for key in doc_keys:
            try:
                # 2. Download + extract text
                content_bytes = await self.s3_vault.get_document(  # type: ignore[union-attr]
                    tenant_id, key
                )
                text_content = self._extract_text(content_bytes, key)

                if not text_content.strip():
                    log.warning("ingest_empty_doc", key=key)
                    continue

                # 3. Chunk (512 tokens)
                chunks = self.text_chunker.split(text_content)  # type: ignore[union-attr]

                if not chunks:
                    continue

                # 4. Embed (Gemini / Stub)
                embeddings = await self.embedding_service.embed_documents(  # type: ignore[union-attr]
                    chunks
                )

                # 5. Store in pgvector
                for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                    await self.memory_repo.store(  # type: ignore[union-attr]
                        tenant_id=tenant_id,
                        role=role,
                        content=chunk,
                        embedding=embedding,
                        metadata={
                            "source": key,
                            "chunk_index": i,
                            "total_chunks": len(chunks),
                            "original_filename": key.split("/")[-1],
                        },
                    )
                    total_chunks += 1

                docs_processed += 1
                log.info(
                    "ingest_doc_complete",
                    key=key,
                    chunks=len(chunks),
                    tenant_id=str(tenant_id),
                )

            except Exception as e:
                log.error("ingest_doc_failed", key=key, error=str(e))
                errors.append(f"{key}: {str(e)}")

        await self.uow.commit()  # type: ignore[union-attr]

        result = {
            "tenant_id": str(tenant_id),
            "role": role,
            "docs_processed": docs_processed,
            "chunks_stored": total_chunks,
            "errors": errors,
        }
        log.info("ingest_complete", **result)
        return result

    async def retrieve_similar(
        self, cmd: RetrieveMemoryCommand
    ) -> list[dict]:
        """
        Retrieve Top-N similar document chunks for RAG.

        Query → embed → cosine similarity → ranked results.
        """
        # Embed the query
        query_embedding = await self.embedding_service.embed_query(  # type: ignore[union-attr]
            cmd.query
        )

        # Retrieve from pgvector
        results = await self.memory_repo.retrieve_similar(  # type: ignore[union-attr]
            tenant_id=cmd.tenant_id,
            query_embedding=query_embedding,
            limit=cmd.limit,
        )

        log.info(
            "memory_retrieved",
            tenant_id=str(cmd.tenant_id),
            query_len=len(cmd.query),
            results_count=len(results),
        )
        return results

    async def retrieve_context_for_negotiation(
        self,
        tenant_id: uuid.UUID,
        session_context: str,
        limit: int = 5,
    ) -> list[str]:
        """
        Convenience: retrieve context strings for injection into Layer 3 LLM.

        Returns list of text chunks (most similar first).
        """
        cmd = RetrieveMemoryCommand(
            tenant_id=tenant_id,
            query=session_context,
            limit=limit,
        )
        results = await self.retrieve_similar(cmd)
        return [r["content"] for r in results]

    async def ingest_text_directly(
        self,
        tenant_id: uuid.UUID,
        text: str,
        role: str,
        metadata: dict | None = None,
    ) -> dict:
        """
        Directly ingest a text string into pgvector (no S3 download needed).
        Used for auto-ingesting completed session transcripts.
        Returns {'chunks_stored': N}.
        """
        try:
            chunks = self.text_chunker.split(text)  # type: ignore[union-attr]
            if not chunks:
                return {"chunks_stored": 0}

            stored = 0
            async with self.uow:
                embeddings = await self.embedding_service.embed_documents(chunks)  # type: ignore[union-attr]
                for chunk, embedding in zip(chunks, embeddings):
                    if not embedding:
                        continue
                    await self.memory_repo.store(  # type: ignore[union-attr]
                        tenant_id=tenant_id,
                        role=role,
                        content=chunk,
                        embedding=embedding,
                        metadata={
                            "source": "session_transcript",
                            **(metadata or {}),
                        },
                    )
                    stored += 1
                await self.uow.commit()  # type: ignore[union-attr]

            return {"chunks_stored": stored}
        except Exception as exc:
            log.warning("ingest_text_directly_failed", tenant_id=str(tenant_id), error=str(exc))
            return {"chunks_stored": 0}

    async def get_memory_stats(self, tenant_id: uuid.UUID) -> dict:
        """Return memory stats for a tenant."""
        count = await self.memory_repo.count_by_tenant(tenant_id)  # type: ignore[union-attr]
        docs = await self.s3_vault.list_documents(tenant_id)  # type: ignore[union-attr]
        return {
            "tenant_id": str(tenant_id),
            "total_chunks": count,
            "total_docs": len(docs),
        }

    async def clear_memory(self, tenant_id: uuid.UUID) -> int:
        """Delete all memory for a tenant (for re-ingestion)."""
        deleted = await self.memory_repo.delete_by_tenant(tenant_id)  # type: ignore[union-attr]
        await self.uow.commit()  # type: ignore[union-attr]
        log.info("memory_cleared", tenant_id=str(tenant_id), deleted=deleted)
        return deleted

    # ── Private Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _extract_text(content: bytes, key: str) -> str:
        """
        Extract text from document bytes.

        Supports: .txt, .md, .csv, .json (direct decode)
        For .pdf: basic text extraction (production would use OCR).
        """
        filename = key.lower().split("/")[-1]

        # Plain text formats
        if any(filename.endswith(ext) for ext in (".txt", ".md", ".csv", ".json", ".log")):
            return content.decode("utf-8", errors="replace")

        # PDF: basic extraction
        if filename.endswith(".pdf"):
            return PersonalizationService._extract_pdf_text(content)

        # Fallback: try UTF-8 decode
        try:
            return content.decode("utf-8", errors="replace")
        except Exception:
            return ""

    @staticmethod
    def _extract_pdf_text(content: bytes) -> str:
        """
        Basic PDF text extraction.

        Uses pypdf (preferred) or PyPDF2 (legacy fallback).
        Production would use OCR (Tesseract/Google Vision).
        """
        from io import BytesIO

        # Try pypdf first (modern, maintained)
        try:
            from pypdf import PdfReader  # type: ignore[import-untyped]

            reader = PdfReader(BytesIO(content))
            text_parts = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
            return "\n\n".join(text_parts)
        except ImportError:
            pass
        except Exception:
            return ""

        # Fallback: raw UTF-8 decode
        return content.decode("utf-8", errors="replace")
