"""Add FK constraints on negotiation_sessions + audit hash chain trigger

Revision ID: 025
Revises: 024
Create Date: 2026-06-06

Adds referential integrity for negotiation_sessions.rfq_id and match_id
(were plain UUIDs with no FK — orphaned sessions possible).

Also adds a DB trigger on audit_entries to enforce hash chain integrity
at the database level, preventing direct SQL inserts from breaking the chain.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "025"
down_revision: Union[str, None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # FK: negotiation_sessions.rfq_id → rfqs.id
    # Use NOT VALID to avoid locking the table while validating existing rows,
    # then validate separately.
    op.execute("""
        ALTER TABLE negotiation_sessions
        ADD CONSTRAINT fk_negotiation_sessions_rfq_id
        FOREIGN KEY (rfq_id) REFERENCES rfqs(id) ON DELETE SET NULL
        NOT VALID
    """)
    op.execute("""
        ALTER TABLE negotiation_sessions
        VALIDATE CONSTRAINT fk_negotiation_sessions_rfq_id
    """)

    # FK: negotiation_sessions.match_id → matches.id
    op.execute("""
        ALTER TABLE negotiation_sessions
        ADD CONSTRAINT fk_negotiation_sessions_match_id
        FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE SET NULL
        NOT VALID
    """)
    op.execute("""
        ALTER TABLE negotiation_sessions
        VALIDATE CONSTRAINT fk_negotiation_sessions_match_id
    """)

    # Audit hash chain trigger — enforces prev_hash correctness on INSERT.
    op.execute("""
        CREATE OR REPLACE FUNCTION enforce_audit_hash_chain()
        RETURNS TRIGGER AS $$
        DECLARE
            expected_prev_hash TEXT;
        BEGIN
            -- Get the most recent entry_hash for this escrow
            SELECT entry_hash INTO expected_prev_hash
            FROM audit_entries
            WHERE escrow_id = NEW.escrow_id
            ORDER BY sequence_no DESC
            LIMIT 1;

            -- First entry for this escrow: prev_hash must be NULL or empty
            IF expected_prev_hash IS NULL THEN
                IF NEW.prev_hash IS NOT NULL AND NEW.prev_hash != '' THEN
                    RAISE EXCEPTION 'First audit entry for escrow must have NULL prev_hash';
                END IF;
            ELSE
                -- Subsequent entries: prev_hash must match the last entry_hash
                IF NEW.prev_hash IS DISTINCT FROM expected_prev_hash THEN
                    RAISE EXCEPTION 'Hash chain broken: expected prev_hash=%, got %',
                        expected_prev_hash, NEW.prev_hash;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        DROP TRIGGER IF EXISTS trg_enforce_audit_hash_chain ON audit_entries
    """)
    op.execute("""
        CREATE TRIGGER trg_enforce_audit_hash_chain
        BEFORE INSERT ON audit_entries
        FOR EACH ROW
        EXECUTE FUNCTION enforce_audit_hash_chain()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_enforce_audit_hash_chain ON audit_entries")
    op.execute("DROP FUNCTION IF EXISTS enforce_audit_hash_chain()")
    op.execute("ALTER TABLE negotiation_sessions DROP CONSTRAINT IF EXISTS fk_negotiation_sessions_match_id")
    op.execute("ALTER TABLE negotiation_sessions DROP CONSTRAINT IF EXISTS fk_negotiation_sessions_rfq_id")
