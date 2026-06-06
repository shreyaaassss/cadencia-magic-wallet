"""Messaging service — buyer-seller communication scoped by deal."""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select

log = structlog.get_logger(__name__)


class MessagingService:
    """Manages conversation threads and messages."""

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
        """Create a new conversation thread."""
        from src.messaging.infrastructure.models import ConversationThreadModel

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
        return {"id": str(thread.id), "subject": subject, "thread_type": thread_type}

    async def send_message(
        self,
        thread_id: uuid.UUID,
        sender_enterprise_id: uuid.UUID,
        sender_user_id: uuid.UUID,
        body: str,
    ) -> dict:
        """Send a message in a thread."""
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
        if thread.status != "OPEN":
            raise ValueError("Thread is closed")

        msg = MessageModel(
            id=uuid.uuid4(),
            thread_id=thread_id,
            sender_enterprise_id=sender_enterprise_id,
            sender_user_id=sender_user_id,
            body=body[:5000],  # enforce max length
        )
        self._session.add(msg)
        await self._session.commit()
        return {"id": str(msg.id), "body": msg.body, "created_at": str(msg.created_at)}

    async def list_threads(self, enterprise_id: uuid.UUID, limit: int = 20) -> list[dict]:
        """List threads for an enterprise."""
        from sqlalchemy import or_

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
                "created_at": str(t.created_at),
            }
            for t in threads
        ]

    async def get_messages(self, thread_id: uuid.UUID, limit: int = 50) -> list[dict]:
        """Get messages in a thread."""
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
