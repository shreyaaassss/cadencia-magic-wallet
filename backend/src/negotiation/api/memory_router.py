# Agent Memory API — Document upload, ingestion, and retrieval endpoints.
# context.md §4: API prefix /v1/*, API-first modular monolith.

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from src.identity.api.dependencies import get_current_user
from src.identity.domain.user import User
from src.shared.api.responses import success_response

router = APIRouter(prefix="/v1/agent-memory", tags=["agent-memory"])
records_router = APIRouter(prefix="/v1/negotiation-records", tags=["negotiation-records"])
insights_router = APIRouter(prefix="/v1/negotiation-insights", tags=["negotiation-insights"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class IngestRequest(BaseModel):
    tenant_id: uuid.UUID
    role: str = Field(default="buyer", pattern="^(buyer|seller)$")


class IngestResponse(BaseModel):
    tenant_id: str
    role: str
    docs_processed: int
    chunks_stored: int
    errors: list[str]


class RetrieveRequest(BaseModel):
    tenant_id: uuid.UUID
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=5, ge=1, le=20)


class MemoryChunkResponse(BaseModel):
    id: str
    content: str
    metadata: dict
    similarity: float


class MemoryStatsResponse(BaseModel):
    tenant_id: str
    total_chunks: int
    total_docs: int


# ── Dependency injection ──────────────────────────────────────────────────────


async def get_personalization_service():
    """Construct PersonalizationService with S3Vault and DB session."""
    import os
    from src.negotiation.application.personalization_service import PersonalizationService
    from src.negotiation.infrastructure.s3_vault import S3Vault

    s3 = S3Vault(
        bucket_prefix=os.environ.get("S3_AGENT_BUCKET_PREFIX", "cadencia-agents"),
        region=os.environ.get("AWS_REGION", "ap-south-1"),
    )
    return PersonalizationService(s3_vault=s3)


async def get_s3_vault():
    """Construct S3Vault from environment configuration."""
    import os
    from src.negotiation.infrastructure.s3_vault import S3Vault

    return S3Vault(
        bucket_prefix=os.environ.get("S3_AGENT_BUCKET_PREFIX", "cadencia-agents"),
        region=os.environ.get("AWS_REGION", "ap-south-1"),
    )


def _check_tenant_access(user: User, tenant_id: uuid.UUID) -> None:
    """Raise 403 if user's enterprise doesn't match the requested tenant."""
    if user.enterprise_id != tenant_id:
        raise HTTPException(status_code=403, detail="Access denied: tenant mismatch")


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/upload", status_code=201)
async def upload_document(
    tenant_id: Annotated[str, Form()],
    role: Annotated[str, Form()] = "buyer",
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    s3_vault: object = Depends(get_s3_vault),
) -> dict:
    """
    POST /v1/agent-memory/upload — Upload document to tenant S3 vault.

    Accepts multipart file upload. Stores in tenant-isolated S3 bucket.
    Call /ingest after uploading to process into agent memory.
    """
    tid = uuid.UUID(tenant_id)
    _check_tenant_access(user, tid)

    content = await file.read()
    mime_type = file.content_type or "application/octet-stream"
    filename = file.filename or f"upload_{uuid.uuid4().hex[:8]}"

    key = await s3_vault.store_document(  # type: ignore[union-attr]
        tenant_id=tid,
        filename=filename,
        content=content,
        mime_type=mime_type,
    )

    return success_response(
        data={
            "key": key,
            "filename": filename,
            "size_bytes": len(content),
            "mime_type": mime_type,
            "tenant_id": str(tid),
        },
        status_code=201,
    )


@router.post("/ingest")
async def ingest_documents(
    body: IngestRequest,
    user: User = Depends(get_current_user),
    svc: object = Depends(get_personalization_service),
) -> dict:
    """
    POST /v1/agent-memory/ingest — Full pipeline: S3 → chunk → embed → pgvector.

    Processes all documents in tenant's S3 vault into searchable agent memory.
    """
    _check_tenant_access(user, body.tenant_id)

    from src.negotiation.application.commands import IngestMemoryCommand

    cmd = IngestMemoryCommand(
        tenant_id=body.tenant_id,
        role=body.role,
    )
    result = await svc.ingest_enterprise_memory(cmd)  # type: ignore[union-attr]
    return success_response(data=result)


@router.post("/retrieve")
async def retrieve_similar(
    body: RetrieveRequest,
    user: User = Depends(get_current_user),
    svc: object = Depends(get_personalization_service),
) -> dict:
    """
    POST /v1/agent-memory/retrieve — Cosine similarity Top-N retrieval.

    Returns most relevant document chunks for a given query.
    Used by Layer 3 LLM advisory for RAG-augmented negotiation.
    """
    _check_tenant_access(user, body.tenant_id)

    from src.negotiation.application.commands import RetrieveMemoryCommand

    cmd = RetrieveMemoryCommand(
        tenant_id=body.tenant_id,
        query=body.query,
        limit=body.limit,
    )
    results = await svc.retrieve_similar(cmd)  # type: ignore[union-attr]
    return success_response(data=results)


@router.get("/{tenant_id}/stats")
async def get_memory_stats(
    tenant_id: uuid.UUID,
    user: User = Depends(get_current_user),
    svc: object = Depends(get_personalization_service),
) -> dict:
    """
    GET /v1/agent-memory/{tenant_id}/stats — Memory statistics.

    Returns count of stored chunks and documents for a tenant.
    """
    _check_tenant_access(user, tenant_id)
    stats = await svc.get_memory_stats(tenant_id)  # type: ignore[union-attr]
    return success_response(data=stats)


@router.delete("/{tenant_id}")
async def clear_memory(
    tenant_id: uuid.UUID,
    user: User = Depends(get_current_user),
    svc: object = Depends(get_personalization_service),
) -> dict:
    """
    DELETE /v1/agent-memory/{tenant_id} — Clear all memory for re-ingestion.
    """
    _check_tenant_access(user, tenant_id)
    deleted = await svc.clear_memory(tenant_id)  # type: ignore[union-attr]
    return success_response(data={"deleted": deleted, "tenant_id": str(tenant_id)})


# ── Negotiation Records API ───────────────────────────────────────────────────


class RecordListRequest(BaseModel):
    outcome: str | None = None
    record_type: str | None = None
    product_category: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class RecordSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=5, ge=1, le=20)


