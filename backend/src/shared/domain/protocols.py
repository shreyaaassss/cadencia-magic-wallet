# context.md §3 — Shared domain protocols: zero framework imports.
# These Protocols are cross-context — any bounded context may import from here.
# context.md §7: IEnterpriseReader enables compliance to read enterprise data
#   without violating hexagonal boundaries (identity/ domain not imported directly).

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# ── EnterpriseSnapshot ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EnterpriseSnapshot:
    """
    Read-only projection of enterprise data needed by compliance.

    Deliberately minimal — compliance never needs full enterprise aggregate.
    Populated by IEnterpriseReader implementations in infrastructure.
    """

    enterprise_id: uuid.UUID
    name: str
    pan: str           # 10-char Indian PAN (e.g., AABCP1234C)
    gstin: str         # 15-char GSTIN (e.g., 27AABCP1234C1Z5)
    state_code: str    # 2-digit GST state code (e.g., "27" = Maharashtra)


# ── IMerkleService ────────────────────────────────────────────────────────────


@runtime_checkable
class IMerkleService(Protocol):
    """
    SHA-256 binary Merkle tree service.

    Returns raw hex strings — callers wrap in domain value objects as needed.
    Shared across settlement/ and compliance/ contexts.
    """

    def compute_root(self, entries: list[str]) -> str:
        """
        Compute Merkle root of entries.

        Returns 64-char hex string. Raises ValidationError if entries empty.
        """
        ...

    def generate_proof(self, entries: list[str], index: int) -> list[str]:
        """
        Generate inclusion proof for entries[index].

        Each element prefixed "L:" or "R:" (sibling direction).
        """
        ...

    def verify_proof(
        self, root: str, entry: str, proof: list[str], index: int
    ) -> bool:
        """Verify inclusion proof against root."""
        ...


# ── IEnterpriseReader ─────────────────────────────────────────────────────────


@runtime_checkable
class IEnterpriseReader(Protocol):
    """
    Read-only cross-domain port for compliance to fetch enterprise data.

    Implemented in compliance/infrastructure/ by querying the enterprises table
    directly (modular monolith — same DB, read-only).

    Never import identity domain directly: that violates hexagonal rules.
    """

    async def get_snapshot(
        self, enterprise_id: uuid.UUID
    ) -> EnterpriseSnapshot | None:
        """Return snapshot or None if enterprise not found."""
        ...
