# context.md §3 — Commands are pure Python dataclasses. No framework imports.

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class CreateSessionCommand:
    match_id: uuid.UUID
    rfq_id: uuid.UUID
    buyer_enterprise_id: uuid.UUID
    seller_enterprise_id: uuid.UUID
    # Optional: override the RFQ's primary parsed_fields with a specific product variant.
    # Used when a multi-product RFQ spawns per-product sessions — ensures each session
    # negotiates the correct product/budget instead of the primary product.
    override_rfq_parsed_fields: dict | None = None


@dataclass(frozen=True)
class HumanOverrideCommand:
    session_id: uuid.UUID
    price: Decimal
    currency: str = "INR"
    terms: dict = field(default_factory=dict)
    user_id: uuid.UUID = field(default_factory=uuid.uuid4)
    enterprise_id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass(frozen=True)
class TerminateSessionCommand:
    session_id: uuid.UUID
    reason: str = "Admin terminated"


@dataclass(frozen=True)
class IngestMemoryCommand:
    """Ingest enterprise documents: S3 → chunk → embed → pgvector."""
    tenant_id: uuid.UUID
    role: str = "buyer"  # buyer | seller
    filenames: list = field(default_factory=list)  # Specific files, or empty=all


@dataclass(frozen=True)
class RetrieveMemoryCommand:
    """Retrieve similar past negotiations for RAG context."""
    tenant_id: uuid.UUID
    query: str = ""
    limit: int = 5
    role: str | None = None  # "buyer" or "seller" — filters memory by perspective