async def _get_record_repo(db_session):
    from src.negotiation.infrastructure.repositories import PostgresNegotiationRecordRepository
    return PostgresNegotiationRecordRepository(db_session)


async def _get_insight_repo(db_session):
    from src.negotiation.infrastructure.repositories import PostgresNegotiationInsightRepository
    return PostgresNegotiationInsightRepository(db_session)


async def _get_db():
    from src.shared.infrastructure.db.session import get_session_factory
    async with get_session_factory()() as session:
        yield session


@records_router.get("/{enterprise_id}")
async def list_negotiation_records(
    enterprise_id: uuid.UUID,
    outcome: str | None = None,
    record_type: str | None = None,
    product_category: str | None = None,
    limit: int = 20,
    offset: int = 0,
    user: User = Depends(get_current_user),
) -> dict:
    """
    GET /v1/negotiation-records/{enterprise_id}
    List normalized negotiation records with optional filters.
    """
    _check_tenant_access(user, enterprise_id)

    filters = {}
    if outcome:
        filters["outcome"] = outcome
    if record_type:
        filters["record_type"] = record_type
    if product_category:
        filters["product_category"] = product_category

    from src.shared.infrastructure.db.session import get_session_factory
    from src.negotiation.infrastructure.repositories import PostgresNegotiationRecordRepository

    async with get_session_factory()() as db_session:
        repo = PostgresNegotiationRecordRepository(db_session)
        records = await repo.list_by_enterprise(
            enterprise_id=enterprise_id,
            filters=filters,
            limit=limit,
            offset=offset,
        )

    return success_response(
        data=[
            {
                "id": str(r.id),
                "record_type": r.record_type.value,
                "enterprise_role": r.enterprise_role,
                "outcome": r.outcome.value,
                "product_name": r.product_name,
                "product_category": r.product_category,
                "agreed_price_inr": float(r.agreed_price_inr) if r.agreed_price_inr else None,
                "total_rounds": r.total_rounds,
                "deal_quality_score": float(r.deal_quality_score) if r.deal_quality_score else None,
                "buyer_style": r.buyer_style,
                "seller_style": r.seller_style,
                "conversation_summary": r.conversation_summary,
                "created_at": r.created_at.isoformat() if hasattr(r.created_at, "isoformat") else str(r.created_at),
            }
            for r in records
        ]
    )


