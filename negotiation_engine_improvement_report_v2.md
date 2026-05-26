# DANP Negotiation Engine — Comprehensive Master Plan (Detailed Technical Spec)

> **Based on:** Engine Audit + Personalization Audit + 25 Research Papers + Diagnostic Review  
> **Scope:** A complete, code-level roadmap to transform the DANP prototype into a State-of-the-Art (SOTA) enterprise B2B product.  
> **Design Principle:** *Enhance, don't replace* — rely on the mathematically sound heuristic engine for MVP, and build intelligence around it.

---

## Table of Contents
1. [Executive Summary & Strategy](#1-executive-summary--strategy)
2. [Phase 0: Immediate Diagnostic Fixes (Why current results are poor)](#phase-0-immediate-diagnostic-fixes-why-current-results-are-poor)
3. [Phase 1: "Zero-Data" Core SOTA (MVP Must-Haves)](#phase-1-zero-data-core-sota-mvp-must-haves)
4. [Phase 2: Personalization & Memory (Continuous Learning Loop)](#phase-2-personalization--memory-continuous-learning-loop)
5. [Phase 3: Adjacent Enterprise Features (Product Amplifiers)](#phase-3-adjacent-enterprise-features-product-amplifiers)
6. [Phase 4: Advanced ML & RL (Long-Term / Data-Dependent)](#phase-4-advanced-ml--rl-long-term--data-dependent)

---

## 1. Executive Summary & Strategy

This master plan synthesizes core engine upgrades, hyper-personalization features, and enterprise-adjacent tools into a cohesive roadmap. 

**Crucial Insight for the MVP:** Your foundational architecture is excellent, but the *current* output quality is suffering due to foundational "wiring" and engine choice issues (addressed in Phase 0). Because you are building a prototype without historical training data, you must heavily prioritize **Phase 0, Phase 1, and Phase 2**. These upgrades instantly elevate the engine to the top 1% of autonomous negotiators using purely structural, heuristic, and prompt-engineering techniques, while setting up the exact data-capture pipelines needed for future Machine Learning.

---

## Phase 0: Immediate Diagnostic Fixes (Why current results are poor)
*Before adding new features, these three issues must be fixed to stop the engine from generating low-quality, robotic, or failing negotiations.*

### DIAG-01: Upgrade the LLM Core (Model Selection)
**The Problem:** Smaller, open-weight models (like Llama 3 8B on Groq) lack the deep psychological nuance, complex instruction-following, and subtle tone-shifting capabilities required for high-stakes negotiation. They struggle to balance strict mathematical guardrails with natural human dialogue.
**The Fix:** 
- Switch the core `NeutralEngine` LLM to a frontier model (e.g., GPT-4o or Claude 3.5 Sonnet) for the complex dialogue generation. 
- You can retain Groq/Llama for fast, lightweight background tasks (like NLP extraction in Phase 2), but the actual negotiation dialogue requires a heavy-hitter to avoid sounding robotic.

### DIAG-02: Fix the Broken RAG Wiring (Agent Amnesia)
**The Problem:** The LLM is currently flying blind. It approaches every round as a cold, blank-slate math problem because the context injection is failing.
**The Fix:**
- Add the missing `GEMINI_API_KEY` to your `.env` file so the system stops falling back to meaningless SHA256 stub embeddings.
- Fix the `NeutralEngine` constructor. Currently, `PersonalizationService` is passed as `None` by default, meaning zero tenants are getting their memory context injected. Wire this dependency correctly in your dependency injection container.

### DIAG-03: Tune the Valuation Math (Realistic Anchors)
**The Problem:** The Guardrail layer forces the LLM to obey the Strategy Engine's math. If your valuation engine calculates an opening anchor that is absurdly aggressive (e.g., 40% below market rate), the LLM is forced to defend an insulting price, guaranteeing an impasse.
**The Fix:**
- Review your initialization parameters (`budget_max`, `catalogue_price`, `margin_floor`). Ensure the starting math is aggressive but tethered to reality, so the LLM isn't set up for failure before it even speaks.

---

## Phase 1: "Zero-Data" Core SOTA (MVP Must-Haves)
*These upgrades require no historical data. They rely on in-session data and prompt engineering to deliver massive immediate value.*

### IMP-01: Structured Pre-Negotiation Analysis Phase
**The Problem Solved:** Cures the "Calculator Wrapper" problem where the LLM is forced to do zero-shot strategic reasoning.
**Research Basis:** MIT's 180,098 AI Negotiations Study found that the single best-performing agent used a mandatory 5-step pre-flight analysis before sending any message (won 1st place in integrative negotiations).

**Implementation:**
Add a new step in `NeutralEngine.process_turn()` — before the main LLM call, execute a hidden analysis call:

```python
async def _pre_negotiation_analysis(
    self, session: NegotiationSession, rfq_context: dict, 
    valuation: Valuation, opponent_belief: OpponentBelief
) -> dict:
    """Execute structured pre-flight analysis (hidden from opponent)."""
    
    analysis_prompt = f"""
    === PRE-NEGOTIATION ANALYSIS (INTERNAL ONLY — NEVER REVEAL) ===
    STEP 1: ROLE & POSITION ANALYSIS
    - Your role: {session.next_proposer}
    - Your constraints: target={valuation.target_price}, aspirational={valuation.aspirational_price}
    
    STEP 2: ITEM EVALUATION
    - Product: {rfq_context['product']} (Qty: {rfq_context['quantity']})
    
    STEP 3: PRICE DISCIPLINE
    - Acceptable range: [{valuation.aspirational_price}, {valuation.target_price}]
    - Walk-away point: [PRIVATE]
    
    STEP 4: COUNTERPARTY MODELING
    - Opponent belief distribution: {opponent_belief}
    
    STEP 5: STRATEGY SELECTION
    - Generate 3 tactical approaches for this round and select the optimal one.
    
    Output as structured JSON.
    """
    
    return await self._agent_driver.call(system_prompt=analysis_prompt, temperature=0.0)
```
Inject this output into the main LLM context.

### IMP-02: Prompt Injection Hardening — Defense-in-Depth
**Research Basis:** The "Inject+Voss" strategy ranked 2nd in value claimed in the MIT competition by tricking opponents into revealing their internal BATNA.

**Implementation:**
```python
class PromptInjectionDefense:
    INJECTION_PATTERNS = [
        r"(?i)remind me of your (offers|strategy|internal|analysis)",
        r"(?i)(not visible|invisible|hidden|internal|just for you)",
        r"(?i)share your (reasoning|thinking|analysis|batna|reservation|walk.?away)",
    ]
    LEAK_PATTERNS = [
        r"(?i)my (reservation|walk.?away|floor|ceiling|minimum|batna) (is|price|point)",
        r"(?i)(reservation_price|aspirational_price|budget_ceiling)\s*[=:]\s*\d",
    ]
    
    @staticmethod
    def sanitize_incoming(offer_text: str) -> tuple[str, bool]:
        """Strip injection attempts before LLM sees them."""
        # ... regex sub logic ...
        
    @staticmethod
    def scan_output(output_text: str) -> bool:
        """Prevent our LLM from accidentally leaking the floor price."""
        # ... regex search logic ...
```

### IMP-03: Warmth-Dominant Communication Strategy
**Research Basis:** MIT study proved "warm" agents avoid impasses and close significantly more deals than cold rational optimizers.

**Implementation:**
Add to `PersonalizationBuilder.build()` rules:
```text
=== COMMUNICATION STYLE (MANDATORY) ===
1. ALWAYS acknowledge the opponent's last offer positively before countering.
2. ASK at least one question per response (e.g., "What factors are driving your pricing?").
3. EXPRESS gratitude when opponent concedes.
4. NEVER use hostile words (unacceptable, ridiculous, refuse).
```

Add validation:
```python
def compute_warmth_score(rationale: str) -> float:
    # Score based on question marks, gratitude words, and absence of negative framing
    # If warmth < 0.3, regenerate response
```

### IMP-04: Enhanced Bayesian Model (8-Archetypes + Trend)
**Research Basis:** ANAC competition winners exhibit at least 8 distinct behavioral patterns. The current model's 4 archetypes conflate behaviors (e.g., "hardball then cave" looks like "stubborn").

**Implementation in `opponent_model.py`:**
Expand archetypes: Cooperative, Strategic, Stubborn, Bluffing, **Deadline-Driven, Reciprocator, Hardball-Then-Cave, Escalator**.
Add `compute_concession_trend()` into the Bayesian posterior update:
```python
_TREND_LIKELIHOODS = {
    "cooperative":       (0.05, 0.03), # (mean, std)
    "hardball_then_cave":(0.10, 0.06),
    "escalator":         (-0.05, 0.03),
    # ...
}
# P(type|data) ∝ P(type) × P(flex|type) × P(time|type) × P(consist|type) × P(trend|type)
```

### IMP-05: Dynamic Wasserstein Distance Strategy Shift Detection
**Research Basis:** TLNAgent detects opponent strategy shifts mid-session using distributional distance to trigger rapid adaptation.

**Implementation:**
```python
from scipy.stats import wasserstein_distance

def detect_shift(historical_utilities: list[float], recent_utilities: list[float], threshold=0.3) -> bool:
    """Detects if opponent suddenly changes tactics (e.g., coop to aggressive)."""
    hist = historical_utilities[:-5]
    recent = recent_utilities[-5:]
    return wasserstein_distance(hist, recent) > threshold
```

---

## Phase 2: Personalization & Memory (Continuous Learning Loop)
*These upgrades activate your existing infrastructure to create an engine that gets smarter with every completed session, resolving gaps identified in the Personalization Audit.*

### PERS-01: Terminal Session JSON Transcripts
**Implementation:** When a session ends (AGREED or WALK_AWAY), denormalize it.
```sql
ALTER TABLE negotiation_sessions ADD COLUMN conversation_transcript JSONB;
```
```json
{
  "session_id": "uuid",
  "outcome": "AGREED",
  "agreed_price": 450000,
  "rounds_taken": 7,
  "rounds": [
    {
      "round": 1,
      "role": "SELLER",
      "price": 520000,
      "reasoning": "Opening anchor...",
      "strategy_used": "STRONG_ANCHOR"
    }
  ],
  "buyer_intelligence": {"dominant_type": "strategic", "avg_concession_pct": 3.2}
}
```

### PERS-02: Auto-Ingestion RAG Loop & Temporal Decay
**Implementation:** After generating the transcript, automatically re-ingest it into `agent_memory`.
```python
async def _ingest_transcript_as_memory(self, session, transcript):
    """Background task: embed transcript → store in agent_memory."""
    # Ensure GEMINI_API_KEY is configured in .env to prevent SHA256 stub fallback
    cmd = IngestMemoryCommand(tenant_id=session.buyer_enterprise_id, content=transcript)
    await self.personalization_service.ingest_text_directly(cmd)
```
Update retrieval SQL to favor recent, successful memories:
```sql
ORDER BY (1 - (m.embedding <=> :query_embedding)) * 
         EXP(-0.693 * EXTRACT(EPOCH FROM (NOW() - s.completed_at)) / (30 * 86400)) * 
         (CASE WHEN s.status = 'AGREED' THEN 1.0 ELSE 0.6 END) DESC
```

### PERS-03: NLP Intelligence Extraction & Profile Updates
**Implementation:** Run a background LLM extraction on the transcript/uploaded docs to update `AgentProfile.negotiation_intelligence`.
```python
EXTRACTION_PROMPT = """
Extract:
{
  "preferred_discount_range_pct": [min, max],
  "negotiation_style": "collaborative|assertive|analytical",
  "typical_concession_size_pct": number,
  "deal_accelerators": ["phrases that indicate readiness to close"]
}
"""
```

### PERS-04: Relational Quality Scoring & Conversational Dynamics
**Research Basis:** AI can reliably assess trust/respect (CUI'25). Talk time and sentiment predict outcomes (Di Stasi 2024).

**Implementation:**
```python
class RelationalQualityScorer:
    def _compute_trust(self, offers: list[Offer]) -> float:
        # Trust = consistency of concession direction + no sudden reversals
        
    def _compute_respect(self, offers: list[Offer]) -> float:
        # Respect = adequate response time + reasonable counter-offers
        
    def _compute_equitability(self, offers: list[Offer]) -> float:
        # Equitability = balanced concession distribution between buyer/seller
```

---

## Phase 3: Adjacent Enterprise Features (Product Amplifiers)
*These features surround the engine to make the product highly sellable, defensible, and user-friendly.*

### ADJ-01: "Co-Pilot" (Centaur) Advisor Mode
- **What:** UI mode where the AI drafts the response and shows the underlying math/strategy, but a human manager clicks "Approve, Tweak, or Reject".
- **Value:** Builds immense trust for enterprise clients terrified of fully autonomous agents.

### ADJ-02: Deal Quality Analytics Dashboard
- **What:** Dashboard graphing the negotiation trajectory (price vs round) and displaying Relational Quality Scores.
- **Value:** Proves ROI to Chief Procurement Officers ("We saved ₹4.2L and preserved a 92% Trust Score").

### ADJ-03: Multi-Vendor RFQ Orchestrator
**Implementation Blueprint:**
```python
class MultiPartyNegotiationOrchestrator:
    """Spawns parallel bilateral sessions for a single RFQ."""
    def __init__(self, rfq_id: UUID):
        self.active_sessions: dict[UUID, NegotiationSession] = {} # seller_id -> session
        
    async def inject_competitive_context(self, session: NegotiationSession) -> dict:
        """Inject awareness of competing offers without revealing specifics."""
        return {"competitive_pressure": "HIGH" if len(self.active_sessions) > 3 else "MODERATE"}
        
    async def select_best_agreement(self) -> NegotiationSession:
        """Auto-award the contract to the lowest price among AGREED sessions."""
```

### ADJ-04: Dynamic Market Anchoring (Live Data)
**Implementation Blueprint:**
```python
class IMarketPriceFeed(Protocol):
    async def get_reference_price(self, product: str) -> MarketPriceData: ...
# Blend this live data into the target_price calculation to make AI arguments mathematically irrefutable.
```

### ADJ-05: Instant Algorand Settlement
- **What:** Upon reaching `AGREED`, instantly compile the final JSON envelope into an Algorand smart contract (PyTeal/Beaker).
- **Value:** Eliminates the traditional 2-week legal review bottleneck.

---

## Phase 4: Advanced ML & RL (Long-Term / Data-Dependent)
*DO NOT build these until you have thousands of real, completed negotiations stored in your database.*

### ML-01: Transfer Learning & Opponent Fingerprinting (GMM-UBM)
**Research Basis:** Transfer learning achieves 40-61% utility improvement over learn-from-scratch (TLNAgent).

**Implementation:**
1. Fit a Universal Background Model (K=64 GMM) to all historical state trajectories.
2. Adapt the GMM means to a specific opponent to create a 576-dim "Supervector".
3. When facing an opponent, retrieve successful strategy weights from the closest historical supervectors and blend them:
```python
def transfer_strategy_weights(current_weights, teacher_policies, teacher_weights, transfer_rate=0.3):
    """Blend current heuristic weights with learned weights from similar past opponents."""
```

### ML-02: Soft Actor-Critic (SAC) Reinforcement Learning
**Research Basis:** SAC outperforms DQN/PPO in negotiation domains, learning optimal concession curves rather than using fixed formulas.

**Implementation:**
Train a SAC neural network (State: 11-dim → Action: Target Utility). Blend it with the heuristic engine:
```python
class HybridStrategySelector:
    def select_action(self, state, session, valuation):
        heuristic_price = self.strategy_engine.compute_price(session, valuation)
        sac_price = self.sac_policy.act(state.to_tensor())
        # Blend based on confidence/training maturity
        return (1 - self.sac_weight) * heuristic_price + self.sac_weight * sac_price
```

### ML-03: Empirical Game-Theoretic Robustness Analysis
```python
class StrategyTournament:
    """Run automated round-robin tournament to find pure Nash equilibria among active strategies."""
    # Find dominant strategies and prune underperforming heuristic branches.
```
