# 🧠 Cadencia — Agent Hyper-Personalization Feature Audit

> **What you're building**: Per-user secure vaults, NLP-parsed negotiation intelligence, conversation history in JSON, and a continuous self-updating agent profile loop.  
> **Tone**: Completely honest. No sugar-coating.

---

## First, The Honest Assessment You Asked For

**Is this going to make your code better and give you an outstanding MVP?**

**Partially yes, but you need to hear the hard truth first:**

### What's Already Built (You'll Be Surprised)

You have done **significantly more groundwork** than most early-stage MVPs have. Before writing a single line of new code for this feature, here's what's **already working** in your codebase:

| Component | Status | File |
|-----------|--------|------|
| Per-enterprise S3 vault with AES256 encryption | ✅ **Done** | `s3_vault.py` |
| Text chunking (512-token semantic splitting with overlap) | ✅ **Done** | `embedding_pipeline.py` |
| Gemini text-embedding-004 (1536-dim) pipeline | ✅ **Done** | `embedding_pipeline.py` |
| pgvector RAG storage with HNSW cosine similarity | ✅ **Done** | `models.py`, `repositories.py` |
| RAG retrieval injected into LLM system prompt | ✅ **Done** | `neutral_engine.py` (Layer 3) |
| Enterprise document ingestion API | ✅ **Done** | `personalization_service.py` |
| Per-enterprise `AgentProfile` with EMA learning | ✅ **Done** | `agent_profile.py` |
| Strategy weights updated after every session | ✅ **Done** | `agent_profile.update_after_session()` |
| Bayesian opponent belief persistence in Postgres | ✅ **Done** | `opponent_profiles` table |
| `agent_memory` table (pgvector, tenant-isolated) | ✅ **Done** | `AgentMemoryModel` |

**The bad news**: Most of these are **wired up but never fully exercised**. The RAG retrieval is called in `neutral_engine.py` but `PersonalizationService` is passed as `None` in the default `NeutralEngine` constructor — meaning zero tenants are currently getting RAG context injection. The embedding pipeline works but `GEMINI_API_KEY` is blank in your `.env`. The opponent profile DB table exists but `PostgresOpponentProfileRepository` is never used in `NeutralEngine` — it still uses the in-memory `_belief_cache`.

**So what you actually have is**: A very well-designed skeleton that's roughly 60-70% built, with the critical wiring missing.

---

## What Your Feature Actually Requires

Let me break it into its real parts so we don't overpromise anything.

```
Feature = 4 distinct sub-systems:

  1. Secure User Vault (Storage Layer)
     └── Upload UI + storage quota + doc management

  2. NLP Intelligence Extraction (Parsing Layer)
     └── Style/tone/strategy analysis from uploaded docs

  3. Conversation History Store (Memory Layer)
     └── Every negotiation round saved as structured JSON

  4. Continuous Learning Loop (Feedback Layer)
     └── Parsed intelligence updates agent profile after each session
```

---

## Sub-System 1: Secure User Vaults

### What's Already Built

Your `S3Vault` / MinIO implementation handles **enterprise-level** tenant isolation. Documents go to `raw/{tenant_id}/{filename}` inside `cadencia-agents-{prefix}` buckets with AES256 encryption.

### What's Missing

**Critical gap**: Your vault is scoped to **enterprises**, not **individual users**. You asked for per-user vaults — currently impossible because `AgentProfile` and `AgentMemoryModel` both use `enterprise_id`, not `user_id`. A company's 5 employees all share one profile.

**The storage quota**: You mentioned 512MB per user. That's roughly:
- ~500,000 words of plain text, OR
- ~25-50 average procurement PDF contracts

512MB is actually very generous for text. The real cost isn't disk space — it's the **embedding cost**. At 512-token chunks, 512MB of text = ~250,000 chunks × Gemini embedding API calls. At free tier, that's a problem. At prod rates, it's ~$10-15 per user for initial ingestion. **Budget for this.**

### Recommended Design

```
Storage Architecture:

  User Vault (per user_id):
    MinIO/S3: raw/{enterprise_id}/{user_id}/{filename}
    Quota: 512MB enforced via pre-upload size check
    
  Memory Index (per user_id):
    agent_memory table: add user_id column alongside enterprise_id
    Retrieval: WHERE enterprise_id = ? AND user_id = ?
```

**Use your existing Postgres + MinIO stack** — do NOT add Supabase Storage as a third storage system. You already have:
- MinIO (file storage) ✅  
- Postgres + pgvector (vector search) ✅  
- Redis (caching, rate limiting) ✅

