# NegotiationService — orchestrates all negotiation use cases.
# context.md §1.4 DIP: receives all dependencies via constructor.
# Updated for DANP FSM with full 9-state support.

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import structlog

from src.negotiation.application.commands import (
    CreateSessionCommand,
    HumanOverrideCommand,
    TerminateSessionCommand,
)
from src.negotiation.domain.agent_profile import AgentProfile
from src.negotiation.domain.events import (
    HumanOverrideApplied,
)
from src.negotiation.domain.offer import Offer, ProposerRole
from src.negotiation.domain.session import NegotiationSession, SessionStatus
from src.negotiation.domain.value_objects import OfferValue
from src.negotiation.infrastructure.llm_agent_driver import LLMExhaustedException
from src.shared.domain.exceptions import ConflictError, NotFoundError, PolicyViolation
from src.shared.infrastructure.metrics import (
    ACTIVE_SESSIONS,
    NEGOTIATION_ROUNDS_TOTAL,
    NEGOTIATION_SESSION_DURATION,
)

log = structlog.get_logger(__name__)

SESSION_TTL_HOURS = 24
MAX_ROUNDS = 20


def _build_transcript_text(transcript: dict) -> str:
    """Convert transcript dict to text for RAG ingestion."""
    lines = [
        f"Session {transcript.get('session_id', 'unknown')} — {transcript.get('outcome', 'unknown')}",
        f"Rounds: {transcript.get('rounds_taken', 0)}",
        f"Agreed price: {transcript.get('agreed_price', 'N/A')}",
        "",
        "Offer sequence:",
    ]
    for r in transcript.get("rounds", []):
        lines.append(
            f"  Round {r['round']} [{r['role']}]: ₹{r['price']:,.0f}"
            + (f" — {r['reasoning'][:100]}" if r.get("reasoning") else "")
        )
    return "\n".join(lines)


