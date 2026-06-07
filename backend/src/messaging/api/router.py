"""Messaging API endpoints — threads and messages."""

from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.identity.api.dependencies import get_current_user
from src.identity.domain.user import User
from src.shared.api.responses import success_response
from src.shared.infrastructure.db.session import get_db_session

router = APIRouter(prefix="/v1/threads", tags=["Messaging"])


@router.post("", status_code=201, summary="Create conversation thread")
async def create_thread(
    body: dict,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """POST /v1/threads — create a new conversation thread."""
    from src.messaging.application.services import MessagingService

    svc = MessagingService(session)
    result = await svc.create_thread(
        buyer_enterprise_id=uuid.UUID(body["buyer_enterprise_id"]),
        seller_enterprise_id=uuid.UUID(body["seller_enterprise_id"]),
        thread_type=body.get("thread_type", "GENERAL"),
        subject=body.get("subject"),
        rfq_id=uuid.UUID(body["rfq_id"]) if body.get("rfq_id") else None,
        session_id=uuid.UUID(body["session_id"]) if body.get("session_id") else None,
    )
    return success_response(data=result)


@router.get("", summary="List conversation threads")
async def list_threads(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """GET /v1/threads — list threads for current enterprise."""
    from src.messaging.application.services import MessagingService

    svc = MessagingService(session)
    threads = await svc.list_threads(current_user.enterprise_id)
    return success_response(data=threads)


@router.get("/{thread_id}/messages", summary="Get messages in thread")
async def get_messages(
    thread_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """GET /v1/threads/{id}/messages — get messages (paginated)."""
    from src.messaging.application.services import MessagingService

    svc = MessagingService(session)
    messages = await svc.get_messages(thread_id, limit=limit)
    return success_response(data=messages)


@router.post("/{thread_id}/messages", status_code=201, summary="Send message")
async def send_message(
    thread_id: uuid.UUID,
    body: dict,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """POST /v1/threads/{id}/messages — send a message."""
    from src.messaging.application.services import MessagingService

    svc = MessagingService(session)
    try:
        result = await svc.send_message(
            thread_id=thread_id,
            sender_enterprise_id=current_user.enterprise_id,
            sender_user_id=current_user.id,
            body=body.get("body", ""),
        )
        return success_response(data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{thread_id}/stream", summary="SSE stream for real-time messages")
async def stream_messages(
    thread_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """GET /v1/threads/{id}/stream — SSE stream for real-time message delivery."""
    from src.shared.infrastructure.cache.redis_client import get_redis_client

    async def event_generator():
        redis = get_redis_client()
        pubsub = redis.pubsub()
        channel = f"messaging:{thread_id}"
        await pubsub.subscribe(channel)
        try:
            # Send initial keepalive
            yield f"event: connected\ndata: {json.dumps({'thread_id': str(thread_id)})}\n\n"
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg["type"] == "message":
                    data = msg["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    yield f"event: message\ndata: {data}\n\n"
                else:
                    # Keepalive every 15s to prevent proxy timeout
                    yield ": keepalive\n\n"
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
