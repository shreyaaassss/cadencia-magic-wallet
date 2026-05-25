# context.md §3 — Hexagonal Architecture:
#   Ports are Protocol interfaces — the ONLY way the domain touches infrastructure.
#   Concrete adapters in infrastructure/ implement these Protocols.
#   context.md §13 — Port Interface Catalogue.
# context.md §4 — SOLID ISP: IEnterpriseReader separate from IEnterpriseWriter.

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from src.identity.domain.enterprise import Enterprise
from src.identity.domain.user import User


@runtime_checkable
class IEnterpriseRepository(Protocol):
    """
    Port interface for enterprise persistence.
    context.md §13: PostgresEnterpriseRepository is the concrete adapter.
    """

    async def save(self, enterprise: Enterprise) -> None: ...
    async def get_by_id(self, enterprise_id: uuid.UUID) -> Enterprise | None: ...
    async def get_by_pan(self, pan: str) -> Enterprise | None: ...
    async def get_by_gstin(self, gstin: str) -> Enterprise | None: ...
    async def get_by_wallet_address(self, wallet_address: str) -> Enterprise | None: ...
    async def update(self, enterprise: Enterprise) -> None: ...


@runtime_checkable
class IUserRepository(Protocol):
    """
    Port interface for user persistence.
    context.md §13: PostgresUserRepository is the concrete adapter.
    """

    async def save(self, user: User) -> None: ...
    async def get_by_id(self, user_id: uuid.UUID) -> User | None: ...
    async def get_by_email(self, email: str) -> User | None: ...
    async def update(self, user: User) -> None: ...
    async def list_by_enterprise(self, enterprise_id: uuid.UUID) -> list[User]: ...


@runtime_checkable
class IAPIKeyRepository(Protocol):
    """
    Port interface for API key persistence.
    context.md §14: keys stored as HMAC-SHA256 hashes; plaintext never persisted.
    """

    async def save(
        self,
        key_hash: str,
        enterprise_id: uuid.UUID,
        key_id: uuid.UUID,
        label: str | None,
    ) -> None: ...

    async def get_by_hash(self, key_hash: str) -> dict | None: ...

    async def revoke(self, key_id: uuid.UUID, enterprise_id: uuid.UUID) -> None: ...

    async def list_by_enterprise(self, enterprise_id: uuid.UUID) -> list[dict]: ...


@runtime_checkable
class IJWTService(Protocol):
    """
    Port interface for JWT token operations.
    context.md §14: RS256-signed tokens; HS256 PROHIBITED in production.
    """

    def create_access_token(
        self,
        subject: str,
        enterprise_id: uuid.UUID,
        role: str,
    ) -> str: ...

    def create_refresh_token(self, subject: str) -> str: ...

    def decode_access_token(self, token: str) -> dict: ...

    def decode_refresh_token(self, token: str) -> dict: ...


@runtime_checkable
class IKYCAdapter(Protocol):
    """
    Port interface for KYC provider.
    Phase One: MockKYCAdapter. Production: real provider via same interface.
    context.md §6: KYC Provider integration type.
    """

    async def submit(
        self,
        enterprise_id: uuid.UUID,
        documents: dict,
    ) -> dict: ...

    async def verify(self, enterprise_id: uuid.UUID) -> bool: ...