Adding Supabase Storage would be a **fourth system** for solving the same problem. Avoid this at MVP stage.

---

## Sub-System 2: NLP Intelligence Extraction

### What's Currently There

Nothing for this specific task. The existing pipeline does:
1. Download doc from S3
2. Chunk text into 512-token pieces
3. Embed with Gemini
4. Store in pgvector

This is pure **semantic similarity retrieval** — it finds "similar past negotiation text" and injects it into the prompt. It does **NOT** analyze or extract structured intelligence (style, tone, strategy).

### What You're Proposing

Parse documents and extract **structured intelligence** like:
- "This user tends to anchor 20% below market rate"
- "This user uses collaborative language, rarely threatens walk-away"
- "This user always asks for payment terms before discussing price"

### Honest Assessment of This Specific Piece

This is **the hardest part of your entire feature** and the one most likely to disappoint you at MVP.

**Why it's hard:**
1. **Tone/style extraction from procurement docs is noisy**. A purchase order has no negotiation tone. A vendor RFQ template has no strategic signals. You need actual *back-and-forth negotiation transcripts* — email threads, WhatsApp screenshots, meeting notes — not just procurement documents.

2. **LLM-based style extraction is expensive and slow**. To extract "this user prefers collaborative over adversarial tactics," you need to pass the full document through an LLM with a structured extraction prompt. At 512MB per user, this is hundreds of LLM calls per user at ingestion time.

3. **The signal is weak at first**. A user who uploads 3 old contracts doesn't have enough data for meaningful style inference. You need at least 10-20 actual negotiation histories before patterns emerge.

### Recommended Approach (Pragmatic MVP)

**Two-phase extraction instead of big-bang NLP:**

**Phase 1 (Build now — realistic):**
Use Groq/Llama to extract a limited set of *structured signals* from each uploaded document:

```python
EXTRACTION_PROMPT = """
Analyze this procurement negotiation document and extract:
{
  "preferred_discount_range_pct": [min, max],  # e.g. [5, 15]
  "payment_terms_preference": "advance|net30|LC|flexible",
  "negotiation_style": "collaborative|assertive|analytical|competitive",
  "typical_concession_size_pct": number,  # average concession per round
  "common_terms_prioritized": ["quality", "delivery", "price", "warranty"],
  "walk_away_signals": ["phrases that indicate near-rejection"],
  "deal_accelerators": ["phrases that indicate readiness to close"]
}
Return null for any field you cannot determine with confidence.
"""
```

Store this as `negotiation_intelligence: JSONB` on `AgentProfile`.

**Phase 2 (After first 3 months of live negotiations):**
The *real* intelligence source is your own negotiation conversations — not uploaded docs. Once users complete 5+ sessions on Cadencia, you have ground truth. Mine that instead.

---

## Sub-System 3: Conversation History in JSON

### What's Already There

Your `offers` table stores every offer with:
- `round_number`, `proposer_role`, `price`, `confidence`, `reasoning`, `is_human_override`, `raw_llm_output`
- All linked to `negotiation_sessions` via foreign key

The `NegotiationSession` contains full `offers: list[Offer]` and all the metadata.

### What's Missing

**No denormalized JSON export** of the full conversation thread per session. Your data is properly normalized in relational tables (good for DB queries), but you need a flat JSON format for:
1. User-facing conversation history UI
2. Feeding back into the next NLP extraction cycle
3. RAG ingestion of past negotiation conversations

### Recommended Design

**Add a `conversation_transcript` JSONB column to `negotiation_sessions`:**

```sql
ALTER TABLE negotiation_sessions 
ADD COLUMN conversation_transcript JSONB;
```

```python
# Generated and stored when session reaches terminal state:
conversation_transcript = {
  "session_id": "uuid",
  "rfq_id": "uuid",
  "product": "Steel Rods",
  "quantity": 100,
  "outcome": "AGREED",
  "agreed_price": 450000,
  "rounds_taken": 7,
  "started_at": "2026-05-20T10:00:00Z",
  "completed_at": "2026-05-20T10:15:00Z",
  "buyer_enterprise_id": "uuid",
  "seller_enterprise_id": "uuid",
  "rounds": [
    {
      "round": 1,
      "role": "SELLER",
      "price": 520000,
      "reasoning": "Opening anchor at 10% above target.",
      "confidence": 0.85,
      "strategy_used": "STRONG_ANCHOR",
      "is_human": false
    },
    {
      "round": 2,
      "role": "BUYER",
      "price": 390000,
      "reasoning": "Responsive anchor below target.",
      "confidence": 0.78,
      "strategy_used": "STRONG_ANCHOR",
      "is_human": false
    }
    // ... all rounds
  ],
  "buyer_intelligence": {
    "flexibility_score": 0.65,
    "dominant_type": "strategic",
    "avg_concession_pct": 3.2
  },
  "seller_intelligence": {
    "flexibility_score": 0.45,
    "dominant_type": "boulware",
    "avg_concession_pct": 1.8
  }
}
```

