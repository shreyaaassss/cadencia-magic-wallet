-- Migration 008: Add intelligence fields to agent_profiles
-- Phase 2A of DANP personalization implementation

ALTER TABLE agent_profiles
    ADD COLUMN IF NOT EXISTS negotiation_intelligence JSONB,
    ADD COLUMN IF NOT EXISTS style_summary TEXT,
    ADD COLUMN IF NOT EXISTS vault_bytes_used BIGINT DEFAULT 0;

COMMENT ON COLUMN agent_profiles.negotiation_intelligence IS
    'Structured NLP-extracted intelligence: concession patterns, style classification, deal accelerators.';
COMMENT ON COLUMN agent_profiles.style_summary IS
    'Human-readable negotiation style description, updated after each session.';
COMMENT ON COLUMN agent_profiles.vault_bytes_used IS
    'Running counter of active embedding bytes used by this enterprise (for quota enforcement).';
