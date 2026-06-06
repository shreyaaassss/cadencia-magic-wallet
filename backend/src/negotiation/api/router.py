# context.md §4: API prefix /v1/*, API-first modular monolith.
# Phase Four: Six negotiation routes + SSE streaming endpoint.
# Updated for DANP with intelligence debug endpoint.

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from src.identity.api.dependencies import get_current_user, require_role
from src.identity.domain.user import User
from src.negotiation.api.dependencies import get_negotiation_service, get_sse_publisher
from src.negotiation.api.schemas import (
    CreateSessionRequest,
    HumanOverrideRequest,
    OfferResponse,
    SessionResponse,
    TerminateRequest,
)
from src.negotiation.application.commands import (
    CreateSessionCommand,
    HumanOverrideCommand,
    TerminateSessionCommand,
)
from src.negotiation.application.services import NegotiationService
from src.shared.api.responses import success_response

router = APIRouter(prefix="/v1/sessions", tags=["negotiation"])

# FSM states the frontend sees as "ACTIVE"
_FRONTEND_ACTIVE_STATES = {
    "INIT",
    "SELLER_ANCHOR", "BUYER_RESPONSE",   # new FSM
    "BUYER_ANCHOR", "SELLER_RESPONSE",   # legacy
    "ROUND_LOOP", "ACTIVE",
}


def _simplify_status(raw: str) -> str:
    """Map internal DANP FSM states to frontend-friendly status strings."""
    if raw in _FRONTEND_ACTIVE_STATES:
        return "ACTIVE"
    return raw


def _redact_deal_quality_for_party(
    dqs: dict | float | None, is_buyer: bool
) -> dict | float | None:
    """Redact deal_quality_score so each party only sees their own surplus.

    Prevents reverse-engineering of the opponent's reservation price.
    """
    if dqs is None or not isinstance(dqs, dict):
        return dqs
    if is_buyer:
        return {
            "score": dqs.get("score"),
            "your_savings_inr": dqs.get("buyer_surplus_inr"),
            "agreed_price_inr": dqs.get("agreed_price_inr"),
            "zopa_position_pct": dqs.get("zopa_position_pct"),
        }
    return {
        "score": dqs.get("score"),
        "your_margin_inr": dqs.get("seller_surplus_inr"),
        "agreed_price_inr": dqs.get("agreed_price_inr"),
        "zopa_position_pct": dqs.get("zopa_position_pct"),
    }


def _session_to_response(
    session: object, viewer_enterprise_id: uuid.UUID | None = None
) -> SessionResponse:
    """Map domain NegotiationSession to API response.

    When viewer_enterprise_id is provided, filters agent_reasoning so each
    party only sees their own agent's reasoning (opponent's is redacted).
    """
    # Determine viewer's role for reasoning redaction
    viewer_role: str | None = None
    if viewer_enterprise_id is not None:
        if viewer_enterprise_id == getattr(session, "buyer_enterprise_id", None):
            viewer_role = "buyer"
        else:
            viewer_role = "seller"

    offers = []
    for o in getattr(session, "offers", []):
        # Redact opponent's agent_reasoning — it may contain internal strategy
        # details, price floors, or cost information private to the other party.
        if viewer_role is not None and o.proposer_role.value != viewer_role:
            reasoning = None
        else:
            reasoning = o.agent_reasoning
        offers.append(OfferResponse(
            offer_id=o.id,
            session_id=o.session_id,
            round_number=o.round_number.value,
            proposer_role=o.proposer_role.value,
            price=o.price.amount,
            currency=o.price.currency,
            terms=o.terms,
            confidence=o.confidence.value if o.confidence else None,
            is_human_override=o.is_human_override,
            agent_reasoning=reasoning,
            created_at=o.created_at,
        ))

    raw_dqs = getattr(session, "deal_quality_score", None)
    if viewer_enterprise_id is not None:
        is_buyer = viewer_role == "buyer"
        redacted_dqs = _redact_deal_quality_for_party(raw_dqs, is_buyer)
    else:
        redacted_dqs = raw_dqs

    return SessionResponse(
        session_id=session.id,  # type: ignore[union-attr]
        rfq_id=session.rfq_id,  # type: ignore[union-attr]
        match_id=session.match_id,  # type: ignore[union-attr]
        buyer_enterprise_id=session.buyer_enterprise_id,  # type: ignore[union-attr]
        seller_enterprise_id=session.seller_enterprise_id,  # type: ignore[union-attr]
        status=_simplify_status(session.status.value),  # type: ignore[union-attr]
        agreed_price=session.agreed_price.amount if session.agreed_price else None,  # type: ignore[union-attr]
        agreed_currency=session.agreed_price.currency if session.agreed_price else None,  # type: ignore[union-attr]
        agreed_terms=session.agreed_terms,  # type: ignore[union-attr]
        round_count=session.round_count.value,  # type: ignore[union-attr]
        offers=offers,
        created_at=session.created_at,  # type: ignore[union-attr]
        completed_at=session.completed_at,  # type: ignore[union-attr]
        expires_at=session.expires_at,  # type: ignore[union-attr]
        schema_failure_count=getattr(session, "schema_failure_count", 0),
        stall_counter=getattr(session, "stall_counter", 0),
        deal_quality_score=redacted_dqs,
        product_context=getattr(session, "product_context", None),
    )