@records_router.get("/{enterprise_id}/{record_id}")
async def get_negotiation_record(
    enterprise_id: uuid.UUID,
    record_id: uuid.UUID,
    user: User = Depends(get_current_user),
) -> dict:
    """
    GET /v1/negotiation-records/{enterprise_id}/{record_id}
    Get a single normalized negotiation record with full detail.
    """
    _check_tenant_access(user, enterprise_id)

    from src.shared.infrastructure.db.session import get_session_factory
    from src.negotiation.infrastructure.repositories import PostgresNegotiationRecordRepository

    async with get_session_factory()() as db_session:
        repo = PostgresNegotiationRecordRepository(db_session)
        record = await repo.get_by_id(record_id)

    if not record or record.enterprise_id != enterprise_id:
        raise HTTPException(status_code=404, detail="Negotiation record not found")

    return success_response(
        data={
            "id": str(record.id),
            "enterprise_id": str(record.enterprise_id),
            "record_type": record.record_type.value,
            "source_session_id": str(record.source_session_id) if record.source_session_id else None,
            "counterparty_enterprise_id": str(record.counterparty_enterprise_id) if record.counterparty_enterprise_id else None,
            "enterprise_role": record.enterprise_role,
            "product_name": record.product_name,
            "product_category": record.product_category,
            "hsn_code": record.hsn_code,
            "industry_vertical": record.industry_vertical,
            "outcome": record.outcome.value,
            "agreed_price_inr": float(record.agreed_price_inr) if record.agreed_price_inr else None,
            "initial_ask_price_inr": float(record.initial_ask_price_inr) if record.initial_ask_price_inr else None,
            "initial_bid_price_inr": float(record.initial_bid_price_inr) if record.initial_bid_price_inr else None,
            "final_discount_pct": float(record.final_discount_pct) if record.final_discount_pct else None,
            "total_rounds": record.total_rounds,
            "duration_hours": float(record.duration_hours) if record.duration_hours else None,
            "buyer_avg_concession_pct": float(record.buyer_avg_concession_pct) if record.buyer_avg_concession_pct else None,
            "seller_avg_concession_pct": float(record.seller_avg_concession_pct) if record.seller_avg_concession_pct else None,
            "buyer_style": record.buyer_style,
            "seller_style": record.seller_style,
            "deal_quality_score": float(record.deal_quality_score) if record.deal_quality_score else None,
            "agreed_terms": record.agreed_terms,
            "payment_terms": record.payment_terms,
            "delivery_window_days": record.delivery_window_days,
            "offer_sequence": record.offer_sequence,
            "conversation_summary": record.conversation_summary,
            "confidence_score": float(record.confidence_score) if record.confidence_score else None,
            "source_filename": record.source_filename,
            "normalized_at": record.normalized_at.isoformat() if record.normalized_at and hasattr(record.normalized_at, "isoformat") else str(record.normalized_at) if record.normalized_at else None,
            "created_at": record.created_at.isoformat() if hasattr(record.created_at, "isoformat") else str(record.created_at),
        }
    )


@records_router.post("/{enterprise_id}/search")
async def search_negotiation_records(
    enterprise_id: uuid.UUID,
    body: RecordSearchRequest,
    user: User = Depends(get_current_user),
) -> dict:
    """
    POST /v1/negotiation-records/{enterprise_id}/search
    Semantic search across negotiation records via pgvector cosine similarity.
    """
    _check_tenant_access(user, enterprise_id)

    import os as _os
    from src.shared.infrastructure.db.session import get_session_factory
    from src.negotiation.infrastructure.repositories import PostgresNegotiationRecordRepository
    from src.negotiation.infrastructure.embedding_pipeline import GeminiEmbedder, StubEmbedder

    if _os.environ.get("GEMINI_API_KEY"):
        embedding_svc = GeminiEmbedder()
    else:
        embedding_svc = StubEmbedder()

    try:
        query_embedding = await embedding_svc.embed_query(body.query)
    except Exception:
        raise HTTPException(status_code=503, detail="Embedding service unavailable")

    async with get_session_factory()() as db_session:
        repo = PostgresNegotiationRecordRepository(db_session)
        records = await repo.search_similar(
            enterprise_id=enterprise_id,
            query_embedding=query_embedding,
            limit=body.limit,
        )

    return success_response(
        data=[
            {
                "id": str(r.id),
                "record_type": r.record_type.value,
                "outcome": r.outcome.value,
                "product_name": r.product_name,
                "agreed_price_inr": float(r.agreed_price_inr) if r.agreed_price_inr else None,
                "conversation_summary": r.conversation_summary,
                "created_at": r.created_at.isoformat() if hasattr(r.created_at, "isoformat") else str(r.created_at),
            }
            for r in records
        ]
    )


# ── Negotiation Insights API ──────────────────────────────────────────────────