This transcript is generated once at session completion and stored. It becomes the primary input for the continuous learning loop.

---

## Sub-System 4: Continuous Learning Loop

### What's Already There

`AgentProfile.update_after_session()` already runs an EMA update of:
- `win_rate` 
- `avg_rounds`
- `avg_deviation`

This is called in `NegotiationService._handle_agreement()` after every AGREED session.

### What's Missing

1. **The NLP intelligence extracted from docs is never fed back into the profile**
2. **The conversation transcript is never re-ingested as RAG memory** (this is the biggest missed opportunity)
3. **Strategy selection doesn't adapt based on learned opponent patterns** (you classify opponents per-session but don't persist cross-session learning per counterparty pair — `PostgresOpponentProfileRepository` exists but isn't wired in)
4. **The `concession_rate` in `StrategyWeights` is set at profile creation and never actually updated** — `update_after_session()` updates `win_rate`, `avg_rounds`, and `avg_deviation` but not `concession_rate`

### Recommended Continuous Learning Design

```
Trigger: Session reaches terminal state (AGREED/WALK_AWAY/etc.)

Step 1: Generate conversation_transcript JSON → store in negotiation_sessions
Step 2: Run NLP extraction on transcript → extract style signals
Step 3: Update AgentProfile:
         - EMA update (already done) ✅
         - Update concession_rate based on actual concession behavior ← missing
         - Update negotiation_intelligence JSONB ← missing
Step 4: Ingest transcript as new RAG memory chunk:
         - Chunk conversation transcript
         - Embed with Gemini
         - Store in agent_memory (tenant scoped)
Step 5: If user has opponent profile for this counterparty:
         - Update PostgresOpponentProfileRepository ← already exists, needs wiring
```

**Crucially**: Step 4 means every completed negotiation automatically becomes training data for the next one — without any user action. This is the compound value driver of your feature.

---

## Architecture Decision: Supabase vs Current Stack

> You asked: "Supabase or our current DB implementations (Redis + Postgres)?"

**Honest answer: Stick with your current stack.**

Here's why:

| Concern | Supabase | Your Current Stack |
|---------|----------|-------------------|
| File storage | Supabase Storage | MinIO (already set up) ✅ |
| Vector search | pgvector (via Supabase) | pgvector on your Postgres ✅ |
| Auth | Supabase Auth | Your own JWT RS256 ✅ |
| Row-level security | Supabase RLS | Enforced in repos ✅ |
| Realtime | Supabase Realtime | Your SSE implementation ✅ |
| Cost at 100 users | ~$25-50/month | Same Postgres, ~$0 extra |
| Operational overhead | Low (managed) | Medium (Docker) |

You'd be migrating to Supabase to get features you **already have**. The only genuine advantage of Supabase here is managed backups and their dashboard for debugging — not worth a migration at this stage.

**One valid Supabase use**: Their `pgvector` support is excellent and you're already using it. If you ever move to Supabase Cloud (you have cloud credentials in your `.env`), the migration is trivial because your schema is already compatible.

---

## Storage Quota Implementation

512MB per user needs to be enforced at the upload endpoint:

```python
# In the document upload handler:
MAX_VAULT_SIZE_BYTES = 512 * 1024 * 1024  # 512MB

async def upload_document(tenant_id, user_id, file_content, filename):
    # Check current usage
    current_usage = await vault_repo.get_total_size_bytes(tenant_id, user_id)
    if current_usage + len(file_content) > MAX_VAULT_SIZE_BYTES:
        raise QuotaExceededError(
            f"Vault quota exceeded. "
            f"Current: {current_usage // (1024*1024)}MB / 512MB. "
            f"File size: {len(file_content) // (1024*1024)}MB"
        )
    # Proceed with upload
    await s3_vault.store_document(tenant_id, filename, file_content)
```

Track cumulative size in a `vault_metadata` table (per enterprise/user + total_bytes_used). S3 `list_objects_v2` with size metadata works but is slow for quota enforcement — a Postgres counter is faster.

---

