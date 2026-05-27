-- Migration 013: Add deal_quality_score to negotiation_sessions
-- Persists computed deal quality (ZOPA position + surplus breakdown) on agreement.

ALTER TABLE negotiation_sessions ADD COLUMN IF NOT EXISTS deal_quality_score JSONB;

COMMENT ON COLUMN negotiation_sessions.deal_quality_score IS
    'ZOPA-based deal quality on agreement: {score, buyer_surplus_inr, seller_surplus_inr, zopa_position_pct, agreed_price_inr}. Null for non-agreed sessions.';
