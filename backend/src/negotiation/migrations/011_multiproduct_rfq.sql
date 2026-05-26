-- Migration 011: Multi-product RFQ variant persistence
-- Adds all_products to rfq table and matched_rfq_variant to matches table

ALTER TABLE rfq ADD COLUMN IF NOT EXISTS all_products JSONB;
ALTER TABLE matches ADD COLUMN IF NOT EXISTS matched_rfq_variant JSONB;

COMMENT ON COLUMN rfq.all_products IS
    'All product names extracted from multi-product RFQ. Null for single-product.';
COMMENT ON COLUMN matches.matched_rfq_variant IS
    'The specific product variant (product, quantity, budget) this match was scored against.';
