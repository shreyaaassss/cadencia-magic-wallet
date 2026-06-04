# context.md §3 — Hexagonal Architecture: zero framework imports.

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from src.identity.domain.value_objects import Email, HashedPassword
from src.shared.domain.base_entity import BaseEntity
from src.shared.domain.events import DomainEvent
from src.shared.domain.exceptions import PolicyViolation


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"
    BUYER = "BUYER"
    SELLER = "SELLER"
    TREASURY_MANAGER = "TREASURY_MANAGER"
    COMPLIANCE_OFFICER = "COMPLIANCE_OFFICER"
    AUDITOR = "AUDITOR"


@dataclass
class User(BaseEntity):
    """
    User entity (identity bounded context).

    Each user belongs to exactly one enterprise.
    Authentication delegates to HashedPassword value object.
    """

    enterprise_id: uuid.UUID = field(default_factory=uuid.uuid4)
    email: Email = field(default_factory=lambda: Email(value="placeholder@example.com"))
    password: HashedPassword = field(
        default_factory=lambda: HashedPassword(value="$2b$12$placeholder")
    )
    full_name: str | None = None
    role: UserRole = UserRole.MEMBER
    last_login: datetime | None = None
    is_active: bool = True

    # ── Business methods ──────────────────────────────────────────────────────

    def authenticate(self, plaintext_password: str) -> bool:
        """
        Verify plaintext_password against stored hash.

        Returns False (does NOT raise) if password is wrong.
        Raises PolicyViolation if user account is inactive.
        """
        if not self.is_active:
            raise PolicyViolation(
                "User account is inactive. Contact your enterprise administrator.",
            )
        return self.password.verify(plaintext_password)

    def record_login(self) -> "UserLoggedIn":
        """Set last_login to now and return UserLoggedIn domain event."""
        self.last_login = datetime.now(tz=timezone.utc)
        self.touch()
        return UserLoggedIn(
            aggregate_id=self.id,
            event_type="UserLoggedIn",
            user_id=self.id,
            enterprise_id=self.enterprise_id,
        )

    def deactivate(self) -> None:
        """Deactivate user account."""
        self.is_active = False
        self.touch()


# ── Domain Events ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class UserLoggedIn(DomainEvent):
    user_id: uuid.UUID = field(default_factory=uuid.uuid4)
    enterprise_id: uuid.UUID = field(default_factory=uuid.uuid4)