class NegotiationService:
    """Orchestrates negotiation lifecycle. All ports injected via constructor (DIP)."""

    def __init__(
        self,
        session_repo: object,
        offer_repo: object,
        profile_repo: object,
        playbook_repo: object,
        neutral_engine: object,
        sse_publisher: object,
        event_publisher: object,
        uow: object,
        session_ttl_hours: int = SESSION_TTL_HOURS,
        max_rounds: int = MAX_ROUNDS,
        personalization_service: object | None = None,
    ) -> None:
        self.session_repo = session_repo
        self.offer_repo = offer_repo
        self.profile_repo = profile_repo
        self.playbook_repo = playbook_repo
        self.neutral_engine = neutral_engine
        self.sse_publisher = sse_publisher
        self.event_publisher = event_publisher
        self.uow = uow
        self.session_ttl_hours = session_ttl_hours
        self.max_rounds = max_rounds
        self.personalization_service = personalization_service

    async def create_session(self, cmd: CreateSessionCommand) -> NegotiationSession:
        """Create a new negotiation session from a marketplace match."""
        # Idempotency check
        existing = await self.session_repo.get_by_match_id(cmd.match_id)  # type: ignore[union-attr]
        if existing:
            raise ConflictError(f"Session already exists for match_id {cmd.match_id}")

        # Self-dealing guard — enterprise cannot negotiate with itself
        if cmd.buyer_enterprise_id == cmd.seller_enterprise_id:
            raise PolicyViolation("Self-dealing is not permitted: buyer and seller are the same enterprise")

        # Load or create default agent profiles
        buyer_profile = await self.profile_repo.get_by_enterprise(cmd.buyer_enterprise_id)  # type: ignore[union-attr]
        if not buyer_profile:
            buyer_profile = AgentProfile(enterprise_id=cmd.buyer_enterprise_id)
            await self.profile_repo.save(buyer_profile)  # type: ignore[union-attr]

        seller_profile = await self.profile_repo.get_by_enterprise(cmd.seller_enterprise_id)  # type: ignore[union-attr]
        if not seller_profile:
            seller_profile = AgentProfile(enterprise_id=cmd.seller_enterprise_id)
            await self.profile_repo.save(seller_profile)  # type: ignore[union-attr]

        # Create session in INIT state (DANP)
        session = NegotiationSession(
            rfq_id=cmd.rfq_id,
            match_id=cmd.match_id,
            buyer_enterprise_id=cmd.buyer_enterprise_id,
            seller_enterprise_id=cmd.seller_enterprise_id,
            status=SessionStatus.INIT,
            expires_at=datetime.now(tz=timezone.utc) + timedelta(hours=self.session_ttl_hours),
            # Store per-product override for multi-product RFQs
            product_context=cmd.override_rfq_parsed_fields,
        )

        # Activate: INIT → SELLER_ANCHOR (seller quotes catalog price first)
        created_event = session.activate()

        await self.session_repo.save(session)  # type: ignore[union-attr]
        await self.uow.commit()  # type: ignore[union-attr]

        # Publish SessionCreated
        await self.event_publisher.publish(created_event)  # type: ignore[union-attr]

        # Prometheus: track active session count
        ACTIVE_SESSIONS.inc()

        log.info("session_created", session_id=str(session.id), match_id=str(cmd.match_id),
                 status=session.status.value)
        return session

    async def _load_rfq_and_catalogue(
        self, session: NegotiationSession
    ) -> tuple[dict | None, Decimal | None]:
        """
        Load RFQ parsed_fields and best catalogue_price for this session.

        Returns (rfq_parsed_fields, catalogue_price).
        Both may be None if data is unavailable (freeform sessions).
        """
        rfq_parsed_fields: dict | None = None
        catalogue_price: Decimal | None = None

        # Use per-product context override when this session was created from
        # a multi-product RFQ (e.g. camera + tripod + lens → separate sessions).
        # This ensures each session negotiates the correct product/budget,
        # not the RFQ's primary product.
        product_ctx = getattr(session, "product_context", None)

        try:
            # Access the underlying DB session from session_repo
            db_session = self.session_repo.get_db_session()  # type: ignore[union-attr]
            from sqlalchemy import select as sa_select

            # 1. Load RFQ parsed_fields (or use per-product override)
            from src.marketplace.infrastructure.models import RFQModel
            rfq_result = await db_session.execute(
                sa_select(RFQModel.parsed_fields).where(RFQModel.id == session.rfq_id)
            )
            rfq_row = rfq_result.scalar_one_or_none()
            if rfq_row and isinstance(rfq_row, dict):
                rfq_parsed_fields = rfq_row

            # Override with per-product context if this is a multi-product session.
            # Merge: start with RFQ base fields, then overlay product-specific ones.
            if product_ctx:
                base = dict(rfq_parsed_fields) if rfq_parsed_fields else {}
                base.update({k: v for k, v in product_ctx.items() if v is not None})
                rfq_parsed_fields = base
                log.info(
                    "rfq_product_context_applied",
                    session_id=str(session.id),
                    product=product_ctx.get("product"),
                    budget_max=product_ctx.get("budget_max"),
                )

            # 2. Load this seller's match record (contains matched_catalogue_item_id)
            from src.marketplace.infrastructure.models import CatalogueItemModel, MatchModel
            match_result = await db_session.execute(
                sa_select(MatchModel).where(
                    MatchModel.rfq_id == session.rfq_id,
                    MatchModel.seller_enterprise_id == session.seller_enterprise_id,
                ).limit(1)
            )
            match_row = match_result.scalar_one_or_none()

            # Inject match score into rfq_parsed_fields for valuation layer
            if rfq_parsed_fields is not None and match_row:
                rfq_parsed_fields = dict(rfq_parsed_fields)
                rfq_parsed_fields["_match_score"] = float(
                    match_row.composite_score or match_row.similarity_score or 0.5
                    if hasattr(match_row, "similarity_score") else
                    match_row.composite_score or 0.5
                )

            # ── Fix 2: 4-tier priority catalogue selection ────────────────────
            # Priority 1: exact item recorded during matchmaking (most accurate)
            selected_item = None
            if match_row and match_row.matched_catalogue_item_id:
                item_result = await db_session.execute(
                    sa_select(CatalogueItemModel).where(
                        CatalogueItemModel.id == match_row.matched_catalogue_item_id,
                        CatalogueItemModel.is_active == True,  # noqa: E712
                    )
                )
                selected_item = item_result.scalar_one_or_none()
                if selected_item:
                    log.info(
                        "catalogue_selection_matched_item",
                        session_id=str(session.id),
                        item_name=selected_item.product_name,
                        tier=1,
                    )

            # Priority 2: fuzzy product name match from RFQ parsed_fields
            if selected_item is None and rfq_parsed_fields:
                rfq_product = (
                    rfq_parsed_fields.get("product") or
                    rfq_parsed_fields.get("product_name") or ""
                ).strip()
                if rfq_product:
                    name_result = await db_session.execute(
                        sa_select(CatalogueItemModel).where(
                            CatalogueItemModel.enterprise_id == session.seller_enterprise_id,
                            CatalogueItemModel.is_active == True,  # noqa: E712
                            CatalogueItemModel.product_name.ilike(f"%{rfq_product}%"),
                        ).order_by(CatalogueItemModel.price_per_unit_inr.asc()).limit(1)
                    )
                    selected_item = name_result.scalar_one_or_none()
                    if selected_item:
                        log.info(
                            "catalogue_selection_name_match",
                            session_id=str(session.id),
                            item_name=selected_item.product_name,
                            rfq_product=rfq_product,
                            tier=2,
                        )

            # Priority 3: exact HSN code match
            if selected_item is None and rfq_parsed_fields:
                rfq_hsn = (rfq_parsed_fields.get("hsn_code") or "").strip()
                if rfq_hsn:
                    hsn_result = await db_session.execute(
                        sa_select(CatalogueItemModel).where(
                            CatalogueItemModel.enterprise_id == session.seller_enterprise_id,
                            CatalogueItemModel.is_active == True,  # noqa: E712
                            CatalogueItemModel.hsn_code == rfq_hsn,
                        ).order_by(CatalogueItemModel.price_per_unit_inr.asc()).limit(1)
                    )
                    selected_item = hsn_result.scalar_one_or_none()
                    if selected_item:
                        log.info(
                            "catalogue_selection_hsn_match",
                            session_id=str(session.id),
                            item_name=selected_item.product_name,
                            hsn=rfq_hsn,
                            tier=3,
                        )

            # Priority 4: item closest to buyer's implied unit budget
            if selected_item is None:
                budget_max = float(rfq_parsed_fields.get("budget_max") or 0) if rfq_parsed_fields else 0
                quantity = float(rfq_parsed_fields.get("quantity") or 1) if rfq_parsed_fields else 1
                all_items_result = await db_session.execute(
                    sa_select(CatalogueItemModel).where(
                        CatalogueItemModel.enterprise_id == session.seller_enterprise_id,
                        CatalogueItemModel.is_active == True,  # noqa: E712
                    )
                )
                all_items = all_items_result.scalars().all()
                if all_items:
                    if budget_max and quantity:
                        target_unit = budget_max / quantity
                        selected_item = min(
                            all_items,
                            key=lambda i: abs(float(i.price_per_unit_inr) - target_unit),
                        )
                        log.info(
                            "catalogue_selection_budget_closest",
                            session_id=str(session.id),
                            item_name=selected_item.product_name,
                            target_unit=target_unit,
                            tier=4,
                        )
                    else:
                        # Absolute fallback: cheapest (original behaviour)
                        selected_item = min(all_items, key=lambda i: float(i.price_per_unit_inr))
                        log.info(
                            "catalogue_selection_cheapest_fallback",
                            session_id=str(session.id),
                            item_name=selected_item.product_name,
                            tier="fallback",
                        )

            if selected_item is not None:
                catalogue_price = Decimal(str(selected_item.price_per_unit_inr))
                # Inject item identity into rfq_parsed_fields for LLM context (Fix 4)
                if rfq_parsed_fields is not None:
                    rfq_parsed_fields["_matched_item_name"] = selected_item.product_name
                    rfq_parsed_fields["_matched_item_hsn"] = selected_item.hsn_code
                    rfq_parsed_fields["_matched_item_grade"] = selected_item.grade
                    rfq_parsed_fields["_matched_item_spec"] = (
                        selected_item.specification_text[:300]
                        if selected_item.specification_text else None
                    )

        except Exception:
            log.warning(
                "rfq_catalogue_load_failed",
                session_id=str(session.id),
                rfq_id=str(session.rfq_id),
                exc_info=True,
            )


        return rfq_parsed_fields, catalogue_price

    async def run_agent_turn(self, session_id: uuid.UUID) -> Offer:
        """Execute one turn of the negotiation (4-layer pipeline via NeutralEngine)."""
        session = await self.session_repo.get_by_id(session_id)  # type: ignore[union-attr]
        if not session:
            raise NotFoundError("NegotiationSession", session_id)

        # Check if session accepts turns
        if not session.status.is_active:
            raise ConflictError(f"Session {session_id} is {session.status.value}, cannot run turn")

        # Check timeout
        if session.is_expired():
            await self._handle_timeout(session)
            raise ConflictError(f"Session {session_id} has expired (TIMEOUT)")

        buyer_profile = await self.profile_repo.get_by_enterprise(  # type: ignore[union-attr]
            session.buyer_enterprise_id
        ) or AgentProfile(enterprise_id=session.buyer_enterprise_id)
        seller_profile = await self.profile_repo.get_by_enterprise(  # type: ignore[union-attr]
            session.seller_enterprise_id
        ) or AgentProfile(enterprise_id=session.seller_enterprise_id)

        # Load transactional context first — needed to determine commodity vertical for playbook
        rfq_parsed_fields, catalogue_price = await self._load_rfq_and_catalogue(session)

        # ── NEG-05: Load vertical-specific playbook with "general" fallback ──
        # Determine vertical from RFQ data (industry-agnostic — works for any commodity)
        vertical: str | None = None
        if rfq_parsed_fields:
            # Try industry_vertical first, then commodity_code, then product
            raw_vertical = (
                rfq_parsed_fields.get("industry_vertical")
                or rfq_parsed_fields.get("commodity_code")
                or rfq_parsed_fields.get("product")
            )
            if raw_vertical:
                vertical = str(raw_vertical).lower().replace("_", " ").strip()

        buyer_playbook = None
        if vertical:
            buyer_playbook = await self.playbook_repo.get_by_vertical(vertical)  # type: ignore[union-attr]
        if buyer_playbook is None:
            buyer_playbook = await self.playbook_repo.get_by_vertical("general")  # type: ignore[union-attr]

        # Give seller their own playbook lookup (same vertical; distinct object if DB has one)
        seller_playbook = None
        if vertical:
            seller_playbook = await self.playbook_repo.get_by_vertical(vertical)  # type: ignore[union-attr]
        if seller_playbook is None:
            seller_playbook = await self.playbook_repo.get_by_vertical("general")  # type: ignore[union-attr]

        try:
            offer, is_terminal = await self.neutral_engine.process_turn(  # type: ignore[union-attr]
                session=session,
                buyer_profile=buyer_profile,
                seller_profile=seller_profile,
                buyer_playbook=buyer_playbook,
                seller_playbook=seller_playbook,
                rfq_parsed_fields=rfq_parsed_fields,
                catalogue_price=catalogue_price,
            )
        except LLMExhaustedException:
            log.warning("llm_exhausted_policy_breach", session_id=str(session_id))
            await self._handle_policy_breach(session)
            if self.sse_publisher:
                await self.sse_publisher.publish_turn(  # type: ignore[union-attr]
                    session_id,
                    {
                        "event": "llm_unavailable",
                        "reason": "All LLM API keys exhausted",
                        "session_id": str(session_id),
                    },
                )
            await self.uow.commit()  # type: ignore[union-attr]
            raise ConflictError(
                f"Session {session_id}: LLM unavailable (quota exhausted on all keys)"
            )

        # Add offer to session and persist
        offer_event = session.add_offer(offer)
        await self.offer_repo.save(offer)  # type: ignore[union-attr]
        await self.session_repo.update(session)  # type: ignore[union-attr]
        await self.event_publisher.publish(offer_event)  # type: ignore[union-attr]

        # SSE: stream every offer to the frontend in real-time
        if self.sse_publisher:
            await self.sse_publisher.publish_turn(  # type: ignore[union-attr]
                session_id,
                {
                    "event": "new_offer",
                    "offer": {
                        "offer_id": str(offer.id),
                        "round_number": offer.round_number.value if hasattr(offer.round_number, 'value') else offer.round_number,
                        "proposer_role": offer.proposer_role.value if hasattr(offer.proposer_role, 'value') else str(offer.proposer_role),
                        "price": float(offer.price.amount) if hasattr(offer.price, 'amount') else float(offer.price),
                        "currency": getattr(offer.price, 'currency', 'INR'),
                        "terms": offer.terms or {},
                        "confidence": float(offer.confidence.value) if offer.confidence and hasattr(offer.confidence, 'value') else (float(offer.confidence) if offer.confidence else None),
                        "agent_reasoning": offer.agent_reasoning,
                        "is_human_override": offer.is_human_override,
                    },
                    "session_id": str(session_id),
                    "is_terminal": is_terminal,
                },
            )

        if is_terminal:
            reasoning = offer.agent_reasoning or ""
            ru = reasoning.upper()
            if "REJECT" in ru or "WALK_AWAY" in ru:
                await self._handle_walk_away(session, f"Agent rejected at round {session.round_count.value}")
            elif "POLICY_BREACH" in ru:
                await self._handle_policy_breach(session)
            elif "STALL_TERMINAL" in ru:
                await self._handle_stall(session)
            elif "MAX_ROUNDS" in ru:
                await self._handle_timeout(session)
            elif "TIMEOUT" in ru and "MAX_ROUNDS" not in ru:
                await self._handle_timeout(session)
            elif session.stall_counter >= 3:
                await self._handle_stall(session)
            else:
                await self._handle_agreement(session, offer, buyer_profile, seller_profile)

        await self.uow.commit()  # type: ignore[union-attr]
        return offer

    async def _handle_agreement(
        self,
        session: NegotiationSession,
        offer: Offer,
        buyer_profile: AgentProfile,
        seller_profile: AgentProfile,
    ) -> None:
        """ROUND_LOOP → AGREED: convergence detected."""
        # Agreed price = max(current offer, seller's last offer).
        # When buyer's offer triggers convergence the offer.price is the buyer's
        # lower bid, but neutral_engine already sets final_price=max(b,s) AFTER
        # creating the offer — so the offer.price doesn't reflect the update.
        # Fix: re-compute here to guarantee seller never settles below their floor.
        seller_last = session.get_last_seller_offer()
        agreed_amount = (
            max(offer.price.amount, seller_last.price.amount)
            if seller_last else offer.price.amount
        )
        agreed_price = OfferValue(amount=agreed_amount, currency="INR")
        event = session.mark_agreed(agreed_price, {})

        # Compute deal quality score (buyer's share of ZOPA surplus, 0.0–1.0)
        # Read ZOPA values from session.opponent_beliefs["_zopa"] — persisted by neutral_engine
        try:
            zopa_data = (session.opponent_beliefs or {}).get("_zopa", {})
            if not zopa_data:
                # Fallback: try in-memory cache (same process only)
                zopa_data = getattr(self.neutral_engine, '_zopa_cache', {}).get(str(session.id), {})
            buyer_ceiling = zopa_data.get('buyer_ceiling')
            seller_floor = zopa_data.get('seller_floor')
            if buyer_ceiling and seller_floor:
                bc = float(buyer_ceiling)
                sf = float(seller_floor)
                zopa_range = abs(bc - sf)
                if zopa_range > 0:
                    buyer_gain = bc - float(agreed_amount)
                    session.deal_quality_score = round(max(0.0, min(1.0, buyer_gain / zopa_range)), 4)
        except Exception:
            pass  # Non-fatal

        # Build conversation transcript for RAG re-ingestion
        transcript = None
        try:
            transcript = session.build_conversation_transcript()
            session.conversation_transcript = transcript
        except Exception as _e:
            pass  # Non-fatal — transcript is best-effort

        # Background: ingest transcript into pgvector for future RAG context
        if hasattr(self, 'personalization_service') and self.personalization_service is not None and transcript is not None:
            try:
                import asyncio as _asyncio
                transcript_text = _build_transcript_text(transcript)
                _asyncio.create_task(
                    self.personalization_service.ingest_text_directly(  # type: ignore[union-attr]
                        tenant_id=session.buyer_enterprise_id,
                        text=transcript_text,
                        role="buyer",
                        metadata={"session_id": str(session.id), "outcome": session.status.value},
                    )
                )
                _asyncio.create_task(
                    self.personalization_service.ingest_text_directly(  # type: ignore[union-attr]
                        tenant_id=session.seller_enterprise_id,
                        text=transcript_text,
                        role="seller",
                        metadata={"session_id": str(session.id), "outcome": session.status.value},
                    )
                )
            except Exception:
                pass  # Background ingestion is non-fatal

        await self.session_repo.update(session)  # type: ignore[union-attr]
        await self.event_publisher.publish(event)  # type: ignore[union-attr]

        # Prometheus: session completed — decrement active, observe duration, record round outcome
        ACTIVE_SESSIONS.dec()
        if session.created_at:
            duration = (time.time() - session.created_at.timestamp())
            NEGOTIATION_SESSION_DURATION.observe(duration)
        NEGOTIATION_ROUNDS_TOTAL.labels(outcome="accept").inc()

        if self.sse_publisher:
            await self.sse_publisher.publish_terminal(  # type: ignore[union-attr]
                session.id,
                # BUG-04 FIX: use agreed_amount (max of buyer bid / seller ask),
                # NOT offer.price.amount which is only the buyer's lower bid.
                {"event": "session_agreed", "agreed_price": float(agreed_amount), "session_id": str(session.id)},
            )

        # Update profiles (learning via EMA)
        for profile in [buyer_profile, seller_profile]:
            profile.update_after_session(
                session_agreed=True,
                rounds_taken=session.round_count.value,
                final_price=agreed_amount,
                budget_ceiling=profile.risk_profile.budget_ceiling,
            )
            await self.profile_repo.update(profile)  # type: ignore[union-attr]

        log.info("session_agreed", session_id=str(session.id), price=float(agreed_amount))

    async def _handle_walk_away(self, session: NegotiationSession, reason: str) -> None:
        """ROUND_LOOP → WALK_AWAY: agent rejected."""
        event = session.mark_walk_away(reason)

        # Build conversation transcript for RAG re-ingestion
        try:
            transcript = session.build_conversation_transcript()
            session.conversation_transcript = transcript
        except Exception as _e:
            pass  # Non-fatal — transcript is best-effort

        await self.session_repo.update(session)  # type: ignore[union-attr]
        await self.event_publisher.publish(event)  # type: ignore[union-attr]

        # Prometheus: terminal state
        ACTIVE_SESSIONS.dec()
        NEGOTIATION_ROUNDS_TOTAL.labels(outcome="reject").inc()

        if self.sse_publisher:
            await self.sse_publisher.publish_terminal(  # type: ignore[union-attr]
                session.id,
                {"event": "session_failed", "reason": f"WALK_AWAY: {reason}", "session_id": str(session.id)},
            )
        log.info("session_walk_away", session_id=str(session.id), reason=reason)

    async def _handle_failure(self, session: NegotiationSession, reason: str) -> None:
        """Generic failure handler (backward compat)."""
        event = session.mark_failed(reason)
        await self.session_repo.update(session)  # type: ignore[union-attr]
        await self.event_publisher.publish(event)  # type: ignore[union-attr]

        if self.sse_publisher:
            await self.sse_publisher.publish_terminal(  # type: ignore[union-attr]
                session.id,
                {"event": "session_failed", "reason": reason, "session_id": str(session.id)},
            )
        log.info("session_failed", session_id=str(session.id), reason=reason)

    async def _handle_stall(self, session: NegotiationSession) -> None:
        """ROUND_LOOP → STALLED → HUMAN_REVIEW."""
        stall_event = session.mark_stalled()
        escalation_event = session.escalate_to_human_review()
        await self.session_repo.update(session)  # type: ignore[union-attr]
        await self.event_publisher.publish(escalation_event)  # type: ignore[union-attr]

        # Prometheus: stall detection
        NEGOTIATION_ROUNDS_TOTAL.labels(outcome="stall").inc()

        if self.sse_publisher:
            await self.sse_publisher.publish_turn(  # type: ignore[union-attr]
                session.id,
                {"event": "stall_detected", "reason": "stall_detected",
                 "round": session.round_count.value, "session_id": str(session.id)},
            )
        log.info("session_stalled", session_id=str(session.id))

    async def _handle_timeout(self, session: NegotiationSession) -> None:
        """ROUND_LOOP → TIMEOUT: TTL expired."""
        event = session.mark_timeout()
        await self.session_repo.update(session)  # type: ignore[union-attr]
        await self.event_publisher.publish(event)  # type: ignore[union-attr]

        # Prometheus: terminal state
        ACTIVE_SESSIONS.dec()
        NEGOTIATION_ROUNDS_TOTAL.labels(outcome="timeout").inc()

        if self.sse_publisher:
            await self.sse_publisher.publish_terminal(  # type: ignore[union-attr]
                session.id,
                {"event": "round_timeout", "timeout_round": session.round_count.value, "session_id": str(session.id)},
            )
        log.info("session_timeout", session_id=str(session.id))

    async def _handle_policy_breach(self, session: NegotiationSession) -> None:
        """ROUND_LOOP → POLICY_BREACH: 3x schema failures."""
        event = session.mark_policy_breach()
        await self.session_repo.update(session)  # type: ignore[union-attr]
        await self.event_publisher.publish(event)  # type: ignore[union-attr]

        if self.sse_publisher:
            await self.sse_publisher.publish_terminal(  # type: ignore[union-attr]
                session.id,
                {"event": "session_failed", "reason": "POLICY_BREACH: Schema validation failed 3x", "session_id": str(session.id)},
            )
        log.info("session_policy_breach", session_id=str(session.id))

    async def apply_human_override(self, cmd: HumanOverrideCommand) -> Offer:
        """Human injects an offer mid-session, overriding the agent."""
        session = await self.session_repo.get_by_id(cmd.session_id)  # type: ignore[union-attr]
        if not session:
            raise NotFoundError("NegotiationSession", cmd.session_id)

        if session.status == SessionStatus.HUMAN_REVIEW:
            session.resume_from_human_review()
        elif session.status == SessionStatus.STALLED:
            session.resume_from_human_review()  # STALLED → will go through escalation first
        elif not session.status.is_active:
            raise ConflictError(f"Session {cmd.session_id} is {session.status.value}")

        # BUG-08 FIX: Determine the correct role from the user's enterprise ID.
        # Previously hardcoded to BUYER, preventing sellers from submitting overrides.
        if cmd.enterprise_id == session.buyer_enterprise_id:
            override_role = ProposerRole.BUYER
        elif cmd.enterprise_id == session.seller_enterprise_id:
            override_role = ProposerRole.SELLER
        else:
            raise ConflictError("User's enterprise is not a party to this session")

        current_round = session.round_count.value + 1
        offer = Offer.create_human_offer(
            session_id=session.id,
            round_number=current_round,
            proposer_role=override_role,
            price=cmd.price,
            currency=cmd.currency,
            terms=cmd.terms,
        )

        offer_event = session.add_offer(offer)
        await self.offer_repo.save(offer)  # type: ignore[union-attr]
        await self.session_repo.update(session)  # type: ignore[union-attr]
        await self.uow.commit()  # type: ignore[union-attr]

        # Publish events
        await self.event_publisher.publish(offer_event)  # type: ignore[union-attr]
        override_event = HumanOverrideApplied(
            aggregate_id=session.id,
            event_type="HumanOverrideApplied",
            session_id=session.id,
            offer_id=offer.id,
            price=cmd.price,
            applied_by_user_id=cmd.user_id,
        )
        await self.event_publisher.publish(override_event)  # type: ignore[union-attr]

        if self.sse_publisher:
            await self.sse_publisher.publish_turn(  # type: ignore[union-attr]
                session.id,
                {"event": "override", "price": float(cmd.price), "by": "human",
                 "session_id": str(session.id)},
            )

        log.info("human_override_applied", session_id=str(session.id), price=float(cmd.price))
        return offer

    async def terminate_session(self, cmd: TerminateSessionCommand) -> None:
        """Admin terminates a session."""
        session = await self.session_repo.get_by_id(cmd.session_id)  # type: ignore[union-attr]
        if not session:
            raise NotFoundError("NegotiationSession", cmd.session_id)

        event = session.mark_failed(cmd.reason)
        await self.session_repo.update(session)  # type: ignore[union-attr]
        await self.uow.commit()  # type: ignore[union-attr]
        await self.event_publisher.publish(event)  # type: ignore[union-attr]

        if self.sse_publisher:
            await self.sse_publisher.publish_terminal(  # type: ignore[union-attr]
                session.id,
                {"event": "session_failed", "reason": f"TERMINATED: {cmd.reason}", "session_id": str(session.id)},
            )
        log.info("session_terminated", session_id=str(session.id))

    async def get_session_intelligence(self, session_id: uuid.UUID) -> dict:
        """Get intelligence data for the debug endpoint."""
        session = await self.session_repo.get_by_id(session_id)  # type: ignore[union-attr]
        if not session:
            raise NotFoundError("NegotiationSession", session_id)

        return self.neutral_engine.get_session_intelligence(session)  # type: ignore[union-attr]

    async def cleanup_expired_sessions(self) -> int:
        """Expire sessions that have passed their TTL."""
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=self.session_ttl_hours)
        candidates = await self.session_repo.list_expired_candidates(cutoff)  # type: ignore[union-attr]
        count = 0
        for session in candidates[:100]:
            try:
                event = session.mark_expired()
                await self.session_repo.update(session)  # type: ignore[union-attr]
                await self.event_publisher.publish(event)  # type: ignore[union-attr]
                count += 1
            except Exception:
                log.exception("cleanup_expired_error", session_id=str(session.id))
        if count > 0:
            await self.uow.commit()  # type: ignore[union-attr]
        log.info("cleanup_expired_sessions", expired_count=count)
        return count