@insights_router.get("/{enterprise_id}")
async def get_negotiation_insights(
    enterprise_id: uuid.UUID,
    user: User = Depends(get_current_user),
) -> dict:
    """
    GET /v1/negotiation-insights/{enterprise_id}
    Get computed aggregate intelligence for an enterprise.
    """
    _check_tenant_access(user, enterprise_id)

    from src.shared.infrastructure.db.session import get_session_factory
    from src.negotiation.infrastructure.repositories import PostgresNegotiationInsightRepository

    async with get_session_factory()() as db_session:
        repo = PostgresNegotiationInsightRepository(db_session)
        insight = await repo.get_by_enterprise(enterprise_id)

    if not insight:
        return success_response(data=None)

    return success_response(
        data={
            "enterprise_id": str(insight.enterprise_id),
            "role": insight.role,
            "total_negotiations": insight.total_negotiations,
            "success_rate": float(insight.success_rate),
            "avg_rounds_to_close": float(insight.avg_rounds_to_close),
            "avg_discount_achieved_pct": float(insight.avg_discount_achieved_pct),
            "avg_deal_quality": float(insight.avg_deal_quality),
            "dominant_style": insight.dominant_style,
            "style_distribution": insight.style_distribution,
            "top_products": insight.top_products,
            "top_verticals": insight.top_verticals,
            "counterparty_stats": insight.counterparty_stats,
            "strategy_recommendations": insight.strategy_recommendations,
            "last_computed_at": insight.last_computed_at.isoformat() if insight.last_computed_at and hasattr(insight.last_computed_at, "isoformat") else str(insight.last_computed_at) if insight.last_computed_at else None,
        }
    )


@insights_router.get("/{enterprise_id}/stats")
async def get_negotiation_stats(
    enterprise_id: uuid.UUID,
    user: User = Depends(get_current_user),
) -> dict:
    """
    GET /v1/negotiation-insights/{enterprise_id}/stats
    Quick breakdown of agreed/rejected counts for buyer and seller role.
    Used by the dashboard Vault stat card.
    """
    _check_tenant_access(user, enterprise_id)

    from sqlalchemy import text as _text
    from src.shared.infrastructure.db.session import get_session_factory

    async with get_session_factory()() as db_session:
        result = await db_session.execute(
            _text(
                "SELECT enterprise_role, outcome, COUNT(*) as cnt "
                "FROM negotiation_records "
                "WHERE enterprise_id = :eid "
                "GROUP BY enterprise_role, outcome"
            ),
            {"eid": str(enterprise_id)},
        )
        rows = result.fetchall()

    stats: dict = {
        "as_buyer": {"agreed": 0, "rejected": 0, "stalled": 0, "total": 0},
        "as_seller": {"agreed": 0, "rejected": 0, "stalled": 0, "total": 0},
        "total_in_vault": 0,
    }
    outcome_map = {"AGREED": "agreed", "REJECTED": "rejected", "STALLED": "stalled",
                   "EXPIRED": "rejected", "UNKNOWN": "stalled"}
    for role, outcome, cnt in rows:
        bucket = "as_buyer" if role == "buyer" else "as_seller"
        key = outcome_map.get(outcome, "rejected")
        stats[bucket][key] += cnt
        stats[bucket]["total"] += cnt
        stats["total_in_vault"] += cnt

    return success_response(data=stats)


@insights_router.post("/{enterprise_id}/recompute")
async def recompute_negotiation_insights(
    enterprise_id: uuid.UUID,
    user: User = Depends(get_current_user),
) -> dict:
    """
    POST /v1/negotiation-insights/{enterprise_id}/recompute
    Force recompute aggregate insights from all negotiation records.
    """
    _check_tenant_access(user, enterprise_id)

    from src.shared.infrastructure.db.session import get_session_factory
    from src.negotiation.infrastructure.repositories import (
        PostgresNegotiationRecordRepository,
        PostgresNegotiationInsightRepository,
    )
    from src.negotiation.application.insight_engine import InsightEngine

    async with get_session_factory()() as db_session:
        record_repo = PostgresNegotiationRecordRepository(db_session)
        insight_repo = PostgresNegotiationInsightRepository(db_session)
        engine = InsightEngine(record_repo=record_repo, insight_repo=insight_repo)
        insight = await engine.compute_enterprise_insights(enterprise_id)
        await db_session.commit()

    return success_response(
        data={
            "enterprise_id": str(insight.enterprise_id),
            "total_negotiations": insight.total_negotiations,
            "success_rate": float(insight.success_rate),
            "last_computed_at": insight.last_computed_at.isoformat() if insight.last_computed_at and hasattr(insight.last_computed_at, "isoformat") else str(insight.last_computed_at),
            "status": "recomputed",
        }
    )
