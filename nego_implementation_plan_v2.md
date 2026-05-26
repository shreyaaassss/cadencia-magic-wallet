# DANP Negotiation Engine — Master Implementation Plan v3

> **Source Documents:**
> - [New Architecture Audit](file:///C:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/negotiation_engine_audit_new.md) — 1,158-line comprehensive technical audit (§1–§21)
> - [Improvement Report v2](file:///C:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/negotiation_engine_improvement_report_v2.md) — DIAG-01→03, IMP-01→05, PERS-01→04, ADJ-01→05, ML-01→03
> - [Personalization Audit](file:///C:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/personalization_feature_audit.md) — RAG pipeline, intelligence extraction, profile learning gaps, vault design, quota enforcement
>
> **Decisions Confirmed:**
> - Q1 (GEMINI_API_KEY): ✅ Configured — Gemini embeddings will work, no stub fallback
> - Q2 (LLM provider): Deferred — will decide Claude/GPT separately. No code change needed now.
> - Q3 (Pre-Analysis cost): Use a **separate lightweight LLM** (e.g., Groq/Llama-3.1-8B at temperature=0.0) for the analysis call, frontier model only for main dialogue generation
> - Q4 (DB migrations): ✅ Alembic migration files will be generated
> - Q5 (Leaky abstraction): Add proper repository methods, do not access `_session` directly
>
> **Goal:** Execute every actionable upgrade in logical dependency order. Nothing is skipped.

---

## What's Already Implemented (No Work Needed)

These are confirmed **present and working** in the current codebase per the new audit §16–§17:

### Bug Fixes (All 10 Applied)

| Bug | Description | Status |
|-----|-------------|--------|
| BUG-01 | `break` → `continue` in LLM retry loop | ✅ Fixed |
| BUG-02 | Fragile walrus-operator key collection | ✅ Fixed |
| BUG-03 | `_get_logistics_context_async()` implemented | ✅ Fixed |
| BUG-04 | Agreement price now uses `max(buyer, seller)` | ✅ Fixed |
| BUG-06 | Stall detection uses `Decimal("0.002")` | ✅ Fixed |
| BUG-08 | Human override determines role from enterprise_id | ✅ Fixed |
| BUG-11 | Inter-turn delay in run-auto loop | ✅ Fixed |
| BUG-12 | Bayesian beliefs persisted to JSONB | ✅ Fixed |
| BUG-13 | `validate_raw_envelope()` now called | ✅ Fixed |
| BUG-14 | Gemini base_url corrected | ✅ Fixed |

### Improvements (8/8 Implemented)

| # | Feature | Status |
|---|---------|--------|
| #1 | Hard-bind LLM to ±3% price band | ✅ |
| #2 | 4-tier catalogue selection | ✅ |
| #3 | Dynamic confidence scoring (40/40/20 blend) | ✅ |
| #4 | Reciprocity ratio in adaptive concession | ✅ |
| #5 | Two-phase stall recovery with unfreeze | ✅ |
| #6 | ZOPA-midpoint settlement (60/40 weighting) | ✅ |
| #7 | Deal quality score (buyer_share/surplus) | ✅ |
| #8 | Psychological price rounding (progress-based quanta) | ✅ |

---

## What Still Needs To Be Done

Cross-referenced from **all three source documents** + the **15 Known Gaps** in audit §20.

---

## Phase 0: Critical Diagnostic Fixes

*These fix root causes of poor output quality. Must be done before any new features.*

---

### 0A. Wire PersonalizationService into NeutralEngine (DIAG-02 + Personalization Audit)

> [!IMPORTANT]
> The RAG pipeline is 90% built (S3 → chunk → embed → pgvector → retrieve → inject). But the **last-mile DI wiring is broken**: `PersonalizationService` is passed as `None` in the dependency container, meaning **zero tenants get RAG context injection**. The LLM approaches every round as a cold blank-slate problem. This is the single biggest quality fix.

#### [MODIFY] [dependencies.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/api/dependencies.py)

**Current state (line 48–52):**
```python
neutral_engine = NeutralEngine(
    agent_driver=agent_driver,
    personalization_builder=PersonalizationBuilder(),
    sse_publisher=sse_pub,
)
```

**Changes:**
1. Import and instantiate `PersonalizationService` with all 5 dependencies:
   - `S3TenantVault` (from `infrastructure/s3_vault.py`)
   - `PostgresAgentMemoryRepository` (from `infrastructure/repositories.py`)
   - `GeminiEmbedder` or `StubEmbedder` (from `infrastructure/embedding_pipeline.py`, gated by `GEMINI_API_KEY` presence)
   - `TextChunker` (from `infrastructure/embedding_pipeline.py`)
   - `SqlAlchemyUnitOfWork` (already imported)
2. Pass `personalization_service` to `NeutralEngine` constructor
3. Also wire `PostgresOpponentProfileRepository` for cross-session belief persistence

**Verification:** After this change, structlog should show `rag_context_injected` events with actual chunk content (not empty lists).

---

### 0B. Audit Valuation Math for Realistic Anchors (DIAG-03)

> [!WARNING]
> DIAG-03 flags that if valuation math produces an absurdly aggressive anchor (e.g., 40% below market rate), the LLM is forced to defend an insulting price, guaranteeing impasse. This is a **configuration audit + diagnostic logging** addition, not a code rewrite.

#### [MODIFY] [neutral_engine.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/infrastructure/neutral_engine.py)

Add **valuation sanity checks** with structured log warnings at the end of `_compute_valuation()`:

```python
# Sanity check: opening anchor should not be more than 35% away from opponent's likely range
if is_buyer:
    max_gap = val.target_price * Decimal("0.35")
    if catalogue_price and abs(val.target_price - catalogue_price) > max_gap:
        log.warning(
            "valuation_extreme_anchor",
            role="buyer",
            target=str(val.target_price),
            catalogue=str(catalogue_price),
            gap_pct=float(abs(val.target_price - catalogue_price) / catalogue_price * 100),
        )
```

This surfaces misconfigured `budget_max` / `margin_floor` values via logs before they ruin negotiations.

---

### 0C. Fix concession_rate Never Updating (Personalization Audit + Improvement Report)

> [!WARNING]
> `AgentProfile.update_after_session()` EMA-updates `win_rate`, `avg_rounds`, `avg_deviation` — but **never touches `concession_rate`** (audit §15). This means the strategy engine reads a stale default value forever.

#### [MODIFY] [agent_profile.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/domain/agent_profile.py)

In `update_after_session()` (line 55–97), after computing `new_avg_deviation`:

```python
# Compute actual concession behavior from this session
if session_agreed and final_price is not None and budget_ceiling > Decimal("0"):
    # How much we conceded from budget (buyer) or toward budget (seller)
    actual_concession = float(abs(final_price - budget_ceiling) / budget_ceiling)
    new_concession_rate = w.concession_rate * (1 - alpha) + actual_concession * alpha
else:
    new_concession_rate = w.concession_rate

# Use new_concession_rate in the StrategyWeights rebuild
```

Update the `StrategyWeights` constructor call to pass `concession_rate=new_concession_rate`.

---

### 0C. Remove Dead Sync `_get_logistics_context()` (Audit §20, Gap #3)

> The sync method always returns `None` and confusingly coexists with the working `_get_logistics_context_async()`. Dead code creates maintenance burden and confusion.

#### [MODIFY] [neutral_engine.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/infrastructure/neutral_engine.py)

- **Delete** the sync `_get_logistics_context()` method (lines ~1246–1265)
- Update any call sites to use `_get_logistics_context_async()` instead
- Verify no other file imports or references the sync version

---

### 0D. Fix Stall Detection Threshold Sensitivity (Audit §20, Gap #7)

> 0.2% price change is treated as "no concession." For ₹10Cr+ deals, 0.2% = ₹2L, which IS a meaningful concession. The threshold should be absolute-value-aware.

#### [MODIFY] [neutral_engine.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/infrastructure/neutral_engine.py)

In `_track_concession()` (line ~1198–1224), add dual-threshold logic:

```python
# Percentage threshold (existing)
pct_change = abs(new_price - last_price) / last_price

# Absolute threshold (new) — ₹5,000 minimum movement is always meaningful
abs_change = abs(new_price - last_price)
MIN_ABSOLUTE_CONCESSION = Decimal("5000")  # ₹5K for Indian B2B context

if pct_change < Decimal("0.002") and abs_change < MIN_ABSOLUTE_CONCESSION:
    session.record_no_concession()  # Neither threshold met → stall
else:
    session.reset_stall_counter()   # Either threshold met → concession
```

---

### 0E. Fix Schema Counter Not Resetting on Stall Recovery (Audit §20, Gap #15)

> If an agent has 2 schema failures and then stalls, the schema counter persists through stall recovery, leaving the session one failure away from `POLICY_BREACH`. This is a silent trap.

#### [MODIFY] [neutral_engine.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/infrastructure/neutral_engine.py)

In the stall recovery block (line ~787–817), after the unfreeze move:
```python
session.stall_recovery_attempted = True
session.reset_stall_counter()
session.schema_failure_count = 0  # ← ADD THIS: clean slate after recovery
```

---

### 0F. Fix TIT_FOR_TAT Modifier Hardcoded (Audit §20, Gap #8)

> `modifier=Decimal("0.85")` is hardcoded for the cooperative TIT_FOR_TAT branch. It should use the profile's `strategy_weights.concession_rate` for per-enterprise tuning.

#### [MODIFY] [neutral_engine.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/infrastructure/neutral_engine.py)

Where `select_strategy()` is called, derive the tit-for-tat modifier from the current agent's profile:

```python
tft_modifier = Decimal(str(min(0.95, max(0.60, profile.strategy_weights.concession_rate))))
```

Pass this into `select_strategy()` or apply it when TIT_FOR_TAT is returned.

#### [MODIFY] [strategy.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/domain/strategy.py)

Add `tft_modifier` parameter to `select_strategy()` signature (default `Decimal("0.85")` for backward compat). Use it in the `opponent_flexibility > 0.7` branch instead of the hardcoded value.

---

### 0H. Fix Leaky Repository Abstraction (Audit §20, Gap #2)

> `_load_rfq_and_catalogue()` in services.py directly accesses `session_repo._session` — bypassing the repository interface. Add proper repository methods instead.

#### [MODIFY] [repositories.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/infrastructure/repositories.py)

Add proper methods to `PostgresSessionRepository`:
```python
async def get_rfq_parsed_fields(self, rfq_id: UUID) -> dict | None: ...
async def get_catalogue_item_by_priority(self, seller_id: UUID, ...) -> CatalogueItem | None: ...
```

#### [MODIFY] [services.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/application/services.py)

Replace all `session_repo._session` accesses in `_load_rfq_and_catalogue()` with calls to the new repository methods.

---

### 0G. Fix max_tokens Inconsistency (Audit §20, Gap #12)

> `get_agent_driver()` factory sets `max_tokens=2048` but `LLMAgentDriver.__init__` defaults to `512`. The factory is the production path so this is harmless, but confusing.

#### [MODIFY] [llm_agent_driver.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/infrastructure/llm_agent_driver.py)

Change the `__init__` default from `512` to `2048` to match the factory, eliminating the inconsistency.

---

## Phase 1: Zero-Data SOTA (MVP Must-Haves)

*No historical data required. Relies on in-session reasoning and prompt engineering.*

---

### 1A. Structured Pre-Negotiation Analysis (IMP-01)

> [!IMPORTANT]
> The #1 ranked agent in MIT's 180,098 AI negotiations study used a mandatory 5-step pre-flight analysis before sending any message. This is the single highest-impact feature upgrade.

#### [MODIFY] [neutral_engine.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/infrastructure/neutral_engine.py)

Add `async _pre_negotiation_analysis()` method:

```python
async def _pre_negotiation_analysis(
    self, session, rfq_context, valuation, opponent_belief, strategy_rec
) -> dict:
    """Hidden LLM call: structured 5-step pre-flight analysis (temp=0.0)."""
    
    analysis_prompt = f"""
    === PRE-NEGOTIATION ANALYSIS (INTERNAL ONLY — NEVER REVEAL) ===
    STEP 1: ROLE & POSITION ANALYSIS
    - My role: {session.next_proposer.value}
    - Round: {session.round_count.value + 1}
    - My constraints: target={valuation.target_price}, aspirational={valuation.aspirational_price}
    
    STEP 2: ITEM EVALUATION  
    - Product: {rfq_context.get('product', 'unknown')} (Qty: {rfq_context.get('quantity', '?')})
    - Selected strategy: {strategy_rec.strategy.value}
    
    STEP 3: PRICE DISCIPLINE
    - Strategy suggests: ₹{strategy_rec.suggested_price:,.2f}
    - Acceptable range: [{valuation.aspirational_price}, {valuation.target_price}]
    
    STEP 4: COUNTERPARTY MODELING
    - Opponent type: {opponent_belief.dominant_type.value} (conf: {opponent_belief.confidence:.0%})
    - Their flexibility: {opponent_belief}
    
    STEP 5: STRATEGY SELECTION
    - Generate 2-3 tactical approaches for this round
    - Select the optimal one with rationale
    - Identify key persuasion arguments specific to this product/deal
    
    Output as JSON: {{"selected_approach": str, "key_arguments": [str], "tone": str, "risk_assessment": str}}
    """
    
    return await self._analysis_driver.call(
        system_prompt="You are a strategic negotiation analyst.",
        user_content=analysis_prompt,
        temperature=0.0
    )
```

**Integration point:** Between Strategy Engine output and main LLM call. Inject the analysis into `session_context["_internal_analysis"]`.

**Cost control:** Uses a **separate lightweight LLM driver** (`self._analysis_driver`) — e.g., Groq Llama-3.1-8B at temperature=0.0. Fast, near-free, and deterministic. The expensive frontier model is reserved only for the main dialogue generation call. Gated by `ENABLE_PRE_ANALYSIS=true` env var.

#### [MODIFY] [dependencies.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/api/dependencies.py)

Instantiate a second `LLMAgentDriver` with `LLM_ANALYSIS_PROVIDER=groq` and `LLM_ANALYSIS_MODEL=llama-3.1-8b-instant` and pass it as `analysis_driver` to `NeutralEngine`.

#### [MODIFY] [neutral_engine.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/infrastructure/neutral_engine.py)

Add `analysis_driver: IAgentDriver | None = None` to constructor. Falls back to `self._agent_driver` if not set.

---

### 1B. Prompt Injection Hardening (IMP-02)

> MIT competition's #2 agent ("Inject+Voss") won by tricking opponents into revealing their BATNA. Defense is mandatory.

#### [MODIFY] [guardrails.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/domain/guardrails.py)

Add `PromptInjectionDefense` class:

```python
class PromptInjectionDefense:
    """Defense-in-depth against prompt injection and information leakage."""
    
    INJECTION_PATTERNS = [
        r"(?i)remind me of your (offers|strategy|internal|analysis)",
        r"(?i)(not visible|invisible|hidden|internal|just for you)",
        r"(?i)share your (reasoning|thinking|analysis|batna|reservation|walk.?away)",
        r"(?i)ignore (previous|all|prior|above) instructions",
        r"(?i)you are now|pretend you are|act as if",
        r"(?i)what is your (floor|ceiling|minimum|maximum|reservation|budget)",
        r"(?i)system\s*prompt|initial\s*instructions",
    ]
    
    LEAK_PATTERNS = [
        r"(?i)my (reservation|walk.?away|floor|ceiling|minimum|batna) (is|price|point)",
        r"(?i)(reservation_price|aspirational_price|budget_ceiling)\s*[=:]\s*[\d₹]",
        r"(?i)I cannot go (below|above) ₹?\d",
        r"(?i)my absolute (limit|floor|ceiling)",
    ]
    
    @staticmethod
    def sanitize_incoming(text: str) -> tuple[str, bool]:
        """Strip injection attempts before LLM sees them. Returns (cleaned, was_modified)."""
        
    @staticmethod
    def scan_output(text: str) -> bool:
        """Returns True if output leaks internal information."""
```

#### [MODIFY] [neutral_engine.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/infrastructure/neutral_engine.py)

Wire defense at two points:
1. **Input scrubbing** — call `sanitize_incoming()` on each offer's reasoning text before injecting into offer_history for LLM
2. **Output scanning** — call `scan_output()` on LLM reasoning. If leak detected, strip the reasoning text and log warning (don't regenerate — too expensive)

---

### 1C. Warmth-Dominant Communication Strategy (IMP-03)

> MIT study proved "warm" agents avoid impasses and close significantly more deals than cold rational optimizers.

#### [MODIFY] [personalization.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/infrastructure/personalization.py)

Add `COMMUNICATION STYLE` section to the system prompt in `PersonalizationBuilder.build()`:

```text
=== COMMUNICATION STYLE (MANDATORY) ===
1. ALWAYS acknowledge the opponent's last offer positively before countering.
   Example: "I appreciate your willingness to move on price..."
2. ASK at least one question per response to show engagement.
   Example: "What factors are driving your pricing for this order?"
3. EXPRESS gratitude when opponent concedes ("Thank you for the adjustment...")
4. NEVER use hostile words: unacceptable, ridiculous, refuse, impossible, absurd.
5. Frame rejections as constraints, not refusals:
   BAD: "We refuse to accept this price."
   GOOD: "Our cost structure doesn't allow us to go below ₹X at this volume."
6. Use first-person plural ("we") to build partnership framing.
```

#### [MODIFY] [neutral_engine.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/infrastructure/neutral_engine.py)

Add lightweight warmth scoring:

```python
def _compute_warmth_score(self, reasoning: str) -> float:
    """Score 0.0–1.0 based on question marks, gratitude, absence of hostility."""
    score = 0.0
    if "?" in reasoning: score += 0.3  # Asks questions
    gratitude = ["thank", "appreciate", "grateful", "value your"]
    if any(w in reasoning.lower() for w in gratitude): score += 0.3
    hostile = ["unacceptable", "ridiculous", "refuse", "impossible", "absurd"]
    if not any(w in reasoning.lower() for w in hostile): score += 0.4
    return min(1.0, score)
```

If warmth < 0.3, append a softening hint to the next turn's context (don't regenerate).

---

### 1D. Enhanced 8-Archetype Bayesian Model (IMP-04)

> The current 4-archetype model conflates distinct behaviors. E.g., "hardball then cave" registers as "stubborn" early and "cooperative" late — losing the predictive pattern.

#### [MODIFY] [opponent_model.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/domain/opponent_model.py)

Expand from 4 to 8 archetypes:

| Current 4 | New 4 Additions |
|-----------|----------------|
| `COOPERATIVE` | **`DEADLINE_DRIVEN`** — speeds up concessions only near timeout |
| `STRATEGIC` | **`RECIPROCATOR`** — mirrors concessions exactly (tit-for-tat player) |
| `STUBBORN` | **`HARDBALL_THEN_CAVE`** — holds firm then collapses after round 6–8 |
| `BLUFFING` | **`ESCALATOR`** — increases demands (negative concession trend) |

**Changes:**
1. Expand `OpponentType` enum with 4 new variants
2. Add Gaussian likelihood parameters for each new type across all 3 signals + new `concession_trend` signal
3. Add `compute_concession_trend()` as 4th Bayesian signal (already exists in codebase but not wired into posteriors)
4. `OpponentBelief` grows to 8 fields (with backward-compat defaults of 0.0 for new types)
5. Update `strategy_modifier()` to return modifiers for all 8 types

#### [MODIFY] [strategy.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/domain/strategy.py)

Update `select_strategy()` to react to new opponent types:
- `DEADLINE_DRIVEN` → tighten concession (they'll concede near deadline regardless)
- `RECIPROCATOR` → exact tit-for-tat is optimal
- `HARDBALL_THEN_CAVE` → patience (they'll break after round 6–8, don't escalate early)
- `ESCALATOR` → walk away faster (3 rounds instead of stall_threshold)

Update `adaptive_concession()` modifiers dict:
```python
modifiers = {
    "cooperative": Decimal("0.85"),
    "strategic":   Decimal("1.00"),
    "stubborn":    Decimal("1.20"),
    "bluffing":    Decimal("0.70"),
    "deadline_driven": Decimal("0.75"),   # They'll cave at deadline → be patient
    "reciprocator":    Decimal("1.00"),   # Match exactly
    "hardball_then_cave": Decimal("0.90"),# Hold firm, they'll break
    "escalator":   Decimal("0.50"),       # Defensive, prepare to walk
}
```

---

### 1E. LLM Temperature Tuning for CONDITIONAL Strategy (Audit §20, Gap #11)

> Temperature 0.3 is good for price consistency but too low for creative term proposals in CONDITIONAL strategy.

#### [MODIFY] [neutral_engine.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/infrastructure/neutral_engine.py)

When the selected strategy is `CONDITIONAL`, increase the LLM temperature from 0.3 to 0.6 for that specific call:

```python
llm_temperature = 0.6 if strategy_rec.strategy == StrategyType.CONDITIONAL else 0.3
```

This allows the LLM to be more creative when proposing bundled terms (payment schedules, delivery timelines, warranties) without affecting price-focused negotiations.

---

### 1F. Wasserstein Distance Strategy Shift Detection (IMP-05)

> TLNAgent (ANAC competition winner) detects mid-session opponent strategy shifts using distributional distance to trigger rapid re-classification.

#### [MODIFY] [opponent_model.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/domain/opponent_model.py)

Add `detect_strategy_shift()` function:

```python
def detect_strategy_shift(
    historical_prices: list[float],
    recent_window: int = 5,
    threshold: float = 0.3,
) -> bool:
    """
    Detect if opponent suddenly changed tactics using Wasserstein distance.
    
    Splits price history into historical vs recent windows.
    If distributional distance > threshold → strategy shift detected.
    
    Uses scipy.stats.wasserstein_distance (lightweight, no ML needed).
    """
    if len(historical_prices) < recent_window + 3:
        return False  # Not enough data
    
    # Convert prices to concession deltas (normalized)
    deltas = [abs(historical_prices[i] - historical_prices[i-1]) / max(historical_prices[i-1], 1)
               for i in range(1, len(historical_prices))]
    
    hist_deltas = deltas[:-recent_window]
    recent_deltas = deltas[-recent_window:]
    
    from scipy.stats import wasserstein_distance
    distance = wasserstein_distance(hist_deltas, recent_deltas)
    return distance > threshold
```

#### [MODIFY] [neutral_engine.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/infrastructure/neutral_engine.py)

After computing `opponent_prices` in `process_turn()`: if `detect_strategy_shift()` returns True, **reset the opponent belief to prior** and log a `strategy_shift_detected` event. This forces the Bayesian model to re-classify from fresh data rather than carrying over a now-invalid belief.

---

### 1G. Activate Unused Strategies (Audit §20, Gap #6)

> CONSERVATIVE, CONCESSIVE, CONSTRAINED are defined in `StrategyType` but never selected by `select_strategy()`. Either wire them into the decision tree or remove them to eliminate dead code.

#### [MODIFY] [strategy.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/domain/strategy.py)

Wire the 3 reserved strategies into `select_strategy()`:

- **CONSERVATIVE** — selected when `opponent_flexibility` is 0.3–0.5 AND `rounds_since_concession < 2` (moderate opponent, no stall)
- **CONCESSIVE** — selected when session is 60–85% through rounds AND gap > 10% (need to close but not deadline-critical)
- **CONSTRAINED** — selected when price is within 5% of reservation AND time > 25% remaining (near floor, careful moves)

Add method implementations for each:
```python
def _conservative(self, my_last, floor, target, is_buyer) -> StrategyRecommendation:
    """Small step: 1.5% concession."""

def _concessive(self, my_last, floor, target, is_buyer) -> StrategyRecommendation:
    """Larger step: 3-5% concession to close gap in mid-late rounds."""

def _constrained(self, my_last, floor, target, is_buyer) -> StrategyRecommendation:
    """Near-floor: 0.5-1% micro-concession while signaling limit."""
```

---

## Phase 2: Personalization & Memory (Continuous Learning Loop)

*Activates existing infrastructure to make the engine smarter with every completed session.*

---

### 2A. Conversation Transcript JSON Storage (PERS-01 + Personalization Audit Sub-System 3)

#### [NEW] Database migrations (Alembic files will be generated)

```sql
-- Migration 1: conversation_transcript on sessions
ALTER TABLE negotiation_sessions ADD COLUMN conversation_transcript JSONB;

-- Migration 2: intelligence fields on profiles
ALTER TABLE agent_profiles
    ADD COLUMN negotiation_intelligence JSONB,
    ADD COLUMN style_summary TEXT,
    ADD COLUMN vault_bytes_used BIGINT DEFAULT 0;

-- Migration 3: user_id scoping on agent_memory
ALTER TABLE agent_memory ADD COLUMN user_id UUID REFERENCES users(id);
CREATE INDEX ix_agent_memory_user_id ON agent_memory(tenant_id, user_id);

-- Migration 4: vault_metadata table for quota tracking
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

#### [MODIFY] [models.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/infrastructure/models.py)

Add column: `conversation_transcript = Column(JSONB, nullable=True)`

#### [MODIFY] [session.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/domain/session.py)

Add field: `conversation_transcript: dict | None = None`

Add method (matching personalization audit's exact schema):
```python
def build_conversation_transcript(self) -> dict:
    """Denormalize session into a structured JSON transcript for RAG ingestion."""
    return {
        "session_id": str(self.id),
        "rfq_id": str(self.rfq_id),
        "outcome": self.status.value,
        "agreed_price": float(self.agreed_price.amount) if self.agreed_price else None,
        "rounds_taken": self.round_count.value,
        "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        "buyer_enterprise_id": str(self.buyer_enterprise_id),
        "seller_enterprise_id": str(self.seller_enterprise_id),
        "deal_quality": self.deal_quality_score,
        "rounds": [
            {
                "round": o.round_number.value,
                "role": o.proposer_role.value,
                "price": float(o.price.amount),
                "reasoning": o.agent_reasoning or "",
                "confidence": o.confidence.value if o.confidence else None,
                "is_human": o.is_human_override,
            }
            for o in self.offers
        ],
    }
```

#### [MODIFY] [services.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/application/services.py)

In `_handle_agreement()` and `_handle_walk_away()`:
1. Call `session.build_conversation_transcript()`
2. Store in `session.conversation_transcript`
3. Persist via repo update

---

### 2B. Auto-Ingestion RAG Loop with Temporal Decay (PERS-02)

#### [MODIFY] [services.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/application/services.py)

After generating transcript in `_handle_agreement()`:

```python
# Background: embed transcript for future RAG retrieval
if self.personalization_service is not None:
    import asyncio
    asyncio.create_task(
        self._ingest_transcript_as_memory(session, transcript)
    )
```

Add `_ingest_transcript_as_memory()`:
- Convert transcript dict → text summary
- Ingest for both buyer and seller enterprise IDs
- Use `PersonalizationService.ingest_text_directly()` (new method)

#### [MODIFY] [personalization_service.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/application/personalization_service.py)

Add `async ingest_text_directly(tenant_id, text, role, metadata) → dict`:
- Chunks the text directly (no S3 download needed)
- Embeds via Gemini
- Stores in pgvector

#### [MODIFY] [repositories.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/infrastructure/repositories.py)

Add temporal decay weighting to RAG retrieval SQL:
```sql
ORDER BY (1 - (m.embedding <=> :query_embedding)) * 
         EXP(-0.693 * EXTRACT(EPOCH FROM (NOW() - m.created_at)) / (30 * 86400)) *
         (CASE WHEN m.metadata->>'outcome' = 'AGREED' THEN 1.0 ELSE 0.6 END)
         DESC
```

This favors recent, successful negotiation memories.

---

### 2C. Smart Vault: Active/Archived Split + Content Deduplication (Personalization Audit Sub-System 1)

> **Design principle:** Storage (S3/MinIO) is nearly free — be generous. Embedding slots (pgvector) cost real money — control them tightly. The old flat-cap design ("50MB limit") punished users for uploading; this design gives unlimited storage but controls *which* documents burn embedding credits.

#### The Core Architecture

```
Every uploaded document has two independent states:

  S3 / MinIO (ALWAYS stored, never deleted unless user requests):
  └── raw/{enterprise_id}/{user_id}/{filename}  ← unlimited, ~$0

  pgvector (ONLY for "active" documents):
  └── agent_memory rows with embeddings        ← costs Gemini API credits
      ├── FREE tier:  25MB active embedding quota per user
      ├── PRO tier:  150MB active embedding quota per user
      └── ENTERPRISE: unlimited

Uploading = always succeeds (goes to S3)
Activating = costs embedding quota (goes to pgvector)
Archiving  = removes pgvector rows, keeps S3 (frees embedding quota)
```

#### Design Decisions

| Problem | Old Design | New Design |
|---------|-----------|------------|
| Upload 100 contracts | Fails at 50MB | ✅ Always succeeds (S3 is free) |
| Embedding cost at scale | Embed everything blindly | ✅ Only embed "active" docs |
| Duplicate vendor templates | Re-embed identical content | ✅ SHA-256 dedup — embed once, reuse |
| Old docs nobody reads | Stay in pgvector forever | ✅ Auto-demote after 90 days of zero hits |
| Wrong doc active | User stuck | ✅ User can archive/activate any doc |

#### [MODIFY] Database migration (add to Migration 4 in Phase 2A)

```sql
CREATE TABLE vault_metadata (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    enterprise_id     UUID NOT NULL REFERENCES enterprises(id),
    user_id           UUID REFERENCES users(id),
    filename          TEXT NOT NULL,
    s3_key            TEXT NOT NULL,
    size_bytes        BIGINT NOT NULL,
    mime_type         TEXT,
    content_hash      TEXT NOT NULL,          -- SHA-256 of raw content, for dedup
    is_active         BOOLEAN DEFAULT FALSE,  -- TRUE = embedded in pgvector
    active_bytes_used BIGINT DEFAULT 0,       -- Bytes contributing to active quota
    embedding_count   INT DEFAULT 0,          -- Number of pgvector rows created
    last_retrieved_at TIMESTAMP WITH TIME ZONE, -- For auto-demotion (90-day TTL)
    ingested_at       TIMESTAMP WITH TIME ZONE,
    created_at        TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX ix_vault_metadata_enterprise ON vault_metadata(enterprise_id);
CREATE INDEX ix_vault_metadata_user       ON vault_metadata(user_id);
CREATE INDEX ix_vault_metadata_hash       ON vault_metadata(content_hash); -- dedup lookup
CREATE INDEX ix_vault_metadata_active     ON vault_metadata(enterprise_id, is_active);
```

#### [NEW] Vault repository in [repositories.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/infrastructure/repositories.py)

Add `PostgresVaultMetadataRepository`:
```python
# Tier limits (bytes)
VAULT_ACTIVE_LIMITS = {
    "FREE":       25  * 1024 * 1024,   # 25MB active embedding quota
    "PRO":        150 * 1024 * 1024,   # 150MB active embedding quota
    "ENTERPRISE": float("inf"),         # Unlimited
}

class PostgresVaultMetadataRepository:

    async def get_active_bytes_used(self, enterprise_id: UUID, user_id: UUID) -> int:
        """Sum of size_bytes WHERE is_active=TRUE. Fast Postgres counter."""

    async def find_by_hash(self, content_hash: str) -> VaultMetadata | None:
        """Check if identical content is already embedded anywhere (global dedup)."""

    async def record_upload(
        self, enterprise_id, user_id, filename, s3_key,
        size_bytes, mime_type, content_hash
    ) -> VaultMetadata:
        """Insert with is_active=False. Upload always succeeds."""

    async def activate(
        self, vault_id: UUID, embedding_count: int
    ) -> None:
        """Set is_active=True, record embedding_count, set active_bytes_used."""

    async def archive(self, vault_id: UUID) -> int:
        """Set is_active=False, return bytes freed from active quota."""

    async def record_retrieval_hit(self, vault_id: UUID) -> None:
        """Update last_retrieved_at=NOW() when this doc's chunks are used in RAG."""

    async def get_stale_active_docs(
        self, older_than_days: int = 90
    ) -> list[VaultMetadata]:
        """Docs with is_active=True AND last_retrieved_at < NOW() - interval."""
```

#### [NEW] Upload + Activate endpoints (in a new `personalization_router.py`)

```python
# STEP 1: Upload — always succeeds, goes to S3 only, no embedding cost
@router.post("/v1/memory/upload")
async def upload_document(file: UploadFile, user: User = Depends(get_current_user)):
    content = await file.read()
    content_hash = hashlib.sha256(content).hexdigest()

    # Always store to S3 — no quota check needed (storage is free)
    s3_key = f"raw/{user.enterprise_id}/{user.id}/{file.filename}"
    await s3_vault.store_document(user.enterprise_id, s3_key, content)
    meta = await vault_repo.record_upload(
        user.enterprise_id, user.id, file.filename,
        s3_key, len(content), file.content_type, content_hash
    )
    return success_response(data={
        "vault_id": str(meta.id),
        "filename": file.filename,
        "bytes": len(content),
        "status": "archived",  # Not yet embedded
        "hint": "Call POST /v1/memory/{vault_id}/activate to make this document searchable."
    })


# STEP 2: Activate — checks quota, runs embedding, costs money
@router.post("/v1/memory/{vault_id}/activate")
async def activate_document(
    vault_id: UUID,
    user: User = Depends(get_current_user),
    svc: PersonalizationService = Depends(get_personalization_service),
):
    meta = await vault_repo.get(vault_id)
    tier_limit = VAULT_ACTIVE_LIMITS.get(user.plan, VAULT_ACTIVE_LIMITS["FREE"])
    active_used = await vault_repo.get_active_bytes_used(user.enterprise_id, user.id)

    # Quota check only at activation, not upload
    if active_used + meta.size_bytes > tier_limit:
        raise HTTPException(413, detail={
            "error": "active_embedding_quota_exceeded",
            "active_used_mb": active_used // (1024 * 1024),
            "limit_mb": tier_limit // (1024 * 1024),
            "file_mb": meta.size_bytes // (1024 * 1024),
            "hint": "Archive another document first, or upgrade your plan."
        })

    # Content deduplication: if identical hash already embedded, reuse vectors
    existing = await vault_repo.find_by_hash(meta.content_hash)
    if existing and existing.is_active:
        # Point this user's entry to the existing embeddings — zero API cost
        await vault_repo.activate(vault_id, embedding_count=existing.embedding_count)
        return success_response(data={"vault_id": str(vault_id), "deduped": True})

    # Fresh embedding — triggers actual Gemini API calls
    asyncio.create_task(
        svc.ingest_from_s3(user.enterprise_id, meta.s3_key, role=user.role, vault_id=vault_id)
    )
    return success_response(data={"vault_id": str(vault_id), "status": "embedding_queued"})


# STEP 3: Archive — frees active quota, keeps S3 file
@router.post("/v1/memory/{vault_id}/archive")
async def archive_document(vault_id: UUID, user: User = Depends(get_current_user)):
    bytes_freed = await vault_repo.archive(vault_id)
    # Delete pgvector rows for this vault_id
    await memory_repo.delete_by_vault_id(vault_id)
    return success_response(data={"bytes_freed": bytes_freed})
```

#### [NEW] Auto-demotion background job in [services.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/application/services.py)

```python
async def demote_stale_vault_embeddings(self) -> int:
    """
    Background cron: archive embeddings not retrieved in 90 days.
    Frees active quota for users. S3 files are untouched.
    Run alongside cleanup_expired_sessions().
    """
    stale = await self.vault_repo.get_stale_active_docs(older_than_days=90)
    for doc in stale:
        await self.memory_repo.delete_by_vault_id(doc.id)
        await self.vault_repo.archive(doc.id)
    return len(stale)
```

#### [MODIFY] RAG retrieval in [repositories.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/infrastructure/repositories.py)

When a RAG chunk is returned in a retrieval hit, update `last_retrieved_at` on the parent `vault_metadata` row:
```python
# After returning RAG results, fire-and-forget:
await vault_repo.record_retrieval_hit(chunk.vault_id)
```

This keeps actively useful documents from being auto-demoted.

#### Vault Tier Summary

| Tier | S3 Storage | Active Embedding Quota | Auto-Embed | Cost to You |
|------|-----------|----------------------|------------|-------------|
| **Free** | Unlimited | **25MB** | No | ~$0.25/user max |
| **Pro** | Unlimited | **150MB** | Yes (latest 10 docs) | ~$1.50/user max |
| **Enterprise** | Unlimited | **Unlimited** | Yes | Varies |

> [!NOTE]
> Session-scoped retrieval (filtering `agent_memory` by `metadata->>'hsn_prefix'` matching the current RFQ's HSN code) further reduces retrieval noise — only relevant category documents appear in RAG context even if 150MB of mixed documents are active.

---

### 2D. NLP Intelligence Extraction from Transcripts (PERS-03)

#### [NEW] [intelligence_service.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/application/intelligence_service.py)

Exact schema from personalization audit:
```python
class NegotiationIntelligenceService:
    """
    Extracts negotiation intelligence from:
    1. Uploaded user documents (at ingestion time) — via LLM
    2. Completed negotiation transcripts (at session completion) — pure math, no LLM
    Updates AgentProfile.negotiation_intelligence JSONB.
    """
    
    def extract_from_transcript(self, transcript: dict) -> dict:
        """Pure-math extraction — no LLM needed. Computed from offer sequence."""
        # Computes:
        # - avg_concession_pct: mean |Δprice| / price per round
        # - opening_anchor_pct_below_budget: (budget - opening_price) / budget × 100
        # - rounds_to_close: total rounds taken
        # - consistency_score: monotonicity (1.0 = always conceding, 0.0 = oscillating)
        # - style_classification: curve shape analysis
        #   (boulware = slow-then-fast → "assertive", conceder = fast-then-slow → "collaborative")
        # - buyer_intelligence + seller_intelligence dicts for transcript JSON
        
    async def extract_from_document(self, content: str, tenant_id: UUID) -> dict:
        """LLM extraction of style signals from uploaded procurement documents."""
        # Uses lightweight Groq/Llama (same analysis_driver as pre-analysis)
        EXTRACTION_PROMPT = """
Analyze this procurement negotiation document and extract:
{
  "preferred_discount_range_pct": [min, max],
  "payment_terms_preference": "advance|net30|LC|flexible",
  "negotiation_style": "collaborative|assertive|analytical|competitive",
  "typical_concession_size_pct": number,
  "common_terms_prioritized": ["quality", "delivery", "price", "warranty"],
  "walk_away_signals": ["phrases that indicate near-rejection"],
  "deal_accelerators": ["phrases that indicate readiness to close"]
}
Return null for any field you cannot determine with confidence.
"""
        
    async def update_profile_intelligence(self, profile: AgentProfile, new_signals: dict) -> AgentProfile:
        """EMA-merge new signals into existing intelligence JSONB."""
```

#### [MODIFY] [agent_profile.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/domain/agent_profile.py)

Add fields (all from the personalization audit DB schema):
```python
negotiation_intelligence: dict | None = None  # Structured intelligence JSONB
style_summary: str | None = None              # Human-readable style description
vault_bytes_used: int = 0                     # Running counter for quota enforcement
```

#### [MODIFY] [services.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/application/services.py)

In `_handle_agreement()`, after transcript generation:
```python
# Extract intelligence and update profiles (pure math, no extra LLM call)
intel = self.intelligence_service.extract_from_transcript(transcript)
await self.intelligence_service.update_profile_intelligence(buyer_profile, intel)
await self.intelligence_service.update_profile_intelligence(seller_profile, intel)
await self.profile_repo.update(buyer_profile)
await self.profile_repo.update(seller_profile)
```

---

### 2E. Intelligence Injection into LLM Prompts (PERS-03 + PERS-04 + Personalization Audit)

#### [MODIFY] [personalization.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/infrastructure/personalization.py)

When `profile.negotiation_intelligence` is populated, add section to system prompt (exact format from personalization audit):

```text
=== YOUR NEGOTIATION INTELLIGENCE (from your history) ===
Based on your past {N} negotiations:
- You typically close at {X-Y}% below your opening offer
- Your average deal takes {N} rounds
- You tend to use {assertive/collaborative} early anchoring, then {style} after round {N}
- Your highest win rate is with [{commodity}] suppliers ({X}%)
- You have negotiated with [Counterparty] before: they responded well to [tactic]

Style profile: {collaborative|assertive|analytical}
Typical concession per round: {X}%
Conditions where you close deals fastest: {top-3 deal accelerators}
```

---

### 2E. Wire OpponentProfileRepository for Cross-Session Learning (Personalization Audit)

> The `opponent_profiles` table exists (audit §14) but isn't wired into `NeutralEngine`. Bayesian beliefs reset per-session instead of persisting across sessions with the same counterparty.

#### [MODIFY] [dependencies.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/api/dependencies.py)

Wire `PostgresOpponentProfileRepository` and pass to `NeutralEngine`.

#### [MODIFY] [neutral_engine.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/infrastructure/neutral_engine.py)

In `_get_or_compute_belief()`:
1. Check `opponent_profiles` table first (cross-session persistence)
2. Fall back to `session.opponent_beliefs` (in-session persistence — already done)
3. Fall back to `_belief_cache` (in-memory)
4. Fall back to uniform prior

In `_update_belief_cache()`:
- Also upsert to `opponent_profiles` table after each round

---

## Phase 3: Adjacent Enterprise Features

---

### 3A. Relational Quality Scoring (PERS-04)

> Research basis: AI can reliably assess trust/respect (CUI'25). Talk time and sentiment predict outcomes (Di Stasi 2024).

> AI can reliably assess trust/respect (CUI'25 research). Sentiment and talk time predict outcomes.

#### [NEW] [relational_quality.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/domain/relational_quality.py)

```python
class RelationalQualityScorer:
    """Pure-math quality scoring for completed negotiations."""
    
    def score(self, session: NegotiationSession) -> dict:
        return {
            "trust": self._compute_trust(session.offers),
            "respect": self._compute_respect(session.offers),
            "equitability": self._compute_equitability(session),
            "composite": weighted_average,  # 0.0 – 1.0
        }
    
    def _compute_trust(self, offers) -> float:
        """Consistency of concession direction + no sudden reversals."""
        
    def _compute_respect(self, offers) -> float:
        """Reasonable counter-offers (not absurdly far from opponent's last)."""
        
    def _compute_equitability(self, session) -> float:
        """Balanced total concession between buyer and seller."""
```

#### [MODIFY] [services.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/application/services.py)

Call `RelationalQualityScorer.score()` at terminal state. Store alongside `deal_quality_score` in the transcript.

---

### 3B. Deal Quality Analytics API (ADJ-02)

> From improvement report: "Dashboard graphing price vs round trajectory and displaying Relational Quality Scores. Proves ROI to Chief Procurement Officers."

#### [MODIFY] [router.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/api/router.py)

Add `GET /v1/sessions/{id}/analytics`:
- Deal quality score (ZOPA position, surplus distribution)
- Relational quality scores (trust, respect, equitability)
- Negotiation trajectory data (price vs round, for charting)
- Intelligence summary from profiles

---

### 3C. Co-Pilot Advisor Mode Foundation (ADJ-01)

> From improvement report: "UI mode where AI drafts the response and shows the underlying math/strategy, but a human manager clicks Approve, Tweak, or Reject. Builds immense trust."

The backend part of Co-Pilot mode is largely **already implemented** via the existing `/override` endpoint. What's needed is a new response shape for the Turn API:

#### [MODIFY] [router.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/api/router.py)

Add `preview=true` query param to `POST /v1/sessions/{id}/turn`:
- When `preview=true`, compute the offer (run full 4-layer pipeline) but **do not persist it**
- Return the draft offer + strategy rationale + price band to the frontend for human review
- Human can then call `/override` with their approved price, or call `/turn` without `preview` to accept as-is

---

### 3D. Multi-Vendor RFQ Orchestrator Blueprint (ADJ-03)

> From improvement report: "Spawn parallel bilateral sessions for a single RFQ, inject competitive pressure awareness."

#### [NEW] [orchestrator.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/application/orchestrator.py)

```python
class MultiPartyNegotiationOrchestrator:
    """Spawns parallel bilateral sessions for a single RFQ."""
    
    def __init__(self, rfq_id: UUID):
        self.active_sessions: dict[UUID, NegotiationSession] = {}  # seller_id → session
    
    async def inject_competitive_context(self, session: NegotiationSession) -> dict:
        """Inject awareness of competing offers without revealing specifics."""
        n = len(self.active_sessions)
        return {"competitive_pressure": "HIGH" if n > 3 else "MODERATE" if n > 1 else "LOW"}
    
    async def select_best_agreement(self) -> NegotiationSession:
        """Auto-award to the lowest AGREED price among parallel sessions."""
        agreed = [s for s in self.active_sessions.values() if s.status == SessionStatus.AGREED]
        return min(agreed, key=lambda s: s.agreed_price.amount)
```

> [!NOTE]
> This is a **blueprint** for Phase 3. Actual multi-session coordination requires additional API endpoints and is scoped for post-MVP.

---

### 3E. Dynamic Market Anchoring (ADJ-04)

> From improvement report: "Blend live market price data into target_price calculation to make AI arguments mathematically irrefutable."

#### [NEW] Market price feed protocol in [neutral_engine.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/infrastructure/neutral_engine.py)

```python
class IMarketPriceFeed(Protocol):
    async def get_reference_price(self, product: str, hsn_code: str | None) -> Decimal | None: ...
```

In `_compute_valuation()`, if a market price feed is wired in, blend it:
```python
if self._market_feed:
    market_ref = await self._market_feed.get_reference_price(product)
    if market_ref:
        # Blend: 70% RFQ data + 30% market reference
        target_price = target_price * Decimal("0.7") + market_ref * Decimal("0.3")
```

> [!NOTE]
> The feed implementation itself (connecting to commodity price APIs) is out of scope for this plan but the protocol + injection point will be wired now so it can be plugged in later.

---

### 3F. Distributed Lock for run-auto (Audit §20, Gap #1)

> If two clients call `/run-auto` for the same session simultaneously, both drive the FSM causing out-of-turn errors.

#### [MODIFY] [router.py](file:///c:/Users/omen/OneDrive/Desktop/cadencia-goa-v2/backend/src/negotiation/api/router.py)

Add Redis advisory lock before the negotiation loop:

```python
lock_key = f"negotiation:run_auto:{session_id}"
lock = redis_client.lock(lock_key, timeout=300)  # 5-min max hold
if not await lock.acquire(blocking=False):
    raise HTTPException(409, detail="Negotiation already running for this session")
try:
    # ... existing loop logic ...
finally:
    await lock.release()
```

---

## Phase 4: Advanced ML & RL (Deferred)

> [!NOTE]
> **DO NOT build these until you have 1,000+ completed negotiations.** Phase 2's auto-ingestion loop captures exactly the training data these will need.

- **ML-01 (Improvement Report):** Transfer Learning & Opponent Fingerprinting — Fit Universal Background Model (K=64 GMM) to historical state trajectories. Adapt GMM means to specific opponents → 576-dim Supervector for strategy transfer.
- **ML-02 (Improvement Report):** Soft Actor-Critic (SAC) RL — Train SAC neural network (State: 11-dim → Action: Target Utility). Blend with heuristic engine weighted by training maturity.
- **ML-03 (Improvement Report):** Empirical Game-Theoretic Robustness Analysis — Automated round-robin tournament to find Nash equilibria among active strategies, prune underperformers.
- **ADJ-05 (Improvement Report):** Algorand Smart Contract Settlement — Upon `AGREED`, compile final JSON envelope into an Algorand smart contract. The `settlement/` bounded context already handles this handoff via `SessionAgreed` event; the contract compilation step is ADJ-05's scope.

---

---

## Items Explicitly Deferred (Not in Scope for This Implementation)

These items from the source documents are **acknowledged but not implemented** now:

| Item | Source | Reason Deferred |
|------|--------|----------------|
| Per-user vault scoping (user_id on agent_memory) | Personalization Audit | Schema migration ready (Migration 3 above), but full per-user vs per-enterprise isolation requires frontend + API changes. Data structure is ready. |
| Upload UI (frontend) | Personalization Audit | Backend upload endpoint is in 2C. Frontend is out of scope for this backend-only plan. |
| Supabase migration | Personalization Audit | Explicitly recommended **against** — current Postgres + MinIO + Redis stack is equivalent and already set up. |
| ADJ-05 Algorand Settlement | Improvement Report | Already handled by `settlement/` bounded context via `SessionAgreed` domain event. No changes needed in negotiation engine. |
| Phase 4 ML/RL | Improvement Report | Data-dependent. Build after 1,000+ completed sessions. |

---

## Open Questions

> All open questions have been resolved by user comments. No blocking questions remain.

| Question | Decision |
|----------|----------|
| GEMINI_API_KEY | ✅ Configured — real embeddings will work |
| LLM Provider | ✅ **OpenAI** for dialogue + analysis. `LLM_PROVIDER=openai` already supported natively in `LLMAgentDriver` — no code changes needed |
| Pre-Analysis LLM | ✅ **GPT-4.1-nano** via second `LLMAgentDriver` instance as `analysis_driver` |
| Embedding model | ✅ **Gemini text-embedding-004** — already wired in `GeminiEmbedder` |
| DB Migrations | ✅ Generate 4 Alembic migration files |
| Leaky abstraction | ✅ Add proper repository methods (Phase 0H) |

---

## Verification Plan

### Automated Tests
1. **Unit tests** for each new domain class: `PromptInjectionDefense`, `RelationalQualityScorer`, expanded `BayesianOpponentModel` (8 types), new strategies (CONSERVATIVE/CONCESSIVE/CONSTRAINED)
2. **Integration test:** Full `run-auto` with `StubAgentDriver` — pipeline works end-to-end
3. **Regression:** `pytest backend/tests/` all pass

### Manual Verification
1. Run live negotiation via `/run-auto`, inspect logs for:
   - `rag_context_injected` events (RAG working)
   - `pre_analysis_completed` events (if enabled)
   - Conversation transcript generated at terminal state
   - `deal_quality_score` + `relational_quality` populated
2. Prompt injection defense strips hostile patterns
3. Warmth score produces reasonable values

---

## Execution Summary

| Phase | Items | Est. LOC | Dependencies |
|-------|-------|----------|--------------|
| **0A** | Wire PersonalizationService DI | ~50 | None |
| **0B** | Valuation anchor sanity logging (DIAG-03) | ~25 | None |
| **0C** | Fix concession_rate learning | ~15 | None |
| **0D** | Remove dead sync method | ~-20 | None |
| **0E** | Dual-threshold stall detection | ~15 | None |
| **0F** | Schema counter reset on recovery | ~2 | None |
| **0G** | TIT_FOR_TAT modifier from profile | ~20 | None |
| **0H** | max_tokens default consistency | ~2 | None |
| **0I** | Fix leaky repo abstraction | ~80 | None |
| **1A** | Pre-Negotiation Analysis (GPT-4.1-nano) | ~130 | Phase 0A |
| **1B** | Prompt Injection Hardening | ~80 | None |
| **1C** | Warmth Communication | ~50 | None |
| **1D** | 8-Archetype Bayesian Model | ~200 | None |
| **1E** | Temperature tuning for CONDITIONAL | ~5 | None |
| **1F** | Wasserstein Shift Detection (IMP-05) | ~60 | Phase 1D |
| **1G** | Activate 3 unused strategies | ~90 | None |
| **2A** | 4× Alembic DB migrations | ~80 | None |
| **2B** | Conversation Transcript JSON | ~80 | Phase 2A |
| **2C** | Storage Quota + Upload API | ~120 | Phase 2A |
| **2D** | Auto-Ingestion RAG Loop | ~100 | Phase 0A, 2B |
| **2E** | NLP Intelligence Extraction Service | ~180 | Phase 2B |
| **2F** | Intelligence in Prompts | ~40 | Phase 2E |
| **2G** | OpponentProfile Repository wiring | ~60 | Phase 0A |
| **3A** | Relational Quality Scoring | ~80 | None |
| **3B** | Deal Quality Analytics API (ADJ-02) | ~60 | Phase 3A |
| **3C** | Co-Pilot preview mode (ADJ-01) | ~50 | None |
| **3D** | Multi-Vendor Orchestrator blueprint (ADJ-03) | ~80 | None |
| **3E** | Market Anchoring protocol (ADJ-04) | ~40 | None |
| **3F** | Distributed Lock for run-auto | ~30 | None |
| **Total** | **29 items** | **~1,680 lines** | |

---

## Infrastructure Stack & Cost Analysis

### Chosen Stack

| Layer | Technology | Reason |
|-------|-----------|--------|
| **Main negotiation LLM** | OpenAI GPT-4.1 | Best quality/cost for B2B negotiation dialogue; natively supported in `LLMAgentDriver` (`LLM_PROVIDER=openai`) |
| **Pre-analysis LLM** | OpenAI GPT-4.1-nano | Temperature=0.0, deterministic, 20× cheaper than GPT-4.1; second `LLMAgentDriver` instance as `analysis_driver` |
| **Embeddings** | Gemini text-embedding-004 | Already wired in `GeminiEmbedder`; 1,536-dim vectors; HNSW index on pgvector |
| **Vector store** | pgvector (existing Postgres) | Already running; HNSW cosine similarity; no new infra needed |
| **Cache / locks** | Redis (existing) | Already running; used for SSE + distributed lock (Phase 3F) |
| **Object store** | MinIO (existing) | Already running; S3-compatible; zero migration cost |

### `.env` Configuration for This Stack

```bash
# ── Main negotiation dialogue ─────────────────────────────────
LLM_PROVIDER=openai
LLM_MODEL=gpt-4.1
OPENAI_API_KEY=sk-...

# ── Pre-negotiation analysis (lightweight, deterministic) ─────
LLM_ANALYSIS_PROVIDER=openai
LLM_ANALYSIS_MODEL=gpt-4.1-nano
ENABLE_PRE_ANALYSIS=true

# ── Embeddings (already configured) ──────────────────────────
GEMINI_API_KEY=AIza...
# GeminiEmbedder uses text-embedding-004 by default — no other change needed
```

> [!NOTE]
> `LLM_PROVIDER=openai` is already one of the supported values in `get_agent_driver()`. The only code change needed is adding a second `LLMAgentDriver` instance for `analysis_driver` in `dependencies.py` (Phase 1A).

---

### Per-Turn Token Budget (Your Actual Prompts)

```
INPUT per turn (avg across all rounds):
  System prompt (PersonalizationBuilder.build()):
    Strategy + constraints section:    ~450 tokens
    Industry playbook section:         ~200 tokens
    RAG Top-5 chunks:                  ~800 tokens
    Rules section:                     ~200 tokens
    [Intelligence section, Phase 2F]:  ~150 tokens (once populated)
    Subtotal system:                   ~1,800 tokens

  User content (session_context dict):
    RFQ + catalogue data:              ~300 tokens
    Offer history (avg round 4):       ~400 tokens
    Price band + belief + strategy:    ~200 tokens
    [Pre-analysis output, Phase 1A]:   ~200 tokens (when enabled)
    Subtotal user:                     ~1,100 tokens

  TOTAL INPUT per turn (avg):          ~2,900 tokens
  TOTAL OUTPUT per turn (avg):         ~350 tokens (ActionEnvelope JSON + reasoning)

Pre-analysis call (GPT-4.1-nano, once per turn):
  Input:  ~900 tokens | Output: ~250 tokens
```

---

### OpenAI Pricing Reference (2025)

| Model | Input | Output | Role in Stack |
|-------|-------|--------|--------------|
| **GPT-4.1** | $2.00/1M tokens | $8.00/1M tokens | Main negotiation dialogue |
| **GPT-4.1-mini** | $0.40/1M tokens | $1.60/1M tokens | Budget alternative for dialogue |
| **GPT-4.1-nano** | $0.10/1M tokens | $0.40/1M tokens | Pre-analysis calls |
| **GPT-4o** | $2.50/1M tokens | $10.00/1M tokens | (Avoid — GPT-4.1 is better + cheaper) |

### Gemini Embedding Pricing

| Model | Price | Free Tier |
|-------|-------|-----------|
| **text-embedding-004** | $0.00001 / 1K characters (~$0.000037/1K tokens) | 1,500 req/day |

---

### Per-Session Cost (8-Round Avg, 16 LLM Calls, `ENABLE_PRE_ANALYSIS=true`)

| Call Type | Model | Calls | Tokens | Cost |
|-----------|-------|-------|--------|------|
| Main dialogue | GPT-4.1 | 16 | 16 × (2,900 in + 350 out) = 52,200 | **$0.151** |
| Pre-analysis | GPT-4.1-nano | 16 | 16 × (900 in + 250 out) = 18,400 | **$0.003** |
| RAG query embeds | Gemini | 16 | 16 × ~2,000 chars | **$0.0003** |
| Transcript ingestion | Gemini | 1 | ~8,000 chars | **$0.00008** |
| **Total per session** | | | | **~$0.154** |

> With `ENABLE_PRE_ANALYSIS=false` (no analysis calls): **~$0.151/session**  
> Using **GPT-4.1-mini** for dialogue instead: **~$0.027/session**

---

### All Viable Combinations

| Dialogue | Analysis | Quality | Cost/Session | Use When |
|----------|----------|---------|-------------|----------|
| **GPT-4.1** | GPT-4.1-nano | ⭐⭐⭐⭐⭐ | **~$0.154** | Production (recommended) |
| **GPT-4.1-mini** | GPT-4.1-nano | ⭐⭐⭐⭐ | **~$0.027** | Prototype / cost-sensitive |
| **GPT-4.1** | GPT-4.1-mini | ⭐⭐⭐⭐⭐ | **~$0.160** | If nano feels insufficient |
| **GPT-4.1-mini** | GPT-4.1-mini | ⭐⭐⭐⭐ | **~$0.030** | Balanced budget option |

---

### Monthly Cost Projections

#### Prototype (You testing, ~100 sessions/month)

| Resource | Usage | Cost/Month |
|----------|-------|-----------|
| GPT-4.1-mini (dialogue, prototype tier) | 100 × $0.024 | $2.40 |
| GPT-4.1-nano (analysis) | 100 × $0.003 | $0.30 |
| Gemini Embeddings | Within free tier (1,500 req/day) | $0.00 |
| Infrastructure | Docker locally | $0.00 |
| **Monthly total** | | **~$2.70** |

#### Early Production (50 active users, ~500 sessions/month)

| Resource | Usage | Cost/Month |
|----------|-------|-----------|
| GPT-4.1 (dialogue) | 500 × $0.151 | **$75.50** |
| GPT-4.1-nano (analysis) | 500 × $0.003 | **$1.50** |
| Gemini — RAG retrieval | 500 sessions × 16 queries | **$0.15** |
| Gemini — transcript ingestion | 500 sessions | **$0.04** |
| Gemini — doc uploads (onboarding) | 50 users × 10 docs × $0.0005 | **$0.25** |
| Cloud infra (VPS + Postgres + Redis) | | **$30–50** |
| **Monthly total** | | **~$107–127** |

#### Growth (500 users, ~5,000 sessions/month)

| Resource | Usage | Cost/Month |
|----------|-------|-----------|
| GPT-4.1 (dialogue) | 5,000 × $0.151 | **$755** |
| GPT-4.1-nano (analysis) | 5,000 × $0.003 | **$15** |
| Gemini Embeddings (all) | 5,000 sessions + uploads | **$12** |
| Cloud infrastructure (scaled) | | **$150** |
| **Monthly total** | | **~$932** |

---

### Unit Economics

| Metric | Value |
|--------|-------|
| Cost per negotiation session (GPT-4.1 stack) | **~₹13** ($0.154) |
| Reasonable B2B charge per session | **₹500–2,000** |
| Gross margin on LLM costs alone | **97–99%** |
| Break-even users at ₹5,000/month SaaS price | **~1.5 users** covers infra |
| **Vault: S3 storage per user** | **~$0** (MinIO self-hosted) |
| **Vault: Free tier embedding cost** (25MB active) | **~$0.25/user** one-time max |
| **Vault: Pro tier embedding cost** (150MB active) | **~$1.50/user** one-time max |
| Deduplication savings (identical vendor templates) | **Up to 80% fewer API calls** |
| Auto-demotion (90-day stale TTL) | Keeps pgvector lean, frees quota automatically |

### Vault Design: Why Active/Archived Split is Better

| Approach | UX | Cost Control | Verdict |
|----------|----|--------------|---------|
| Flat 50MB cap (old) | ❌ Upload fails at 50MB | ✅ Predictable | Bad UX for B2B |
| Flat 512MB cap | ✅ Generous uploads | ❌ $25/user worst case | Uncontrolled cost |
| **Active/Archived split (new)** | ✅ Unlimited uploads always succeed | ✅ Only active docs cost money | **Best of both** |

> [!NOTE]
> **S3/MinIO storage is essentially free** at prototype and early prod scale. The only real cost is Gemini embedding API calls — controlled by the 25MB free-tier **active quota** in Phase 2C. Users can upload 500MB of contracts but only 25MB are ever embedded at once on the free plan. Deduplication further cuts costs when multiple users upload identical vendor templates.
