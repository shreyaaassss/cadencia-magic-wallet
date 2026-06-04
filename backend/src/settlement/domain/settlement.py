# context.md §3 — Hexagonal Architecture: zero framework imports in domain layer.
# Settlement is an append-only record of a fund-release event.
# Created once, never mutated — immutable audit record of milestone releases.

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.settlement.domain.value_objects import MicroAlgo, TxId
from src.shared.domain.base_entity import BaseEntity


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass
class Settlement(BaseEntity):
    """
    Settlement milestone record (settlement bounded context).

    Records a single fund-release event within an escrow contract.
    Append-only: created once, never mutated.
    """

    escrow_id: uuid.UUID = field(default_factory=uuid.uuid4)
    milestone_index: int = 0
    amount: MicroAlgo = field(default_factory=lambda: MicroAlgo(value=0))
    tx_id: TxId = field(default_factory=lambda: TxId(value="A" * 52))
    oracle_confirmation: dict | None = None
    settled_at: datetime = field(default_factory=_utcnow)
