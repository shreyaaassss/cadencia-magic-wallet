-- Migration 009: Add user_id scoping to agent_memory for per-user personalization
-- Phase 2A of DANP personalization implementation

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'agent_memory' AND column_name = 'user_id'
    ) THEN
        ALTER TABLE agent_memory ADD COLUMN user_id UUID REFERENCES users(id) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS ix_agent_memory_user_id ON agent_memory(tenant_id, user_id);
    END IF;
END $$;

COMMENT ON COLUMN agent_memory.user_id IS
    'Optional user-level scoping for per-user RAG context (in addition to tenant-level).';
