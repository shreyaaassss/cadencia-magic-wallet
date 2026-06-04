# context.md §7 — Domain Event Bus: all cross-domain communication via events.
# context.md §3 — zero framework imports in domain layer.

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

# Re-export events defined alongside their aggregates.
from src.settlement.domain.escrow import (  # noqa: F401
    EscrowDeployed,
    EscrowFrozen,
    EscrowFunded,
    EscrowRefunded,
    EscrowReleased,
    EscrowUnfrozen,
)
from src.shared.domain.events import DomainEvent


@dataclass(frozen=True)
class SessionAgreedStub(DomainEvent):
    """
    Phase Two stub representing the SessionAgreed event from negotiation/.

    Real wiring happens in Phase Four when NegotiationService is implemented.
    context.md §7: settlement receives SessionAgreed → triggers DeployEscrow.
    """

    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
    buyer_enterprise_id: uuid.UUID = field(default_factory=uuid.uuid4)
    seller_enterprise_id: uuid.UUID = field(default_factory=uuid.uuid4)
    buyer_algo_address: str = ""
    seller_algo_address: str = ""
    agreed_price_microalgo: int = 0