## What This Feature Will Actually Look Like in Practice

**For a buyer who has used Cadencia for 6 months with 20 completed sessions:**

Their system prompt injection becomes:

```
=== YOUR NEGOTIATION INTELLIGENCE (from your history) ===
Based on your past 20 negotiations:
- You typically close at 8-12% below your opening offer
- Your average deal takes 6 rounds
- You tend to use assertive early anchoring, then softer language after round 4
- Your highest win rate is with "STEEL" commodity suppliers (85%)
- You have negotiated with [Seller X] before: they responded well to
  deadline-urgency framing and accepted deals at 7% above their floor

=== RELEVANT PAST NEGOTIATION CONTEXT ===
1. [Round 4-7 from Jan session] "When supplier pushed back on delivery timeline,
   moved to consolidated payment term which closed the deal."
2. [Round 2 from March session] "Steel Rods, 50MT, ₹4.8L deal — seller opened
   at ₹5.5L, you anchored at ₹4.2L and converged in 5 rounds."
```

**That is genuinely differentiated** — no competing B2B platform has per-user negotiation intelligence at this granularity at the SME/MSME level.

---

## Will This Give You an Outstanding MVP? Honest Verdict

### The Good

✅ **Technically feasible** — 70% of the infrastructure already exists  
✅ **Genuinely differentiated** — no B2B procurement platform does this at the MSME level  
✅ **Compound value** — gets better with every session automatically  
✅ **Low marginal cost** — once ingestion pipeline is built, per-session learning is free  
✅ **Your architecture is well-designed** — hexagonal arch makes adding this clean

### The Realistic Cautions

⚠️ **The NLP style-extraction from uploaded docs is weaker than it sounds** — procurement PDFs are not negotiation transcripts. The real intelligence comes from *Cadencia sessions themselves*, not uploads. The upload feature is valuable for onboarding, but don't expect 10 uploaded contracts to produce dramatically better AI behavior immediately.

⚠️ **You need to fix the critical bugs from Audit #1 first** — especially BUG-01 (the key rotation break issue). A failing negotiation engine with great personalization is still a failing negotiation engine.

⚠️ **Gemini embeddings require a working `GEMINI_API_KEY`** — your `.env` has this blank. Without it, the entire RAG pipeline falls back to stub embeddings (SHA256 hash vectors) which produce meaningless similarity results. This is silently broken right now.

⚠️ **Per-user vs per-enterprise scoping is a schema migration** — the entire current system uses `enterprise_id`. Adding `user_id` scoping means a migration on `agent_memory`, `agent_profiles`, and S3 paths. Not hard, but it's not a minor change.

⚠️ **512MB quota feels large but the embedding cost is real** — budget for Gemini API costs during onboarding. Consider limiting initial ingestion to 50MB until you have paid customers.

### Priority Recommendation

Build this in this exact order to maximize MVP quality:

```
Week 1: Fix the critical bugs (BUG-01, BUG-09, BUG-04 from Audit #1)
         Wire the existing RAG pipeline (fix GEMINI_API_KEY, wire personalization_service)
         
Week 2: Add conversation_transcript JSON storage at session completion
         Add transcript re-ingestion as RAG memory (auto-learning from own sessions)
         
Week 3: Build the document upload UI + 512MB quota enforcement
         Add NLP intelligence extraction (style/tone analysis) as background job
         
Week 4: Wire PostgresOpponentProfileRepository to NeutralEngine
         Update concession_rate in the EMA learning loop
         Add per-user scoping alongside enterprise_id
```

---

## Full Implementation Plan

### New Database Schema

```sql
-- 1. Add conversation transcript to sessions
ALTER TABLE negotiation_sessions 
ADD COLUMN conversation_transcript JSONB;

-- 2. Add NLP intelligence to agent profiles
ALTER TABLE agent_profiles
ADD COLUMN negotiation_intelligence JSONB,
ADD COLUMN style_summary TEXT,
ADD COLUMN vault_bytes_used BIGINT DEFAULT 0;

-- 3. Add user_id scoping to agent_memory
ALTER TABLE agent_memory
ADD COLUMN user_id UUID REFERENCES users(id);

CREATE INDEX ix_agent_memory_user_id ON agent_memory(tenant_id, user_id);

-- 4. Vault metadata table for quota tracking
CREATE TABLE vault_metadata (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    enterprise_id UUID NOT NULL REFERENCES enterprises(id),
    user_id UUID REFERENCES users(id),
    filename TEXT NOT NULL,
    s3_key TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    mime_type TEXT,
    ingested_at TIMESTAMP WITH TIME ZONE,
    embedding_count INT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX ix_vault_metadata_enterprise ON vault_metadata(enterprise_id);
CREATE INDEX ix_vault_metadata_user ON vault_metadata(user_id);
```

