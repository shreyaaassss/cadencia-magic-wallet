# context.md §7 — Domain Event Bus: all cross-domain communication via events.
# context.md §3 — zero framework imports in domain layer.

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

# Re-export events defined alongside their aggregates for a single import point.
from src.identity.domain.enterprise import (  # noqa: F401
    EnterpriseActivated,
    EnterpriseKYCSubmitted,
    EnterpriseKYCVerified,
)
from src.identity.domain.user import UserLoggedIn  # noqa: F401
from src.shared.domain.events import DomainEvent


@dataclass(frozen=True)
class EnterpriseRegistered(DomainEvent):
    """Emitted when a new enterprise completes registration."""

    enterprise_id: uuid.UUID = field(default_factory=uuid.uuid4)
    legal_name: str = ""
    trade_role: str = ""


@dataclass(frozen=True)
class APIKeyCreated(DomainEvent):
    """Emitted when an API key is created for an enterprise."""

    enterprise_id: uuid.UUID = field(default_factory=uuid.uuid4)
    key_id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass(frozen=True)
class APIKeyRevoked(DomainEvent):
    """Emitted when an API key is revoked."""

    enterprise_id: uuid.UUID = field(default_factory=uuid.uuid4)
    key_id: uuid.UUID = field(default_factory=uuid.uuid4)
