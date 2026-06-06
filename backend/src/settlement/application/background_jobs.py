"""Background jobs for settlement lifecycle management.

Jobs:
  - check_approval_deadlines: auto-reject escrows past 72h approval window
  - check_dispatch_timeouts: auto-freeze escrows where delivery is overdue (7d)
"""

from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)


async def check_approval_deadlines() -> None:
    """Auto-reject escrows where approval_deadline has passed.

    Runs every hour. Transitions PENDING_APPROVAL → REJECTED for
    escrows where the seller didn't respond within 72 hours.
    """
    from datetime import datetime, timezone

    from sqlalchemy import select, update

    from src.settlement.infrastructure.models import EscrowContractModel
    from src.shared.infrastructure.db.session import get_session_factory

    now = datetime.now(timezone.utc)
    async with get_session_factory()() as session:
        result = await session.execute(
            select(EscrowContractModel).where(
                EscrowContractModel.status == "PENDING_APPROVAL",
                EscrowContractModel.approval_deadline != None,  # noqa: E711
                EscrowContractModel.approval_deadline < now,
            )
        )
        overdue = result.scalars().all()
        if not overdue:
            return

        for escrow in overdue:
            await session.execute(
                update(EscrowContractModel)
                .where(EscrowContractModel.id == escrow.id)
                .values(status="REJECTED", updated_at=now)
            )
            log.info(
                "approval_deadline_auto_reject",
                escrow_id=str(escrow.id),
                deadline=str(escrow.approval_deadline),
            )
        await session.commit()
        log.info("approval_deadlines_checked", rejected=len(overdue))


async def check_dispatch_timeouts() -> None:
    """Auto-freeze escrows where delivery is overdue.

    Runs every hour. If an escrow has been DISPATCHED for > 7 days
    without being RELEASED, freeze it for dispute resolution.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select, update

    from src.settlement.infrastructure.models import EscrowContractModel
    from src.shared.infrastructure.db.session import get_session_factory

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    async with get_session_factory()() as session:
        result = await session.execute(
            select(EscrowContractModel).where(
                EscrowContractModel.status == "DISPATCHED",
                EscrowContractModel.is_frozen == False,  # noqa: E712
                EscrowContractModel.updated_at < cutoff,
            )
        )
        overdue = result.scalars().all()
        if not overdue:
            return

        for escrow in overdue:
            await session.execute(
                update(EscrowContractModel)
                .where(EscrowContractModel.id == escrow.id)
                .values(is_frozen=True, updated_at=datetime.now(timezone.utc))
            )
            log.warning(
                "dispatch_timeout_auto_freeze",
                escrow_id=str(escrow.id),
                dispatched_at=str(escrow.updated_at),
            )
        await session.commit()
        log.info("dispatch_timeouts_checked", frozen=len(overdue))
