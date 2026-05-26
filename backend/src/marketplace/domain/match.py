# context.md §3 — zero framework imports in domain layer.

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from src.marketplace.domain.value_objects import MatchStatus, SimilarityScore
from src.shared.domain.base_entity import BaseEntity
from src.shared.domain.exceptions import ConflictError


@dataclass
class Match(BaseEntity):
    """Match linking an RFQ to a ranked seller."""

    rfq_id: uuid.UUID = field(default_factory=uuid.uuid4)
    seller_enterprise_id: uuid.UUID = field(default_factory=uuid.uuid4)
    similarity_score: SimilarityScore = field(
        default_factory=lambda: SimilarityScore(value=0.0)  # type: ignore[call-arg]
    )
    rank: int = 1
    status: MatchStatus = MatchStatus.PENDING
    matched_rfq_variant: dict | None = None  # Which product variant this match was scored on

    def select(self) -> None:
        """Transition: PENDING → SELECTED."""
        if self.status != MatchStatus.PENDING:
            raise ConflictError(
                f"Cannot select match in status {self.status.value}, expected PENDING."
            )
        self.status = MatchStatus.SELECTED
        self.touch()

    def reject(self) -> None:
        """Transition: PENDING → REJECTED."""
        if self.status != MatchStatus.PENDING:
            raise ConflictError(
                f"Cannot reject match in status {self.status.value}, expected PENDING."
            )
        self.status = MatchStatus.REJECTED
        self.touch()
