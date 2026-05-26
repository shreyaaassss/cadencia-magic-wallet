-- Migration 007: Add conversation_transcript to negotiation_sessions
-- Phase 2A of DANP personalization implementation

ALTER TABLE negotiation_sessions
    ADD COLUMN IF NOT EXISTS conversation_transcript JSONB;

COMMENT ON COLUMN negotiation_sessions.conversation_transcript IS
    'Structured JSON transcript of all offers/rounds. Ingested into pgvector after session completion.';
