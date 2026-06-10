# Seller Embedding Schema — Cadencia Marketplace

## Overview
Each seller gets a 384-dimensional vector embedding (Gemini `text-embedding-004`) stored in the `capability_profiles.embedding` column (pgvector). These embeddings power RFQ-to-seller matching via cosine similarity search.

## Embedding Text Construction
The embedding is generated from a concatenation of seller metadata:

```
{profile_text} {product_categories} {geography_scope} {industry_vertical} {catalogue_items}
```

### Fields used (in order):

| Field | Source Table | Example |
|-------|-------------|---------|
| `profile_text` | `capability_profiles` | "Morbi ceramic cluster vitrified tile manufacturer..." |
| `product_categories` | `capability_profiles.commodities` | "Vitrified Tiles Ceramic Wall Tiles Porcelain Tiles" |
| `geography_scope` | `capability_profiles.geographies_served` | "PAN_INDIA" |
| `industry_vertical` | `capability_profiles.industry_vertical` | "Building Materials & Ceramics" |
| Catalogue items | `catalogue_items` (joined) | "600x600 Vitrified Floor Tile \| 6907 \| Building Materials \| GVT Glossy" |

### Catalogue item format per item:
```
{product_name} | {hsn_code} | {product_category} | {grade} | {specification_text[:200]}
```

## Embedding Generation

### Automatic (on profile creation/update)
The backend calls `_recompute_embedding_standalone()` in the marketplace service when:
- A capability profile is created or updated
- A catalogue item is added, updated, or deleted

### Manual re-embedding
```bash
cd backend/
GEMINI_API_KEY=<key> python scripts/reembed_sellers.py
```

## Vector Search (RFQ Matching)
When a buyer submits an RFQ:
1. RFQ text is embedded using the same Gemini model
2. Cosine similarity search against `capability_profiles.embedding`
3. Top-K sellers returned as matches, ranked by composite score:
   - `semantic_score` — cosine similarity (primary signal)
   - `delivery_feasibility_score` — lead time + distance
   - `capacity_score` — MOQ and capacity fit
   - `price_score` — budget alignment
   - `proximity_score` — geographic distance

## Industry-Specific Embedding Signals

Each industry has domain-specific terms that improve matching:

| Industry | Key terms in profile_text |
|----------|--------------------------|
| Textiles | GSM, thread count, OEKO-TEX, loom type, weave pattern |
| Chemicals | purity %, CAS number, REACH, GHS, concentration |
| Pharmaceuticals | GMP, USP/IP/BP grade, FDA, WHO PQ, batch size |
| Auto Components | IATF 16949, OEM tier, die cast, forging, tolerance |
| Steel & Metals | IS grade, BIS, tensile strength, chemistry, HRC |
| Food Processing | FSSAI, Brix, HACCP, BRC, shelf life, cold chain |
| Electronics | BIS ISI, IPC class, UL, CE, FCC, IP rating |
| Plastics & Rubber | MFI, FDA grade, shore hardness, mould tonnage |
| Building Materials | IS code, load bearing, water absorption, glaze |
| Industrial Machinery | CNC, spindle speed, HP/KW, Fanuc/Siemens, precision |

## Database Schema

```sql
-- capability_profiles table (pgvector)
CREATE TABLE capability_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    enterprise_id UUID UNIQUE REFERENCES enterprises(id) ON DELETE CASCADE,
    commodities TEXT[],
    hsn_codes TEXT[],
    min_order_value FLOAT,
    max_order_value FLOAT,
    industry_vertical VARCHAR(200),
    geographies_served TEXT[],
    lead_time_days INTEGER,
    certifications TEXT[],
    profile_text TEXT,
    embedding VECTOR(1536),          -- stores 384-dim Gemini embeddings
    embedding_status VARCHAR(20) DEFAULT 'OUTDATED',
    embedding_version INTEGER DEFAULT 0,
    last_embedded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- IVFFlat index for cosine similarity
CREATE INDEX idx_capability_profiles_embedding
    ON capability_profiles
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);
```
