-- Migration 010: Create vault_metadata table for document quota tracking
-- Phase 2A/2C of DANP personalization implementation

CREATE TABLE IF NOT EXISTS vault_metadata (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    enterprise_id     UUID NOT NULL REFERENCES enterprises(id) ON DELETE CASCADE,
    user_id           UUID REFERENCES users(id) ON DELETE SET NULL,
    filename          TEXT NOT NULL,
    s3_key            TEXT NOT NULL,
    size_bytes        BIGINT NOT NULL,
    mime_type         TEXT,
    content_hash      TEXT NOT NULL,          -- SHA-256 for deduplication
    is_active         BOOLEAN DEFAULT FALSE,  -- TRUE = currently embedded in pgvector
    active_bytes_used BIGINT DEFAULT 0,       -- Bytes contributing to active quota
    embedding_count   INT DEFAULT 0,          -- Number of pgvector rows created
    last_retrieved_at TIMESTAMP WITH TIME ZONE,
    ingested_at       TIMESTAMP WITH TIME ZONE,
    created_at        TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_vault_metadata_enterprise ON vault_metadata(enterprise_id);
CREATE INDEX IF NOT EXISTS ix_vault_metadata_user       ON vault_metadata(user_id);
CREATE INDEX IF NOT EXISTS ix_vault_metadata_hash       ON vault_metadata(content_hash);
CREATE INDEX IF NOT EXISTS ix_vault_metadata_active     ON vault_metadata(enterprise_id, is_active);

COMMENT ON TABLE vault_metadata IS
    'Tracks uploaded documents: S3 storage (always) and pgvector embeddings (active docs only).';
COMMENT ON COLUMN vault_metadata.is_active IS
    'FALSE = stored in S3 only (free). TRUE = also embedded in pgvector (costs quota).';
COMMENT ON COLUMN vault_metadata.content_hash IS
    'SHA-256 of raw content for deduplication — identical documents share embeddings.';