### New Service: `NegotiationIntelligenceService`

```python
class NegotiationIntelligenceService:
    """
    Extracts negotiation intelligence from:
    1. Uploaded user documents (at ingestion time)
    2. Completed negotiation transcripts (at session completion)
    
    Updates AgentProfile.negotiation_intelligence JSONB.
    """
    
    async def extract_from_document(self, content: str, tenant_id: UUID) -> dict:
        """LLM extraction of style signals from a procurement document."""
        # Call Groq with extraction prompt
        # Return structured intelligence dict
        
    async def extract_from_transcript(self, transcript: dict) -> dict:
        """Extract behavioral signals from a completed negotiation."""
        offers = transcript["rounds"]
        # Compute: avg_concession_pct, opening_anchor_pct_below_budget,
        #          rounds_to_close, acceptance_trigger_signals
        # These are computable WITHOUT an LLM — pure math from the offer sequence
        
    async def update_profile_intelligence(
        self, profile: AgentProfile, new_signals: dict
    ) -> AgentProfile:
        """EMA-merge new signals into existing intelligence."""
```

### Updated `PersonalizationBuilder.build()` — New Intelligence Section

```python
# Add to PersonalizationBuilder:
if profile.negotiation_intelligence:
    intel = profile.negotiation_intelligence
    style = intel.get("negotiation_style", "balanced")
    avg_concession = intel.get("typical_concession_size_pct", 5)
    win_context = intel.get("best_win_conditions", [])
    
    intelligence_section = (
        f"=== YOUR NEGOTIATION INTELLIGENCE ===\n"
        f"Style profile: {style}\n"
        f"Your typical concession per round: {avg_concession}%\n"
        f"Conditions where you close deals fastest: {', '.join(win_context[:3])}\n"
        f"Your historical avg rounds to agreement: {profile.strategy_weights.avg_rounds:.1f}\n"
        f"Your win rate: {profile.strategy_weights.win_rate:.0%}\n"
    )
```

### Auto-Ingestion Trigger in `NegotiationService._handle_agreement()`

```python
async def _handle_agreement(self, session, offer, buyer_profile, seller_profile):
    # ... existing code ...
    
    # NEW: Generate and store conversation transcript
    transcript = self._build_conversation_transcript(session, offer)
    await self.session_repo.save_transcript(session.id, transcript)
    
    # NEW: Async background job — don't block the response
    asyncio.create_task(
        self._ingest_transcript_as_memory(
            session=session,
            transcript=transcript,
            buyer_profile=buyer_profile,
            seller_profile=seller_profile,
        )
    )

async def _ingest_transcript_as_memory(self, session, transcript, buyer_profile, seller_profile):
    """Background: embed transcript → store in agent_memory for future RAG retrieval."""
    transcript_text = self._transcript_to_text(transcript)
    
    # Ingest for both buyer and seller separately
    for enterprise_id, role in [
        (session.buyer_enterprise_id, "buyer"),
        (session.seller_enterprise_id, "seller"),
    ]:
        cmd = IngestMemoryCommand(
            tenant_id=enterprise_id,
            role=role,
            content=transcript_text,
        )
        await self.personalization_service.ingest_text_directly(cmd)
```

---

## Summary: What You're Building vs What You Have

```
WHAT YOU PROPOSED          WHAT EXISTS     WHAT TO BUILD
─────────────────────────────────────────────────────────
User secure vaults          60% done        Quota enforcement + user_id scoping
Upload UI                   0% done         Build new upload endpoints + frontend
NLP style parsing           0% done         LLM extraction prompt + pipeline
Conversation JSON storage   20% done        Add JSONB column + build transcript generator
Auto-update on completion   40% done        Wire existing EMA + add transcript ingestion
RAG injection in prompt     90% done        Just fix the GEMINI_API_KEY + wiring
```

**Total new code needed**: ~800-1200 lines of Python + ~3 new DB migrations + upload UI  
**Reuse of existing infrastructure**: ~70%  
**Timeline realistic for 1 developer**: 3-4 weeks for a solid v1

---

> **Bottom line**: This feature is worth building. Your architecture is ready for it. But fix your engine's bugs first, then wire what's already built, then add the new NLP layer on top. Do not start fresh — you'd be throwing away excellent existing work.
