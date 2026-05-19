# DANP Negotiation Engine — Neutral Protocol Engine (Backbone)
# context.md §6.1: NeutralEngine — stateless protocol enforcer.
# Buyer and seller NEVER communicate directly. ALL exchange flows through here.
#
# Implements the full 4-layer pipeline:
#   Layer 1: VALUATION    → Math only (reservation/target price)
#   Layer 2: STRATEGY     → Game theory (8 strategies)
#   Layer 3: LLM ADVISORY → Classifies opponent
#   Layer 4: GUARDRAIL    → Veto (budget/margin/compliance)
#
# Also handles:
#   - Turn enforcement (strict BUYER→SELLER alternation)
#   - Schema validation (ActionEnvelope)
#   - Metrics computation (flexibility, response time)
#   - Bayesian belief update
#   - Stall/timeout detection
#   - Convergence → AGREED trigger

from __future__ import annotations

import time
from decimal import Decimal

import structlog

from src.negotiation.domain.agent_profile import AgentProfile
from src.negotiation.domain.guardrails import (
    ActionEnvelope,
    GuardrailEngine,
    validate_raw_envelope,
)
from src.negotiation.domain.offer import Offer, ProposerRole
from src.negotiation.domain.opponent_model import (
    BayesianOpponentModel,
    OpponentBelief,
    compute_opponent_metrics,
)
from src.negotiation.domain.playbook import IndustryPlaybook
from src.negotiation.domain.policies import NegotiationPolicy
from src.negotiation.domain.session import (
    CONVERGENCE_TOLERANCE,
    NegotiationSession,
    SessionStatus,
)
from src.negotiation.domain.strategy import StrategyEngine, adaptive_concession
from src.negotiation.domain.valuation import (
    Valuation,
    compute_buyer_valuation,
    compute_buyer_valuation_from_rfq,
    compute_seller_valuation,
    compute_seller_valuation_from_catalogue,
)
from src.negotiation.infrastructure.personalization import PersonalizationBuilder

log = structlog.get_logger(__name__)


