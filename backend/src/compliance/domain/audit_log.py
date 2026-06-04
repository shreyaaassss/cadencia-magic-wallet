# context.md §3 — Hexagonal Architecture: zero framework imports in domain layer.
# Append-only SHA-256 hash-chained audit log.
# context.md §1: 7-year retention, tamper-evident, Merkle root anchored on-chain.

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.compliance.domain.value_objects import GENESIS_HASH, HashValue, SequenceNumber
from src.shared.domain.base_entity import BaseEntity
from src.shared.domain.events import DomainEvent


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# ── AuditHasher ───────────────────────────────────────────────────────────────


class AuditHasher:
    """
    Computes the hash of a single audit entry.

    context.md §1: SHA-256 hash-chained audit log — each entry hashes
    its own content PLUS the previous entry's hash (prev_hash).

    Uses stdlib hashlib only (acceptable for domain security primitive).
    """

    SEPARATOR = "|"

    @staticmethod
    def compute(prev_hash: str, event_type: str, payload_json: str) -> str:
        """
        Return SHA-256 hex digest of: prev_hash|event_type|payload_json
        """
        content = AuditHasher.SEPARATOR.join([prev_hash, event_type, payload_json])
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def verify(entry: "AuditEntry") -> bool:
        """
        Re-compute entry_hash from fields and compare to stored hash.
        Returns True if entry is internally consistent.
        """
        expected = AuditHasher.compute(
            prev_hash=entry.prev_hash.value,
            event_type=entry.event_type,
            payload_json=entry.payload_json,
        )
        return entry.entry_hash.value == expected


# ── AuditEntry Aggregate ──────────────────────────────────────────────────────


@dataclass
class AuditEntry(BaseEntity):
    """
    Single entry in the append-only hash-chained audit log.

    IMMUTABLE AFTER CREATION — do not mutate fields post-save.

    Chain integrity:
        entry_hash = SHA-256(prev_hash | event_type | payload_json)
        For the first entry: prev_hash = GENESIS_HASH ("0" * 64)

    context.md §1: Minimum 7-year retention. Append-only.
    """

    escrow_id: uuid.UUID = field(default_factory=uuid.uuid4)
    sequence_no: SequenceNumber = field(default_factory=lambda: SequenceNumber(value=0))
    event_type: str = ""
    payload_json: str = "{}"
    prev_hash: HashValue = field(default_factory=lambda: HashValue(value=GENESIS_HASH))
    entry_hash: HashValue = field(default_factory=lambda: HashValue(value=GENESIS_HASH))

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        escrow_id: uuid.UUID,
        sequence_no: int,
        event_type: str,
        payload: dict,
        prev_hash: str,
    ) -> "AuditEntry":
        """
        Create a new AuditEntry and compute its entry_hash.

        Args:
            escrow_id:    The escrow this audit entry belongs to.
            sequence_no:  Monotonically increasing per escrow (starts at 0).
            event_type:   Name of the domain event (e.g., "EscrowFunded").
            payload:      Dict of event payload — serialised to compact JSON.
            prev_hash:    entry_hash of the previous entry; GENESIS_HASH for first.
        """
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        entry_hash = AuditHasher.compute(
            prev_hash=prev_hash,
            event_type=event_type,
            payload_json=payload_json,
        )
        return cls(
            escrow_id=escrow_id,
            sequence_no=SequenceNumber(value=sequence_no),
            event_type=event_type,
            payload_json=payload_json,
            prev_hash=HashValue(value=prev_hash),
            entry_hash=HashValue(value=entry_hash),
        )

    # ── Domain Events ─────────────────────────────────────────────────────────

    def emit_appended(self) -> "AuditEntryAppended":
        return AuditEntryAppended(
            aggregate_id=self.id,
            event_type="AuditEntryAppended",
            escrow_id=self.escrow_id,
            sequence_no=self.sequence_no.value,
            audit_event_type=self.event_type,
            entry_hash=self.entry_hash.value,
        )


# ── Audit Chain Verifier ──────────────────────────────────────────────────────


class AuditChainVerifier:
    """
    Verifies hash chain integrity for all entries of an escrow.

    Used by ComplianceService.verify_audit_chain().
    """

    @staticmethod
    def verify(entries: list[AuditEntry]) -> tuple[bool, int | None]:
        """
        Verify that entries form a valid hash chain.

        Returns (is_valid, first_invalid_sequence_no).
        Returns (True, None) if chain is valid.
        """
        if not entries:
            return True, None

        # Sort by sequence_no ascending
        sorted_entries = sorted(entries, key=lambda e: e.sequence_no.value)

        expected_prev = GENESIS_HASH
        for entry in sorted_entries:
            # 1. Check internal hash consistency
            if not AuditHasher.verify(entry):
                return False, entry.sequence_no.value

            # 2. Check chain linkage
            if entry.prev_hash.value != expected_prev:
                return False, entry.sequence_no.value

            expected_prev = entry.entry_hash.value

        return True, None


# ── Domain Events ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AuditEntryAppended(DomainEvent):
    escrow_id: uuid.UUID = field(default_factory=uuid.uuid4)
    sequence_no: int = 0
    audit_event_type: str = ""
    entry_hash: str = ""
