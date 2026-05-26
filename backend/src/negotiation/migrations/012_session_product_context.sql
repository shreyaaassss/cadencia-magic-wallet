-- Migration 012: Add product_context to negotiation_sessions
-- Enables per-product negotiation from multi-product RFQs (camera + tripod + lens)
-- Each session stores which product/budget it should negotiate for

ALTER TABLE negotiation_sessions
    ADD COLUMN IF NOT EXISTS product_context JSONB;

COMMENT ON COLUMN negotiation_sessions.product_context IS
    'Per-product context override for multi-product RFQs. When set, the negotiation
     engine uses this product/budget instead of the RFQ primary parsed_fields.
     Structure: {product, quantity, budget_max, budget_min, budget_per_unit, hsn_code}';