class NeutralEngine:
    """
    Neutral Protocol Engine — stateless backbone of the DANP system.

    Implements INeutralEngine protocol.
    All state lives in NegotiationSession — NeutralEngine is pure orchestration.

    4-Layer Pipeline per turn:
      1. Valuation  (deterministic math)
      2. Strategy   (game theory selection)
      3. LLM        (Gemini advisory — opponent classification)
      4. Guardrail  (absolute veto)
    """

    def __init__(
        self,
        agent_driver: object,  # IAgentDriver
        personalization_builder: PersonalizationBuilder | None = None,
        sse_publisher: object | None = None,  # ISSEPublisher
        strategy_engine: StrategyEngine | None = None,
        guardrail_engine: GuardrailEngine | None = None,
        bayesian_model: BayesianOpponentModel | None = None,
        personalization_service: object | None = None,  # PersonalizationService (RAG)
    ) -> None:
        self.agent_driver = agent_driver
        self.personalization = personalization_builder or PersonalizationBuilder()
        self.sse_publisher = sse_publisher
        self.strategy_engine = strategy_engine or StrategyEngine()
        self.guardrail_engine = guardrail_engine or GuardrailEngine()
        self.bayesian_model = bayesian_model or BayesianOpponentModel()
        self.personalization_service = personalization_service
        # Per-session belief cache (session_id → {role → belief})
        self._belief_cache: dict[str, dict[str, OpponentBelief]] = {}

    async def process_turn(
        self,
        session: NegotiationSession,
        buyer_profile: AgentProfile,
        seller_profile: AgentProfile,
        buyer_playbook: IndustryPlaybook | None,
        seller_playbook: IndustryPlaybook | None,
        rfq_parsed_fields: dict | None = None,
        catalogue_price: Decimal | None = None,
    ) -> tuple[Offer, bool]:
        """
        Execute one full negotiation turn through the 4-layer pipeline.

        Returns (offer, is_terminal).
        """
        turn_start = time.monotonic()

        # 0. Check timeout
        if session.is_expired():
            return self._create_timeout_offer(session), True

        # 1. Determine whose turn
        current_role = self._determine_turn(session)
        current_profile = (
            buyer_profile if current_role == ProposerRole.BUYER else seller_profile
        )
        current_playbook = (
            buyer_playbook if current_role == ProposerRole.BUYER else seller_playbook
        )
        is_buyer = current_role == ProposerRole.BUYER

        # 2. Check turn order
        NegotiationPolicy.check_turn_order(session.offers, current_role.value)

        # ── ZOPA PRE-CHECK (round 0 only) ──────────────────────────────────────
        # Detect no Zone of Possible Agreement before running any rounds.
        if session.round_count.value == 0:
            buyer_val = self._compute_valuation(
                buyer_profile, True, rfq_parsed_fields, catalogue_price
            )
            seller_val = self._compute_valuation(
                seller_profile, False, rfq_parsed_fields, catalogue_price
            )
            if buyer_val.reservation_price < seller_val.reservation_price:
                gap = seller_val.reservation_price - buyer_val.reservation_price
                log.warning(
                    "no_zopa_detected",
                    buyer_ceiling=float(buyer_val.reservation_price),
                    seller_floor=float(seller_val.reservation_price),
                    gap=float(gap),
                    session_id=str(session.id),
                )
                return self._create_no_zopa_offer(
                    session, current_role,
                    seller_target=seller_val.target_price,
                    buyer_ceiling=buyer_val.reservation_price,
                    seller_floor=seller_val.reservation_price,
                ), True

        # ── LAYER 1: VALUATION ──
        valuation = self._compute_valuation(
            current_profile, is_buyer,
            rfq_parsed_fields=rfq_parsed_fields,
            catalogue_price=catalogue_price,
        )

        # ── LAYER 2: STRATEGY ──
        opponent_prices = (
            session.get_seller_prices() if is_buyer else session.get_buyer_prices()
        )
        my_prices = (
            session.get_buyer_prices() if is_buyer else session.get_seller_prices()
        )

        # Get Bayesian belief for opponent
        belief = self._get_or_compute_belief(session, current_role, opponent_prices)

        strategy_rec = self.strategy_engine.select_strategy(
            round_num=session.round_count.value,
            my_last_price=my_prices[-1] if my_prices else None,
            opponent_last_price=opponent_prices[-1] if opponent_prices else None,
            reservation_price=valuation.reservation_price,
            target_price=valuation.target_price,
            opponent_flexibility=belief.cooperative + belief.strategic * 0.5,
            rounds_since_concession=session.stall_counter,
            time_remaining_pct=self._time_remaining_pct(session),
            is_buyer=is_buyer,
        )

        # Apply Bayesian modifier to concession
        modifier = self.bayesian_model.strategy_modifier(belief)
        if strategy_rec.concession_fraction > Decimal("0"):
            adjusted_concession = adaptive_concession(
                strategy_rec.concession_fraction,
                opponent_flexibility=belief.cooperative,
                opponent_type=belief.dominant_type.value,
            )
        else:
            adjusted_concession = Decimal("0")

        # ── LAYER 3: LLM ADVISORY ──

        # ── RAG MEMORY INJECTION (before system prompt so it can be embedded) ──
        memory_chunks: list[str] = []
        if self.personalization_service is not None:
            try:
                enterprise_id = (
                    session.buyer_enterprise_id
                    if is_buyer
                    else session.seller_enterprise_id
                )
                product_hint = (rfq_parsed_fields or {}).get("product", "")
                rag_query = (
                    f"Negotiation for {product_hint or 'commodity'} "
                    f"RFQ {session.rfq_id} "
                    f"round {session.round_count.value} "
                    f"price range {strategy_rec.suggested_price}"
                )
                memory_chunks = await self.personalization_service.retrieve_context_for_negotiation(
                    tenant_id=enterprise_id,
                    session_context=rag_query,
                    limit=5,
                ) or []
                if memory_chunks:
                    log.info(
                        "rag_context_injected",
                        enterprise_id=str(enterprise_id),
                        chunks=len(memory_chunks),
                    )
            except Exception as e:
                log.warning("rag_retrieval_failed", error=str(e))

        # ── Build rfq_context dict for system prompt + user message ──
        rfq_ctx: dict | None = None
        if rfq_parsed_fields:
            rfq_ctx = {
                "product": rfq_parsed_fields.get("product") or rfq_parsed_fields.get("commodity_code"),
                "quantity": rfq_parsed_fields.get("quantity"),
                "quantity_unit": rfq_parsed_fields.get("quantity_unit", "units"),
                "total_budget_inr": rfq_parsed_fields.get("budget_max"),
            }
            # For the seller agent: expose per-unit price and total cost basis so the
            # LLM anchors correctly and never negotiates below its own cost floor.
            if not is_buyer and catalogue_price is not None:
                quantity_for_ctx = rfq_parsed_fields.get("quantity")
                rfq_ctx["catalogue_unit_price"] = float(catalogue_price)
                if quantity_for_ctx is not None and Decimal(str(quantity_for_ctx)) > 0:
                    rfq_ctx["total_cost_basis"] = float(
                        catalogue_price * Decimal(str(quantity_for_ctx))
                    )

        system_prompt = self.personalization.build(
            profile=current_profile,
            playbook=current_playbook,
            role=current_role.value,
            memory_context=memory_chunks if memory_chunks else None,
            rfq_context=rfq_ctx,
        )
        offer_history = self._serialize_offer_history(session.offers)
        session_context: dict = {
            "session_id": str(session.id),
            "round_count": session.round_count.value,
            "rfq_id": str(session.rfq_id),
            "strategy_suggestion": strategy_rec.strategy.value,
            "suggested_price": float(strategy_rec.suggested_price),
            "suggested_price_basis": "INR total order value (NOT per-unit)",
            # Explicit valuation bounds so the LLM doesn't have to guess its own limits.
            # reservation_price = absolute walk-away point (buyer: max to pay; seller: min to accept).
            # target_price      = ideal outcome (buyer: ideal low; seller: ideal high).
            # BUYER rule: if opponent's price <= your_target_price_inr → ACCEPT immediately.
            # SELLER rule: if opponent's price >= your_target_price_inr → ACCEPT immediately.
            "your_reservation_price_inr": float(valuation.reservation_price),
            "your_target_price_inr": float(valuation.target_price),
            "opponent_belief": belief.to_dict(),
            "concession_modifier": float(adjusted_concession),
        }

        # Inject rfq_context into user message as well for full LLM clarity
        if rfq_ctx:
            session_context["rfq_context"] = rfq_ctx

        # ── LOGISTICS CONTEXT (from match scoring) ──
        logistics_context = self._get_logistics_context(session)

        try:
            raw_output = await self.agent_driver.generate_offer(  # type: ignore[union-attr]
                system_prompt=system_prompt,
                session_context=session_context,
                offer_history=offer_history,
                logistics_context=logistics_context,
            )
        except Exception as llm_err:
            # LLM unavailable (rate-limit, timeout, exhausted retries).
            # Fall back to the strategy-recommended price so the session
            # continues rather than crashing mid-negotiation.
            log.warning(
                "llm_fallback_to_strategy",
                error=str(llm_err),
                strategy_price=float(strategy_rec.suggested_price),
            )
            raw_output = {
                "action": "OFFER",
                "price": float(strategy_rec.suggested_price),
                "reasoning": "LLM unavailable — strategy fallback price used.",
                "confidence": 0.5,
            }

        action = raw_output.get("action", "OFFER").upper()
        llm_price = Decimal(str(raw_output.get("price", strategy_rec.suggested_price)))
        confidence = raw_output.get("confidence", 0.5)
        reasoning = raw_output.get("reasoning", "")

        # ── LAYER 4: GUARDRAIL VETO ──
        # Use strategy price as fallback if LLM price violates guardrails.
        # For the buyer ceiling: prefer RFQ budget_max over the stale profile
        # default so the guardrail matches the real negotiation constraint.
        rfq_budget_max = (
            Decimal(str(rfq_parsed_fields["budget_max"]))
            if rfq_parsed_fields and rfq_parsed_fields.get("budget_max")
            else None
        )
        effective_budget_ceiling = (
            rfq_budget_max if (is_buyer and rfq_budget_max)
            else current_profile.risk_profile.budget_ceiling
        )

        final_price = llm_price
        is_terminal = False

        if action in ("OFFER", "COUNTER"):
            # Construct envelope for guardrail validation
            envelope = ActionEnvelope(
                session_id=session.id,
                agent_role=current_role.value.lower(),
                round=session.round_count.value + 1,
                action=action.lower(),
                offer_value=llm_price,
                confidence=confidence,
                strategy_tag=strategy_rec.strategy.value,
                rationale=reasoning,
            )

            violations = self.guardrail_engine.validate_envelope(
                envelope=envelope,
                reservation_price=valuation.reservation_price,
                budget_ceiling=(
                    effective_budget_ceiling if is_buyer else None
                ),
                margin_floor=(
                    current_profile.risk_profile.margin_floor if not is_buyer else None
                ),
            )

            if violations:
                # Use strategy-recommended price instead
                log.warning(
                    "guardrail_override",
                    violations=[v.message for v in violations],
                    llm_price=float(llm_price),
                    strategy_price=float(strategy_rec.suggested_price),
                )
                final_price = strategy_rec.suggested_price
                reasoning = f"Guardrail override: {reasoning}"

                # Record schema failure if needed
                if session.record_schema_failure():
                    return self._create_policy_breach_offer(session, current_role), True

            # Budget guard for buyer — use RFQ budget if available, else profile default
            if is_buyer:
                try:
                    NegotiationPolicy.check_budget_guard(
                        final_price, effective_budget_ceiling
                    )
                except Exception:
                    final_price = min(
                        final_price, effective_budget_ceiling
                    )

        elif action == "ACCEPT":
            # Accept the last counter from other side
            last_counter = (
                session.get_last_seller_offer()
                if is_buyer
                else session.get_last_buyer_offer()
            )
            final_price = last_counter.price.amount if last_counter else llm_price
            is_terminal = True

        elif action == "REJECT":
            final_price = (
                llm_price if llm_price > Decimal("0") else Decimal("1")
            )
            is_terminal = True

        else:
            # Unknown action — treat as counter
            action = "COUNTER"

        # ── CROSSED ZOPA CHECK ───────────────────────────────────────────────────
        # If the current side's price has crossed the opponent's last price,
        # settle immediately at the opponent's price — no point continuing.
        #
        # Cases:
        #   Buyer bids ₹8.5L when seller already quoted ₹3.5L → buyer overpays;
        #   settle at ₹3.5L and save the buyer money.
        #
        #   Seller quotes ₹3.5L when buyer last bid ₹8.5L → seller undercuts;
        #   settle at ₹3.5L (seller's own price).
        if action in ("OFFER", "COUNTER") and not is_terminal:
            other_last = (
                session.get_last_seller_offer() if is_buyer
                else session.get_last_buyer_offer()
            )
            if other_last is not None:
                other_price = other_last.price.amount
                if (is_buyer and final_price >= other_price) or \
                   (not is_buyer and final_price <= other_price):
                    settle_price = other_price if is_buyer else final_price
                    final_price = settle_price
                    action = "ACCEPT"
                    is_terminal = True
                    reasoning = (
                        f"Prices crossed — instant agreement at "
                        f"\u20b9{float(settle_price):,.0f}. "
                        + ("Buyer offer exceeds seller ask."
                           if is_buyer else "Seller price is below buyer bid.")
                    )
                    log.info(
                        "crossed_zopa_instant_agreement",
                        settled_price=float(settle_price),
                        buyer_price=float(final_price if is_buyer else other_price),
                        seller_price=float(other_price if is_buyer else final_price),
                        session_id=str(session.id),
                    )

        # Create the offer
        offer = Offer.create_agent_offer(
            session_id=session.id,
            round_number=session.round_count.value + 1,
            proposer_role=current_role,
            price=final_price,
            currency="INR",
            terms={},
            confidence=confidence,
            agent_reasoning=f"{action}: {reasoning}" if action == "REJECT" else reasoning,
        )

        # Track concession / stall
        if not is_terminal and action in ("OFFER", "COUNTER"):
            self._track_concession(session, current_role, final_price)

        # Check convergence after non-terminal offers
        if not is_terminal and action in ("OFFER", "COUNTER"):
            last_buyer = session.get_last_buyer_offer()
            last_seller = session.get_last_seller_offer()
            b_price = (
                final_price if is_buyer else (last_buyer.price.amount if last_buyer else None)
            )
            s_price = (
                final_price if not is_buyer else (last_seller.price.amount if last_seller else None)
            )
            if NegotiationPolicy.check_convergence(b_price, s_price):
                is_terminal = True
                # Override reasoning so the UI shows convergence clearly
                # instead of the LLM's "I will make a counteroffer..." message.
                if b_price and s_price:
                    gap_pct = abs(s_price - b_price) / min(b_price, s_price) * 100
                    agreed_at = min(b_price, s_price) if is_buyer else max(b_price, s_price)
                    reasoning = (
                        f"Prices converged — deal reached at "
                        f"\u20b9{float(final_price):,.0f}. "
                        f"Gap closed to {float(gap_pct):.1f}% (within 2% threshold)."
                    )

        # Terminate only on genuine deadlock or the absolute round ceiling.
        # - stall_counter >= STALL_ROUNDS: neither side has moved meaningfully
        #   for 3 consecutive rounds → real deadlock, no point continuing.
        # - round_count >= MAX_ROUNDS: absolute safety net (20 rounds).
        #
        # The old total-rounds >= stall_threshold check was a blunt timer that
        # killed converging deals at round 10. stall_counter is reset every time
        # any side makes a meaningful concession (>0.2% move), so it only fires
        # when negotiation has genuinely ground to a halt.
        if not is_terminal:
            from src.negotiation.domain.session import MAX_ROUNDS, STALL_ROUNDS
            if session.stall_counter >= STALL_ROUNDS:
                is_terminal = True
                log.info(
                    "negotiation_stalled_no_concession",
                    stall_counter=session.stall_counter,
                    round=session.round_count.value + 1,
                    session_id=str(session.id),
                )
            elif session.round_count.value + 1 >= MAX_ROUNDS:
                is_terminal = True
                log.info(
                    "negotiation_max_rounds_reached",
                    round=session.round_count.value + 1,
                    session_id=str(session.id),
                )

        # Update Bayesian belief
        self._update_belief_cache(session, current_role, opponent_prices)

        # SSE publishing is handled by NegotiationService.run_agent_turn()
        # to avoid duplicate events reaching the frontend.

        return offer, is_terminal

    # ── Intelligence Methods (for Debug API) ──────────────────────────────────

    def get_session_intelligence(
        self, session: NegotiationSession
    ) -> dict:
        """
        Return intelligence data for the debug endpoint.

        Includes:
        - Current Bayesian beliefs for both sides
        - Flexibility scores
        - Strategy recommendations
        - Stall/convergence status
        """
        sid = str(session.id)
        buyer_prices = session.get_buyer_prices()
        seller_prices = session.get_seller_prices()

        buyer_metrics = compute_opponent_metrics(buyer_prices) if buyer_prices else None
        seller_metrics = compute_opponent_metrics(seller_prices) if seller_prices else None

        # Get cached beliefs or compute
        beliefs = self._belief_cache.get(sid, {})
        buyer_belief = beliefs.get("buyer", BayesianOpponentModel.PRIOR)
        seller_belief = beliefs.get("seller", BayesianOpponentModel.PRIOR)

        if buyer_metrics:
            buyer_belief = self.bayesian_model.update_belief(buyer_metrics)
        if seller_metrics:
            seller_belief = self.bayesian_model.update_belief(seller_metrics)

        return {
            "session_id": sid,
            "round_count": session.round_count.value,
            "status": session.status.value,
            "buyer_intelligence": {
                "belief": buyer_belief.to_dict(),
                "dominant_type": buyer_belief.dominant_type.value,
                "confidence": buyer_belief.confidence,
                "flexibility": (
                    buyer_metrics.flexibility_score if buyer_metrics else None
                ),
                "consistency": (
                    buyer_metrics.consistency if buyer_metrics else None
                ),
                "prices": [float(p) for p in buyer_prices],
            },
            "seller_intelligence": {
                "belief": seller_belief.to_dict(),
                "dominant_type": seller_belief.dominant_type.value,
                "confidence": seller_belief.confidence,
                "flexibility": (
                    seller_metrics.flexibility_score if seller_metrics else None
                ),
                "consistency": (
                    seller_metrics.consistency if seller_metrics else None
                ),
                "prices": [float(p) for p in seller_prices],
            },
            "convergence": session.check_convergence(),
            "stall_counter": session.stall_counter,
            "schema_failures": session.schema_failure_count,
        }

    # ── Private Helpers ───────────────────────────────────────────────────────

    def _determine_turn(self, session: NegotiationSession) -> ProposerRole:
        """Determine whose turn it is next."""
        return session.next_proposer

    def _compute_valuation(
        self,
        profile: AgentProfile,
        is_buyer: bool,
        rfq_parsed_fields: dict | None = None,
        catalogue_price: Decimal | None = None,
    ) -> Valuation:
        """
        Layer 1: Compute valuation from transactional context (RFQ + catalogue).

        Primary path: derive intrinsic_value from rfq quantity × unit_rate,
        then use compute_buyer_valuation_from_rfq / compute_seller_valuation_from_catalogue.

        Fallback path: budget_ceiling-based derivation (for freeform sessions
        without an RFQ or when parsed_fields lack required keys).
        """
        # ── Primary path: RFQ budget data (most reliable) ──
        if rfq_parsed_fields is not None and is_buyer:
            budget_min = rfq_parsed_fields.get("budget_min")
            budget_max = rfq_parsed_fields.get("budget_max")

            if budget_max is not None:
                # Use RFQ budget directly — this is the buyer's stated constraint
                if budget_min is None:
                    budget_min = Decimal(str(budget_max)) * Decimal("0.80")
                val = compute_buyer_valuation_from_rfq(
                    budget_min=Decimal(str(budget_min)),
                    budget_max=Decimal(str(budget_max)),
                    risk_appetite=profile.risk_profile.risk_appetite,
                )
                log.info(
                    "valuation_computed",
                    source="rfq_budget",
                    role="buyer",
                    budget_min=str(budget_min),
                    budget_max=str(budget_max),
                    reservation=str(val.reservation_price),
                    target=str(val.target_price),
                )
                return val

        # ── Secondary path: RFQ quantity × unit_rate ──
        try:
            if rfq_parsed_fields is not None:
                quantity_raw = rfq_parsed_fields.get("quantity")
                unit_rate_raw = rfq_parsed_fields.get("unit_rate")
                if quantity_raw is not None and unit_rate_raw is not None:
                    quantity = Decimal(str(quantity_raw))
                    unit_rate = Decimal(str(unit_rate_raw))
                    intrinsic_value = quantity * unit_rate

                    if is_buyer:
                        val = compute_buyer_valuation(
                            fair_price=intrinsic_value,
                            risk_appetite=profile.risk_profile.risk_appetite,
                            budget_ceiling=profile.risk_profile.budget_ceiling,
                        )
                    else:
                        if catalogue_price is not None:
                            # catalogue_price is per-unit — scale to total order value
                            # so the seller's floor is on the same basis as the buyer's budget.
                            cost_basis = catalogue_price * quantity
                        else:
                            cost_basis = intrinsic_value
                        val = compute_seller_valuation_from_catalogue(
                            catalogue_price=cost_basis,
                            margin_floor=profile.risk_profile.margin_floor,
                            risk_appetite=profile.risk_profile.risk_appetite,
                        )
                    log.info(
                        "valuation_computed",
                        source="rfq_catalogue",
                        role="buyer" if is_buyer else "seller",
                        intrinsic=str(intrinsic_value),
                        reservation=str(val.reservation_price),
                        target=str(val.target_price),
                    )
                    return val

                # Seller path: use budget_max from RFQ as market reference,
                # modulated by the match score so different sellers negotiate
                # from different starting points (better matches → more competitive).
                if not is_buyer and rfq_parsed_fields.get("budget_max") is not None:
                    market_ref = Decimal(str(rfq_parsed_fields["budget_max"]))
                    if catalogue_price is not None:
                        # catalogue_price is per-unit — multiply by order quantity
                        # to get total cost basis comparable to the buyer's budget.
                        quantity_raw_b = rfq_parsed_fields.get("quantity")
                        if quantity_raw_b is not None and Decimal(str(quantity_raw_b)) > 0:
                            cost_basis = catalogue_price * Decimal(str(quantity_raw_b))
                        else:
                            # No usable quantity — derive from budget with match_score heuristic
                            match_score = Decimal(str(rfq_parsed_fields.get("_match_score", 0.5)))
                            cost_basis = market_ref * (Decimal("0.85") - Decimal("0.25") * match_score)
                    else:
                        # No catalogue price — use match_score to differentiate sellers.
                        # Higher match score → lower cost basis → more competitive pricing.
                        # Score 1.0 → 60% of budget, score 0.5 → 72.5% of budget.
                        match_score = Decimal(str(
                            rfq_parsed_fields.get("_match_score", 0.5)
                        ))
                        cost_factor = Decimal("0.85") - Decimal("0.25") * match_score
                        cost_basis = market_ref * cost_factor
                    val = compute_seller_valuation_from_catalogue(
                        catalogue_price=cost_basis,
                        margin_floor=profile.risk_profile.margin_floor,
                        risk_appetite=profile.risk_profile.risk_appetite,
                    )
                    log.info(
                        "valuation_computed",
                        source="rfq_budget_seller",
                        role="seller",
                        cost_basis=str(cost_basis),
                        reservation=str(val.reservation_price),
                        target=str(val.target_price),
                    )
                    return val

        except (KeyError, TypeError, ValueError, ArithmeticError) as e:
            log.warning(
                "valuation_rfq_fallback",
                source="budget_ceiling_fallback",
                reason=str(e),
            )

        # ── Fallback path: budget_ceiling-based derivation ──
        if is_buyer:
            return compute_buyer_valuation(
                fair_price=profile.risk_profile.budget_ceiling * Decimal("0.80"),
                risk_appetite=profile.risk_profile.risk_appetite,
                budget_ceiling=profile.risk_profile.budget_ceiling,
            )
        else:
            # Use match_score to differentiate sellers even in fallback path.
            match_score = Decimal("0.5")
            if rfq_parsed_fields and "_match_score" in rfq_parsed_fields:
                match_score = Decimal(str(rfq_parsed_fields["_match_score"]))
            # Higher match score → lower cost basis → more competitive pricing
            cost_factor = Decimal("0.75") - Decimal("0.15") * match_score
            cost_basis = profile.risk_profile.budget_ceiling * cost_factor
            return compute_seller_valuation(
                cost_basis=cost_basis,
                margin_floor=profile.risk_profile.margin_floor,
                risk_appetite=profile.risk_profile.risk_appetite,
            )

    def _get_or_compute_belief(
        self,
        session: NegotiationSession,
        current_role: ProposerRole,
        opponent_prices: list[Decimal],
    ) -> OpponentBelief:
        """Get cached belief or compute fresh from opponent prices."""
        sid = str(session.id)
        role_key = current_role.value.lower()

        if sid in self._belief_cache and role_key in self._belief_cache[sid]:
            prior = self._belief_cache[sid][role_key]
        else:
            prior = BayesianOpponentModel.PRIOR

        if len(opponent_prices) < 2:
            return prior

        metrics = compute_opponent_metrics(opponent_prices)
        return self.bayesian_model.update_belief(metrics, prior)

    def _update_belief_cache(
        self,
        session: NegotiationSession,
        current_role: ProposerRole,
        opponent_prices: list[Decimal],
    ) -> None:
        """Update the belief cache after a turn."""
        if len(opponent_prices) < 2:
            return

        sid = str(session.id)
        role_key = current_role.value.lower()

        if sid not in self._belief_cache:
            self._belief_cache[sid] = {}

        metrics = compute_opponent_metrics(opponent_prices)
        prior = self._belief_cache[sid].get(role_key, BayesianOpponentModel.PRIOR)
        self._belief_cache[sid][role_key] = self.bayesian_model.update_belief(
            metrics, prior
        )

    def _track_concession(
        self,
        session: NegotiationSession,
        role: ProposerRole,
        new_price: Decimal,
    ) -> None:
        """Track whether a meaningful concession was made."""
        is_buyer = role == ProposerRole.BUYER
        my_prices = (
            session.get_buyer_prices() if is_buyer else session.get_seller_prices()
        )
        if not my_prices:
            session.reset_stall_counter()
            return

        last_price = my_prices[-1]
        if last_price == Decimal("0"):
            session.reset_stall_counter()
            return

        change = abs(new_price - last_price) / last_price
        if change < 0.002:  # Less than 0.2% change = no concession
            session.record_no_concession()
        else:
            session.reset_stall_counter()

    def _time_remaining_pct(self, session: NegotiationSession) -> float:
        """Fraction of max rounds remaining."""
        from src.negotiation.domain.session import MAX_ROUNDS

        used = session.round_count.value
        return max(0.0, (MAX_ROUNDS - used) / MAX_ROUNDS)

    def _serialize_offer_history(self, offers: list[Offer]) -> list[dict]:
        """Serialize last 20 offers for LLM context (no PII)."""
        return [
            {
                "round": o.round_number.value,
                "role": o.proposer_role.value,
                "price": float(o.price.amount),
                "terms": o.terms,
                "is_human": o.is_human_override,
            }
            for o in offers[-20:]
        ]

    def _get_logistics_context(self, session: NegotiationSession) -> dict | None:
        """
        Build logistics context from match scoring data.

        Uses the match's stored delivery estimates (computed during matching).
        Returns None if no delivery data is available (falls back to standard negotiation).
        """
        try:
            # Synchronous access to match data stored on session metadata
            # The match scoring data is persisted in the matches table
            # For now, we use the session's rfq_id to signal logistics awareness
            # A more complete implementation would query the match row
            return None  # Will be populated when match data is passed through
        except Exception:
            return None

    def _create_no_zopa_offer(
        self,
        session: NegotiationSession,
        role: ProposerRole,
        seller_target: Decimal | None = None,
        buyer_ceiling: Decimal | None = None,
        seller_floor: Decimal | None = None,
    ) -> Offer:
        """Create a REJECT offer when no Zone of Possible Agreement exists at round 0.

        Uses the seller's actual asking price so judges can see the gap clearly
        instead of a meaningless ₹1 placeholder.
        """
        # Show seller's real catalog price so the rejection is self-explanatory.
        display_price = seller_target if seller_target is not None else Decimal("1")

        if buyer_ceiling is not None and seller_floor is not None:
            gap = seller_floor - buyer_ceiling
            gap_pct = float(gap / seller_floor * 100) if seller_floor > 0 else 0
            # Prefix with WALK_AWAY so NegotiationService routes this to _handle_walk_away
            reasoning = (
                f"WALK_AWAY: No deal possible — Seller's minimum "
                f"\u20b9{float(seller_floor):,.0f} exceeds Buyer's budget "
                f"\u20b9{float(buyer_ceiling):,.0f}. "
                f"Gap: \u20b9{float(gap):,.0f} ({gap_pct:.1f}%) — walking away."
            )
        else:
            reasoning = (
                "WALK_AWAY: No Zone of Possible Agreement detected. "
                "Buyer's maximum price is below seller's minimum acceptable price. "
                "Walking away rather than forcing an uneconomical deal."
            )

        return Offer.create_agent_offer(
            session_id=session.id,
            round_number=session.round_count.value + 1,
            proposer_role=role,
            price=display_price,
            currency="INR",
            terms={},
            confidence=1.0,
            agent_reasoning=reasoning,
        )

    def _create_timeout_offer(
        self, session: NegotiationSession
    ) -> Offer:
        """Create a placeholder offer for timeout termination."""
        return Offer.create_agent_offer(
            session_id=session.id,
            round_number=session.round_count.value + 1,
            proposer_role=session.next_proposer,
            price=Decimal("1"),
            currency="INR",
            terms={},
            confidence=0.0,
            agent_reasoning="TIMEOUT: Session TTL expired.",
        )

    def _create_policy_breach_offer(
        self, session: NegotiationSession, role: ProposerRole
    ) -> Offer:
        """Create a placeholder offer for policy breach termination."""
        return Offer.create_agent_offer(
            session_id=session.id,
            round_number=session.round_count.value + 1,
            proposer_role=role,
            price=Decimal("1"),
            currency="INR",
            terms={},
            confidence=0.0,
            agent_reasoning="POLICY_BREACH: Schema validation failed 3 times.",
        )
