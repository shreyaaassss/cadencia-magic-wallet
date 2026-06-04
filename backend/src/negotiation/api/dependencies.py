# context.md §4 DIP: dependencies wired here via FastAPI Depends().

from __future__ import annotations

import os

import structlog
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.negotiation.application.personalization_service import PersonalizationService
from src.negotiation.application.services import NegotiationService
from src.negotiation.infrastructure.embedding_pipeline import (
    GeminiEmbedder,
    StubEmbedder,
    TextChunker,
)
from src.negotiation.infrastructure.llm_agent_driver import get_agent_driver, get_analysis_driver
from src.negotiation.infrastructure.neutral_engine import NeutralEngine
from src.negotiation.infrastructure.personalization import PersonalizationBuilder
from src.negotiation.infrastructure.repositories import (
    PostgresAgentMemoryRepository,
    PostgresAgentProfileRepository,
    PostgresNegotiationInsightRepository,
    PostgresNegotiationRecordRepository,
    PostgresOfferRepository,
    PostgresOpponentProfileRepository,
    PostgresPlaybookRepository,
    PostgresSessionRepository,
)
from src.negotiation.infrastructure.s3_vault import S3Vault
from src.negotiation.infrastructure.sse_publisher import RedisSSEPublisher
from src.shared.infrastructure.cache.redis_client import get_redis_client
from src.shared.infrastructure.db.session import get_db_session
from src.shared.infrastructure.db.uow import SqlAlchemyUnitOfWork
from src.shared.infrastructure.events.publisher import get_publisher

_dep_log = structlog.get_logger(__name__)


async def get_sse_publisher() -> RedisSSEPublisher:
    redis = get_redis_client()
    return RedisSSEPublisher(redis)


def get_negotiation_service(
    session: AsyncSession = Depends(get_db_session),
) -> NegotiationService:
    """Wire NegotiationService with all concrete adapters."""
    agent_driver = get_agent_driver()

    # Wire SSE publisher using the synchronous get_redis_client() singleton
    sse_pub = None
    try:
        redis = get_redis_client()
        sse_pub = RedisSSEPublisher(redis)
    except Exception as e:
        _dep_log.warning("sse_publisher_init_failed", error=str(e))

    # Wire PersonalizationService for RAG context injection
    personalization_service = None
    try:
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        embedder = GeminiEmbedder(api_key=gemini_key) if gemini_key else StubEmbedder()
        s3_vault = S3Vault()
        personalization_service = PersonalizationService(
            s3_vault=s3_vault,
            memory_repo=PostgresAgentMemoryRepository(session),
            embedding_service=embedder,
            text_chunker=TextChunker(),
            uow=SqlAlchemyUnitOfWork(session),
        )
    except Exception as e:
        _dep_log.warning("personalization_service_init_failed", error=str(e))

    opponent_profile_repo = PostgresOpponentProfileRepository(session)

    # Wire analysis driver (lightweight LLM for pre-negotiation analysis)
    analysis_driver = None
    try:
        analysis_driver = get_analysis_driver()
    except Exception as e:
        _dep_log.warning("analysis_driver_init_failed", error=str(e))

    neutral_engine = NeutralEngine(
        agent_driver=agent_driver,
        personalization_builder=PersonalizationBuilder(),
        sse_publisher=sse_pub,
        personalization_service=personalization_service,
        opponent_profile_repo=opponent_profile_repo,
        analysis_driver=analysis_driver,
        record_repo=PostgresNegotiationRecordRepository(session),
        insight_repo=PostgresNegotiationInsightRepository(session),
    )

    return NegotiationService(
        session_repo=PostgresSessionRepository(session),
        offer_repo=PostgresOfferRepository(session),
        profile_repo=PostgresAgentProfileRepository(session),
        playbook_repo=PostgresPlaybookRepository(session),
        neutral_engine=neutral_engine,
        sse_publisher=sse_pub,
        event_publisher=get_publisher(),
        uow=SqlAlchemyUnitOfWork(session),
    )
