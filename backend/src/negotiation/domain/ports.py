# context.md §3 — Protocol interfaces ONLY here. No concrete classes.
# context.md §1.4 OCP: new LLM provider = new IAgentDriver adapter.
# Extended with IOpponentProfileRepository and IDANPStateMachine for DANP spec.

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol, runtime_checkable

from src.negotiation.domain.agent_profile import AgentProfile
from src.negotiation.domain.offer import Offer
from src.negotiation.domain.opponent_model import OpponentBelief
from src.negotiation.domain.playbook import IndustryPlaybook
from src.negotiation.domain.session import NegotiationSession


@runtime_checkable
class ISessionRepository(Protocol):
    async def save(self, session: NegotiationSession) -> None: ...
    async def get_by_id(self, session_id: uuid.UUID) -> NegotiationSession | None: ...
    async def get_by_match_id(self, match_id: uuid.UUID) -> NegotiationSession | None: ...
    async def update(self, session: NegotiationSession) -> None: ...
    async def list_active(self, limit: int, offset: int) -> list[NegotiationSession]: ...
    async def list_by_enterprise(
        self, enterprise_id: uuid.UUID | None, status: str | None, limit: int, offset: int,
    ) -> list[NegotiationSession]: ...
    async def list_expired_candidates(self, cutoff: datetime) -> list[NegotiationSession]: ...


@runtime_checkable
class IOfferRepository(Protocol):
    async def save(self, offer: Offer) -> None: ...
    async def list_by_session(self, session_id: uuid.UUID) -> list[Offer]: ...
    async def get_by_id(self, offer_id: uuid.UUID) -> Offer | None: ...


@runtime_checkable
class IAgentProfileRepository(Protocol):
    async def get_by_enterprise(self, enterprise_id: uuid.UUID) -> AgentProfile | None: ...
    async def save(self, profile: AgentProfile) -> None: ...
    async def update(self, profile: AgentProfile) -> None: ...


@runtime_checkable
class IPlaybookRepository(Protocol):
    async def get_by_vertical(self, vertical: str) -> IndustryPlaybook | None: ...
    async def list_all(self) -> list[IndustryPlaybook]: ...


@runtime_checkable
class IOpponentProfileRepository(Protocol):
    """Repository for persistent opponent belief profiles."""

    async def get_belief(
        self, observer_id: uuid.UUID, target_id: uuid.UUID
    ) -> OpponentBelief | None: ...

    async def save_belief(
        self,
        observer_id: uuid.UUID,
        target_id: uuid.UUID,
        belief: OpponentBelief,
        flexibility: float,
    ) -> None: ...

    async def update_belief(
        self,
        observer_id: uuid.UUID,
        target_id: uuid.UUID,
        belief: OpponentBelief,
        flexibility: float,
    ) -> None: ...


@runtime_checkable
class IAgentDriver(Protocol):
    """LLM-backed agent — OCP: new provider = new adapter, zero NegotiationService changes."""
    async def generate_offer(
        self,
        system_prompt: str,
        session_context: dict,
        offer_history: list[dict],
    ) -> dict: ...


@runtime_checkable
class INeutralEngine(Protocol):
    """Stateless protocol enforcer — buyer and seller NEVER communicate directly."""
    async def process_turn(
        self,
        session: NegotiationSession,
        buyer_profile: AgentProfile,
        seller_profile: AgentProfile,
        buyer_playbook: IndustryPlaybook | None,
        seller_playbook: IndustryPlaybook | None,
    ) -> tuple[Offer, bool]: ...


@runtime_checkable
class ISSEPublisher(Protocol):
    """Redis-backed SSE event queue."""
    async def publish_turn(self, session_id: uuid.UUID, event: dict) -> None: ...
    async def get_events_since(
        self, session_id: uuid.UUID, last_event_id: str | None
    ) -> list[dict]: ...
    async def publish_terminal(self, session_id: uuid.UUID, event: dict) -> None: ...


@runtime_checkable
class IS3Vault(Protocol):
    """
    Tenant-isolated S3 storage for enterprise documents.

    Bucket pattern: cadencia-agents-{tenant_id_prefix}
    Keys: raw/{tenant_id}/{filename}
    Encryption: AES256 SSE.
    """

    async def store_document(
        self,
        tenant_id: uuid.UUID,
        filename: str,
        content: bytes,
        mime_type: str,
    ) -> str: ...

    async def get_document(
        self, tenant_id: uuid.UUID, key: str
    ) -> bytes: ...

    async def list_documents(
        self, tenant_id: uuid.UUID
    ) -> list[str]: ...

    async def delete_document(
        self, tenant_id: uuid.UUID, key: str
    ) -> None: ...


@runtime_checkable
class IAgentMemoryRepository(Protocol):
    """
    pgvector-backed agent memory for RAG retrieval.

    Stores chunked + embedded enterprise documents for
    retrieval-augmented agent intelligence (Layer 3).
    """

    async def store(
        self,
        tenant_id: uuid.UUID,
        role: str,
        content: str,
        embedding: list[float],
        metadata: dict,
    ) -> uuid.UUID: ...

    async def retrieve_similar(
        self,
        tenant_id: uuid.UUID,
        query_embedding: list[float],
        limit: int,
        role: str | None = None,
    ) -> list[dict]: ...

    async def delete_by_tenant(
        self, tenant_id: uuid.UUID
    ) -> int: ...

    async def count_by_tenant(
        self, tenant_id: uuid.UUID
    ) -> int: ...


@runtime_checkable
class IEmbeddingService(Protocol):
    """
    Pluggable embedding service for document vectorization.

    OCP: new embedding provider = new adapter, zero pipeline changes.
    """

    async def embed_documents(
        self, texts: list[str]
    ) -> list[list[float]]: ...

    async def embed_query(
        self, text: str
    ) -> list[float]: ...


# ── Phase 6: Negotiation Memory Repositories ─────────────────────────────────

from src.negotiation.domain.negotiation_insight import NegotiationInsight  # noqa: E402
from src.negotiation.domain.negotiation_record import NegotiationRecord  # noqa: E402


@runtime_checkable
class INegotiationRecordRepository(Protocol):
    """
    Repository for canonical NegotiationRecord entities.

    All queries are tenant-scoped (enterprise_id mandatory filter) to
    enforce strict data isolation — no cross-enterprise queries permitted.
    """

    async def save(self, record: NegotiationRecord) -> None: ...

    async def get_by_id(
        self, record_id: uuid.UUID
    ) -> NegotiationRecord | None: ...

    async def list_by_enterprise(
        self,
        enterprise_id: uuid.UUID,
        filters: dict,
        limit: int,
        offset: int,
    ) -> list[NegotiationRecord]: ...

    async def get_by_session_id(
        self, session_id: uuid.UUID
    ) -> NegotiationRecord | None: ...

    async def search_similar(
        self,
        enterprise_id: uuid.UUID,
        query_embedding: list[float],
        limit: int,
    ) -> list[NegotiationRecord]: ...


@runtime_checkable
class INegotiationInsightRepository(Protocol):
    """Repository for per-enterprise aggregate NegotiationInsight."""

    async def get_by_enterprise(
        self, enterprise_id: uuid.UUID
    ) -> NegotiationInsight | None: ...

    async def save(self, insight: NegotiationInsight) -> None: ...

    async def upsert(self, insight: NegotiationInsight) -> None: ...

