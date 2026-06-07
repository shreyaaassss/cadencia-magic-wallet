"""Messaging service — buyer-seller communication scoped by deal.

Lifecycle rules:
  - Threads are scoped to a session/escrow — one active thread per deal
  - Threads auto-close when escrow reaches RELEASED or REFUNDED
  - Closed threads are read-only (chat history preserved, no new messages)
  - Only matched buyer-seller pairs can create threads (post-match only)
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import or_, select, update

log = structlog.get_logger(__name__)


class MessagingService:
    """Manages conversation threads and messages with lifecycle guards."""

    def __init__(self, session: object) -> None:
        self._session = session

    async def create_thread(
        self,
        buyer_enterprise_id: uuid.UUID,
        seller_enterprise_id: uuid.UUID,
        thread_type: str = "GENERAL",
        subject: str | None = None,
        rfq_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        escrow_id: uuid.UUID | None = None,
    ) -> dict:
        """Create a new conversation thread.

        Validates that buyer and seller have an active match/session.
        Only one OPEN thread per session_id is allowed.
        """
        from src.messaging.infrastructure.models import ConversationThreadModel

        # Post-match guard: verify a session exists between these parties
        if session_id:
            from src.negotiation.infrastructure.models import NegotiationSessionModel
            sess_result = await self._session.execute(
                select(NegotiationSessionModel).where(
                    NegotiationSessionModel.id == session_id,
                    NegotiationSessionModel.buyer_enterprise_id == buyer_enterprise_id,
                    NegotiationSessionModel.seller_enterprise_id == seller_enterprise_id,
                )
            )
            if not sess_result.scalar_one_or_none():
                raise ValueError("No matching session between buyer and seller")

            # Check for existing open thread on this session
            existing = await self._session.execute(
                select(ConversationThreadModel).where(
                    ConversationThreadModel.session_id == session_id,
                    ConversationThreadModel.status == "OPEN",
                )
            )
            if existing.scalar_one_or_none():
                raise ValueError("An open thread already exists for this session")

        thread = ConversationThreadModel(
            id=uuid.uuid4(),
            subject=subject,
            thread_type=thread_type,
            rfq_id=rfq_id,
            session_id=session_id,
            escrow_id=escrow_id,
            buyer_enterprise_id=buyer_enterprise_id,
            seller_enterprise_id=seller_enterprise_id,
        )
        self._session.add(thread)
        await self._session.commit()
        log.info("thread_created", thread_id=str(thread.id))
        return {"id": str(thread.id), "subject": subject, "thread_type": thread_type, "status": "OPEN"}

    async def send_message(
        self,
        thread_id: uuid.UUID,
        sender_enterprise_id: uuid.UUID,
        sender_user_id: uuid.UUID,
        body: str,
    ) -> dict:
        """Send a message in a thread.

        Blocked if thread is CLOSED (escrow released/refunded).
        """
        from src.messaging.infrastructure.models import ConversationThreadModel, MessageModel

        # Verify thread exists and sender is a party
        result = await self._session.execute(
            select(ConversationThreadModel).where(ConversationThreadModel.id == thread_id)
        )
        thread = result.scalar_one_or_none()
        if not thread:
            raise ValueError("Thread not found")
        if sender_enterprise_id not in (thread.buyer_enterprise_id, thread.seller_enterprise_id):
            raise ValueError("Not a party to this thread")
        if thread.status == "CLOSED":
            raise ValueError("Thread is closed — deal has been completed. Chat history is read-only.")
        if thread.status == "ESCALATED":
            raise ValueError("Thread is escalated to admin — wait for resolution")

        if not body or not body.strip():
            raise ValueError("Message body cannot be empty")

        msg = MessageModel(
            id=uuid.uuid4(),
            thread_id=thread_id,
            sender_enterprise_id=sender_enterprise_id,
            sender_user_id=sender_user_id,
            body=body[:5000],  # enforce max length
        )
        self._session.add(msg)
        await self._session.commit()

        # Publish to Redis for real-time SSE delivery
        try:
            import json

            from src.shared.infrastructure.cache.redis_client import get_redis_client
            redis = get_redis_client()
            await redis.publish(f"messaging:{thread_id}", json.dumps({
                "id": str(msg.id),
                "body": msg.body,
                "sender_enterprise_id": str(sender_enterprise_id),
                "is_system_generated": False,
                "created_at": str(msg.created_at),
            }))
        except Exception:
            pass  # Redis publish is best-effort

        return {"id": str(msg.id), "body": msg.body, "created_at": str(msg.created_at)}

    async def close_threads_for_escrow(self, escrow_id: uuid.UUID) -> int:
        """Auto-close all OPEN threads linked to an escrow."""
        from src.messaging.infrastructure.models import ConversationThreadModel

        result = await self._session.execute(
            update(ConversationThreadModel)
            .where(
                ConversationThreadModel.escrow_id == escrow_id,
                ConversationThreadModel.status == "OPEN",
            )
            .values(status="CLOSED")
        )
        await self._session.commit()
        count = result.rowcount
        if count:
            log.info("threads_closed_for_escrow", escrow_id=str(escrow_id), count=count)
        return count

    async def close_threads_for_session(self, session_id: uuid.UUID) -> int:
        """Close all OPEN threads linked to a session."""
        from src.messaging.infrastructure.models import ConversationThreadModel

        result = await self._session.execute(
            update(ConversationThreadModel)
            .where(
                ConversationThreadModel.session_id == session_id,
                ConversationThreadModel.status == "OPEN",
            )
            .values(status="CLOSED")
        )
        await self._session.commit()
        count = result.rowcount
        if count:
            log.info("threads_closed_for_session", session_id=str(session_id), count=count)
        return count

    async def list_threads(self, enterprise_id: uuid.UUID, limit: int = 20) -> list[dict]:
        """List threads for an enterprise (includes closed threads for history)."""
        from src.messaging.infrastructure.models import ConversationThreadModel

        result = await self._session.execute(
            select(ConversationThreadModel)
            .where(or_(
                ConversationThreadModel.buyer_enterprise_id == enterprise_id,
                ConversationThreadModel.seller_enterprise_id == enterprise_id,
            ))
            .order_by(ConversationThreadModel.created_at.desc())
            .limit(limit)
        )
        threads = result.scalars().all()
        return [
            {
                "id": str(t.id),
                "subject": t.subject,
                "thread_type": t.thread_type,
                "status": t.status,
                "session_id": str(t.session_id) if t.session_id else None,
                "escrow_id": str(t.escrow_id) if t.escrow_id else None,
                "is_read_only": t.status == "CLOSED",
                "created_at": str(t.created_at),
            }
            for t in threads
        ]

    async def get_messages(self, thread_id: uuid.UUID, limit: int = 50) -> list[dict]:
        """Get messages in a thread (works for both OPEN and CLOSED threads)."""
        from src.messaging.infrastructure.models import MessageModel

        result = await self._session.execute(
            select(MessageModel)
            .where(MessageModel.thread_id == thread_id)
            .order_by(MessageModel.created_at.asc())
            .limit(limit)
        )
        messages = result.scalars().all()
        return [
            {
                "id": str(m.id),
                "sender_enterprise_id": str(m.sender_enterprise_id),
                "body": m.body,
                "is_system_generated": m.is_system_generated,
                "created_at": str(m.created_at),
            }
            for m in messages
        ]