@router.get("")
async def list_sessions(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    svc: NegotiationService = Depends(get_negotiation_service),
    user: object = Depends(get_current_user),
) -> dict:
    """GET /v1/sessions — list negotiation sessions for current user's enterprise."""
    enterprise_id = getattr(user, "enterprise_id", None)
    sessions = await svc.session_repo.list_by_enterprise(
        enterprise_id=enterprise_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    items = [_session_to_response(s, viewer_enterprise_id=enterprise_id).model_dump(mode="json") for s in sessions]

    # Enrich with enterprise names for the table display
    ent_ids = set()
    for item in items:
        ent_ids.add(item["buyer_enterprise_id"])
        ent_ids.add(item["seller_enterprise_id"])
    if ent_ids:
        try:
            db_session = svc.session_repo._session  # type: ignore[union-attr]
            from sqlalchemy import select as sa_select

            from src.identity.infrastructure.models import EnterpriseModel
            result = await db_session.execute(
                sa_select(EnterpriseModel.id, EnterpriseModel.name)
                .where(EnterpriseModel.id.in_(ent_ids))
            )
            name_map = {str(row.id): row.name for row in result.fetchall()}
            for item in items:
                item["buyer_name"] = name_map.get(item["buyer_enterprise_id"], "")
                item["seller_name"] = name_map.get(item["seller_enterprise_id"], "")
        except Exception:
            pass  # Non-fatal — names are optional enrichment

    return success_response(data=items)


@router.post("", status_code=201)
async def create_session(
    body: CreateSessionRequest,
    svc: NegotiationService = Depends(get_negotiation_service),
    _user: object = Depends(get_current_user),
) -> dict:
    """POST /v1/sessions — create negotiation session."""
    cmd = CreateSessionCommand(
        match_id=body.match_id,
        rfq_id=body.rfq_id,
        buyer_enterprise_id=body.buyer_enterprise_id,
        seller_enterprise_id=body.seller_enterprise_id,
    )
    session = await svc.create_session(cmd)
    return success_response(data=_session_to_response(session).model_dump(mode="json"))


@router.get("/{session_id}")
async def get_session(
    session_id: uuid.UUID,
    svc: NegotiationService = Depends(get_negotiation_service),
    user: User = Depends(get_current_user),
) -> dict:
    """GET /v1/sessions/{id} — full session state + offer history."""
    from src.shared.domain.exceptions import NotFoundError
    session = await svc.session_repo.get_by_id(session_id)  # type: ignore[union-attr]
    if not session:
        raise NotFoundError("NegotiationSession", session_id)
    if user.enterprise_id not in (session.buyer_enterprise_id, session.seller_enterprise_id):
        raise HTTPException(status_code=403, detail="Access denied")
    return success_response(data=_session_to_response(session, viewer_enterprise_id=user.enterprise_id).model_dump(mode="json"))


@router.post("/{session_id}/turn")
async def run_turn(
    session_id: uuid.UUID,
    preview: bool = False,
    svc: NegotiationService = Depends(get_negotiation_service),
    user: User = Depends(get_current_user),
) -> dict:
    """POST /v1/sessions/{id}/turn — trigger one agent turn."""
    from src.shared.domain.exceptions import NotFoundError
    session = await svc.session_repo.get_by_id(session_id)  # type: ignore[union-attr]
    if not session:
        raise NotFoundError("NegotiationSession", session_id)
    if user.enterprise_id not in (session.buyer_enterprise_id, session.seller_enterprise_id):
        raise HTTPException(status_code=403, detail="Access denied")
    offer = await svc.run_agent_turn(session_id)
    resp = OfferResponse(
        offer_id=offer.id,
        session_id=offer.session_id,
        round_number=offer.round_number.value,
        proposer_role=offer.proposer_role.value,
        price=offer.price.amount,
        currency=offer.price.currency,
        terms=offer.terms,
        confidence=offer.confidence.value if offer.confidence else None,
        is_human_override=offer.is_human_override,
        agent_reasoning=offer.agent_reasoning,
        created_at=offer.created_at,
    )

    # Co-pilot preview mode: return draft offer without persisting
    if preview:
        return success_response({
            "preview": True,
            "draft_price": float(offer.price.amount),
            "draft_action": str(offer.proposer_role.value),
            "reasoning": offer.agent_reasoning or "",
            "strategy": str(getattr(offer, "_strategy_rec", None) and offer._strategy_rec.strategy.value) if hasattr(offer, "_strategy_rec") else "unknown",
            "hint": "Call this endpoint without preview=true to accept this offer, or POST /override with your adjusted price.",
        })

    return success_response(data=resp.model_dump(mode="json"))


@router.post("/{session_id}/run-auto")
async def run_auto_negotiation(
    session_id: uuid.UUID,
    max_rounds: int = Query(default=20, ge=1, le=50, description="Maximum rounds to execute"),
    svc: NegotiationService = Depends(get_negotiation_service),
    user: User = Depends(get_current_user),
):
    """
    POST /v1/sessions/{id}/run-auto — Run autonomous agent-vs-agent negotiation.

    Executes buyer/seller turns in a loop until a terminal state is reached
    (AGREED, WALK_AWAY, TIMEOUT, POLICY_BREACH, FAILED) or max_rounds is exhausted.
    Returns the final session state with full offer history.
    """
    from src.shared.domain.exceptions import ConflictError, NotFoundError

    session = await svc.session_repo.get_by_id(session_id)  # type: ignore[union-attr]
    if not session:
        raise NotFoundError("NegotiationSession", session_id)
    if user.enterprise_id not in (session.buyer_enterprise_id, session.seller_enterprise_id):
        raise HTTPException(status_code=403, detail="Access denied")

    # Distributed lock: prevent concurrent run-auto for same session
    from src.shared.infrastructure.cache.redis_client import get_redis_client
    lock_key = f"negotiation:run_auto:{session_id}"
    redis_client = get_redis_client()
    lock = redis_client.lock(lock_key, timeout=300)  # 5-min max hold
    if not await lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="Negotiation automation already running for this session. Try again shortly.",
        )
    try:
        offers_this_run: list[OfferResponse] = []
        terminal = False

        import structlog
        _auto_log = structlog.get_logger("negotiation.run_auto")

        import os as _os
        # BUG-11 FIX: rate-limit between turns so rapid-fire auto-negotiation doesn't
        # exhaust all Groq API keys simultaneously. Default 1.5s lets ~40 RPM budget
        # be spread across keys. Set AUTO_TURN_DELAY_SECONDS=0 to disable in tests.
        _inter_turn_delay = float(_os.getenv("AUTO_TURN_DELAY_SECONDS", "1.5"))

        for round_num in range(max_rounds):
            # Check if session is still active before each turn
            session = await svc.session_repo.get_by_id(session_id)  # type: ignore[union-attr]
            if not session or not session.status.is_active:
                terminal = True
                break

            try:
                offer = await svc.run_agent_turn(session_id)
                offers_this_run.append(OfferResponse(
                    offer_id=offer.id,
                    session_id=offer.session_id,
                    round_number=offer.round_number.value,
                    proposer_role=offer.proposer_role.value,
                    price=offer.price.amount,
                    currency=offer.price.currency,
                    terms=offer.terms,
                    confidence=offer.confidence.value if offer.confidence else None,
                    is_human_override=offer.is_human_override,
                    agent_reasoning=offer.agent_reasoning,
                    created_at=offer.created_at,
                ))
            except ConflictError:
                # Session transitioned to terminal state during this turn
                terminal = True
                break
            except Exception as exc:
                _auto_log.error(
                    "run_auto_turn_failed",
                    session_id=str(session_id),
                    round_num=round_num,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                break

            # Reload session to check terminal status after the turn
            session = await svc.session_repo.get_by_id(session_id)  # type: ignore[union-attr]
            if session and not session.status.is_active:
                terminal = True
                break

            # Apply inter-turn delay (skip after last iteration)
            if _inter_turn_delay > 0 and round_num < max_rounds - 1:
                await asyncio.sleep(_inter_turn_delay)

        # Reload final session state
        session = await svc.session_repo.get_by_id(session_id)  # type: ignore[union-attr]
        if not session:
            raise NotFoundError("NegotiationSession", session_id)

        return success_response(data={
            "session": _session_to_response(session, viewer_enterprise_id=user.enterprise_id).model_dump(mode="json"),
            "rounds_executed": len(offers_this_run),
            "terminal": terminal,
            "final_status": _simplify_status(session.status.value),
            "offers_this_run": [o.model_dump(mode="json") for o in offers_this_run],
        })
    finally:
        try:
            await lock.release()
        except Exception:
            pass


@router.post("/{session_id}/override")
async def human_override(
    session_id: uuid.UUID,
    body: HumanOverrideRequest,
    svc: NegotiationService = Depends(get_negotiation_service),
    user: User = Depends(get_current_user),
) -> dict:
    """POST /v1/sessions/{id}/override — human injects offer mid-session."""
    from src.shared.domain.exceptions import NotFoundError
    session = await svc.session_repo.get_by_id(session_id)  # type: ignore[union-attr]
    if not session:
        raise NotFoundError("NegotiationSession", session_id)
    if user.enterprise_id not in (session.buyer_enterprise_id, session.seller_enterprise_id):
        raise HTTPException(status_code=403, detail="Access denied")
    cmd = HumanOverrideCommand(
        session_id=session_id,
        price=body.price,
        currency=body.currency,
        terms=body.terms,
        user_id=getattr(user, "id", uuid.uuid4()),
        enterprise_id=getattr(user, "enterprise_id", uuid.uuid4()),
    )
    offer = await svc.apply_human_override(cmd)
    resp = OfferResponse(
        offer_id=offer.id,
        session_id=offer.session_id,
        round_number=offer.round_number.value,
        proposer_role=offer.proposer_role.value,
        price=offer.price.amount,
        currency=offer.price.currency,
        terms=offer.terms,
        confidence=None,
        is_human_override=True,
        agent_reasoning=None,
        created_at=offer.created_at,
    )
    return success_response(data=resp.model_dump(mode="json"))


@router.post("/{session_id}/terminate")
async def terminate_session(
    session_id: uuid.UUID,
    body: TerminateRequest = TerminateRequest(),
    svc: NegotiationService = Depends(get_negotiation_service),
    _user: object = Depends(require_role("ADMIN")),
) -> dict:
    """POST /v1/sessions/{id}/terminate — admin terminates session."""
    cmd = TerminateSessionCommand(session_id=session_id, reason=body.reason)
    await svc.terminate_session(cmd)
    return success_response(data={"terminated": True, "session_id": str(session_id)})


@router.get(
    "/{session_id}/analytics",
    summary="Get deal quality and relational quality analytics for a completed session",
)
async def get_session_analytics(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    svc: NegotiationService = Depends(get_negotiation_service),
) -> dict:
    """
    Returns deal quality score, relational quality scores (trust/respect/equitability),
    and negotiation trajectory data for charting.
    Proves ROI to Chief Procurement Officers.
    """
    from src.negotiation.domain.relational_quality import RelationalQualityScorer

    session = await svc.session_repo.get_by_id(session_id)  # type: ignore[union-attr]
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if current_user.enterprise_id not in (session.buyer_enterprise_id, session.seller_enterprise_id):
        raise HTTPException(status_code=403, detail="Access denied")

    scorer = RelationalQualityScorer()
    rq = scorer.score(session)

    # Price trajectory for charting
    trajectory = [
        {
            "round": o.round_number.value,
            "role": o.proposer_role.value,
            "price": float(o.price.amount),
            "is_human": o.is_human_override,
        }
        for o in session.offers
    ]

    is_buyer = current_user.enterprise_id == session.buyer_enterprise_id
    redacted_dqs = _redact_deal_quality_for_party(
        getattr(session, "deal_quality_score", None), is_buyer
    )

    return success_response({
        "session_id": str(session.id),
        "status": session.status.value,
        "agreed_price": float(session.agreed_price.amount) if session.agreed_price else None,
        "deal_quality_score": redacted_dqs,
        "relational_quality": rq,
        "trajectory": trajectory,
        "rounds_taken": session.round_count.value,
        "transcript": getattr(session, "conversation_transcript", None),
    })


@router.get("/{session_id}/intelligence")
async def get_intelligence(
    session_id: uuid.UUID,
    svc: NegotiationService = Depends(get_negotiation_service),
    user: User = Depends(get_current_user),
) -> dict:
    """
    GET /v1/sessions/{id}/intelligence — Bayesian beliefs (role-filtered).

    Each party sees only a high-level classification of their opponent,
    NOT the opponent's raw beliefs, price trajectory, or flexibility scores.
    """
    from src.shared.domain.exceptions import NotFoundError
    session = await svc.session_repo.get_by_id(session_id)  # type: ignore[union-attr]
    if not session:
        raise NotFoundError("NegotiationSession", session_id)
    if user.enterprise_id not in (session.buyer_enterprise_id, session.seller_enterprise_id):
        raise HTTPException(status_code=403, detail="Access denied")
    data = await svc.get_session_intelligence(session_id)

    # Role-filter: each party sees only opponent classification, not raw data
    is_buyer = user.enterprise_id == session.buyer_enterprise_id
    opponent_intel = data.get("seller_intelligence" if is_buyer else "buyer_intelligence", {})
    own_intel = data.get("buyer_intelligence" if is_buyer else "seller_intelligence", {})

    filtered = {
        "session_id": data.get("session_id"),
        "round_count": data.get("round_count"),
        "status": data.get("status"),
        "your_intelligence": own_intel,
        "opponent_classification": {
            "dominant_type": opponent_intel.get("dominant_type"),
            "flexibility_hint": (
                "high" if (opponent_intel.get("flexibility") or 0) > 0.4 else "low"
            ),
        },
        "convergence": data.get("convergence"),
        "stall_counter": data.get("stall_counter"),
    }
    return success_response(data=filtered)


@router.get("/{session_id}/stream")
async def stream_session(
    session_id: uuid.UUID,
    request: Request,
    last_event_id: str | None = Query(None, alias="Last-Event-ID"),
    current_user: User = Depends(get_current_user),
    svc: NegotiationService = Depends(get_negotiation_service),
) -> StreamingResponse:
    """
    GET /v1/sessions/{id}/stream — SSE live agent turns.

    Supports Last-Event-ID header for reconnect replay.
    Requires authentication and enterprise membership.
    """
    from src.shared.domain.exceptions import NotFoundError

    session = await svc.session_repo.get_by_id(session_id)
    if not session:
        raise NotFoundError("NegotiationSession", session_id)

    if current_user.enterprise_id not in (
        session.buyer_enterprise_id,
        session.seller_enterprise_id,
    ):
        raise HTTPException(status_code=403, detail="Not a party to this session")

    sse_pub = await get_sse_publisher()

    async def event_generator():
        # Replay missed events on reconnect
        last_id = last_event_id or request.headers.get("Last-Event-ID")
        events = await sse_pub.get_events_since(session_id, last_id)
        for ev in events:
            event_id = ev.get("event_id", "")
            yield f"id: {event_id}\nevent: {ev.get('event', 'message')}\ndata: {json.dumps(ev)}\n\n"

        # Track the latest event ID we've seen; use empty string sentinel
        # to avoid re-fetching all events when None
        current_last_id = (
            events[-1]["event_id"] if events
            else last_id or ""
        )

        # Poll for new events
        while True:
            if await request.is_disconnected():
                break
            new_events = await sse_pub.get_events_since(
                session_id,
                current_last_id if current_last_id else None,
            )
            for ev in new_events:
                event_id = ev.get("event_id", "")
                yield f"id: {event_id}\nevent: {ev.get('event', 'message')}\ndata: {json.dumps(ev)}\n\n"
                current_last_id = event_id
                if ev.get("terminal"):
                    return
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
