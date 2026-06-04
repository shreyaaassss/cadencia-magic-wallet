"""
Admin service layer — all database queries and business logic for admin endpoints.

Design:
  - All aggregations use SQLAlchemy func.count/sum/avg — never fetch-all-then-aggregate.
  - JOINs handle user_count, enterprise_name, buyer/seller names — no N+1 patterns.
  - LLM log table may not exist yet — queries handle empty results gracefully.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.admin.models import BroadcastModel, LLMCallLogModel
from src.admin.schemas.admin_schemas import (
    ActivityItem,
    AdminAgentItem,
    AdminEnterpriseItem,
    AdminStatsResponse,
    AdminUserItem,
    AgentStatusResponse,
    BroadcastRequest,
    BroadcastResponse,
    KYCActionResponse,
    LLMLogItem,
    PendingEscrowItem,
    UserSuspendResponse,
)
from src.identity.infrastructure.models import EnterpriseModel, UserModel
from src.negotiation.infrastructure.models import NegotiationSessionModel
from src.settlement.infrastructure.models import EscrowContractModel
from src.shared.infrastructure.logging import get_logger

log = get_logger(__name__)

# KYC action → target status mapping
_KYC_ACTION_MAP: dict[str, str] = {
    "approve": "ACTIVE",
    "reject": "REJECTED",
    "revoke": "NOT_SUBMITTED",
}

# Frontend maps PENDING from the KYC domain. The DB CHECK constraint allows:
#   PENDING, KYC_SUBMITTED, VERIFIED, ACTIVE
# The frontend expects: NOT_SUBMITTED, PENDING, ACTIVE, REJECTED
# We map DB values → frontend values for consistency.
_KYC_STATUS_MAP: dict[str, str] = {
    "PENDING": "NOT_SUBMITTED",
    "KYC_SUBMITTED": "PENDING",
    "VERIFIED": "ACTIVE",
    "ACTIVE": "ACTIVE",
}

# Reverse map: frontend status → DB status for writes
_KYC_STATUS_REVERSE: dict[str, str] = {
    "ACTIVE": "ACTIVE",
    "REJECTED": "PENDING",       # Reset to PENDING (closest valid DB status)
    "NOT_SUBMITTED": "PENDING",  # Reset to PENDING
}


def _map_kyc_to_frontend(db_status: str) -> str:
    """Map DB kyc_status values to frontend-expected values."""
    return _KYC_STATUS_MAP.get(db_status, db_status)


class AdminService:
    """Admin service — encapsulates all admin dashboard queries and mutations."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── 1. GET /v1/admin/stats ────────────────────────────────────────────────

    async def get_stats(self) -> AdminStatsResponse:
        """Compute platform-wide aggregate statistics via efficient DB queries."""

        # Enterprise counts
        ent_result = await self._db.execute(
            select(
                func.count(EnterpriseModel.id).label("total"),
                func.count(
                    case(
                        (EnterpriseModel.kyc_status == "ACTIVE", EnterpriseModel.id),
                        else_=None,
                    )
                ).label("active"),
                func.count(
                    case(
                        (EnterpriseModel.kyc_status == "KYC_SUBMITTED", EnterpriseModel.id),
                        else_=None,
                    )
                ).label("pending"),
            )
        )
        ent_row = ent_result.one()

        # User count
        user_result = await self._db.execute(
            select(func.count(UserModel.id))
        )
        total_users = user_result.scalar_one()

        # Session aggregates
        session_result = await self._db.execute(
            select(
                func.count(
                    case(
                        (NegotiationSessionModel.status == "ACTIVE", NegotiationSessionModel.id),
                        else_=None,
                    )
                ).label("active_sessions"),
                func.count(
                    case(
                        (NegotiationSessionModel.status == "AGREED", NegotiationSessionModel.id),
                        else_=None,
                    )
                ).label("agreed_sessions"),
                func.count(
                    case(
                        (NegotiationSessionModel.status != "ACTIVE", NegotiationSessionModel.id),
                        else_=None,
                    )
                ).label("non_active_sessions"),
                func.coalesce(
                    func.avg(
                        case(
                            (NegotiationSessionModel.status == "AGREED",
                             NegotiationSessionModel.current_round),
                            else_=None,
                        )
                    ),
                    0.0,
                ).label("avg_rounds"),
            )
        )
        sess_row = session_result.one()

        # Escrow total value
        escrow_result = await self._db.execute(
            select(func.coalesce(func.sum(EscrowContractModel.amount_microalgo), 0))
        )
        total_escrow_value = escrow_result.scalar_one()

        # LLM calls today (count rows in llm_call_logs created today UTC)
        today_start = datetime.now(tz=timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        try:
            llm_result = await self._db.execute(
                select(func.count(LLMCallLogModel.id)).where(
                    LLMCallLogModel.created_at >= today_start
                )
            )
            llm_calls_today = llm_result.scalar_one()
        except Exception:
            # Table may not exist yet — graceful fallback
            llm_calls_today = 0

        # Compute success rate
        agreed = sess_row.agreed_sessions or 0
        non_active = sess_row.non_active_sessions or 0
        success_rate = round((agreed / non_active) * 100, 1) if non_active > 0 else 0.0

        # Pending escrows count
        try:
            pending_escrow_result = await self._db.execute(
                select(func.count(EscrowContractModel.id)).where(
                    EscrowContractModel.status == "PENDING_APPROVAL"
                )
            )
            pending_escrows = pending_escrow_result.scalar_one()
        except Exception:
            pending_escrows = 0

        return AdminStatsResponse(
            total_enterprises=ent_row.total or 0,
            active_enterprises=ent_row.active or 0,
            total_users=total_users or 0,
            active_sessions=sess_row.active_sessions or 0,
            total_escrow_value=int(total_escrow_value),
            pending_kyc=ent_row.pending or 0,
            pending_escrows=pending_escrows,
            llm_calls_today=llm_calls_today,
            avg_negotiation_rounds=round(float(sess_row.avg_rounds), 1),
            success_rate=success_rate,
        )

    # ── 1b. GET /v1/admin/pending-escrows ──────────────────────────────────────

    async def list_pending_escrows(self, limit: int = 50) -> list[PendingEscrowItem]:
        """List pending escrows with buyer/seller enterprise names via JOINs."""
        BuyerEnt = aliased(EnterpriseModel, name="buyer_ent")
        SellerEnt = aliased(EnterpriseModel, name="seller_ent")

        result = await self._db.execute(
            select(
                EscrowContractModel.id.label("escrow_id"),
                EscrowContractModel.session_id,
                EscrowContractModel.amount_microalgo,
                EscrowContractModel.agreed_price_inr,
                EscrowContractModel.status,
                EscrowContractModel.created_at,
                func.coalesce(BuyerEnt.name, "Unknown Buyer").label("buyer_name"),
                func.coalesce(SellerEnt.name, "Unknown Seller").label("seller_name"),
            )
            .outerjoin(
                BuyerEnt,
                EscrowContractModel.buyer_enterprise_id == BuyerEnt.id,
            )
            .outerjoin(
                SellerEnt,
                EscrowContractModel.seller_enterprise_id == SellerEnt.id,
            )
            .where(EscrowContractModel.status == "PENDING_APPROVAL")
            .order_by(EscrowContractModel.created_at.asc())
            .limit(limit)
        )

        items = []
        for row in result.all():
            items.append(
                PendingEscrowItem(
                    escrow_id=str(row.escrow_id),
                    session_id=str(row.session_id),
                    buyer_name=row.buyer_name,
                    seller_name=row.seller_name,
                    agreed_price_inr=row.agreed_price_inr,
                    amount_microalgo=row.amount_microalgo,
                    amount_algo=round(row.amount_microalgo / 1_000_000, 6),
                    status=row.status,
                    created_at=row.created_at.isoformat() if isinstance(row.created_at, datetime) else str(row.created_at),
                )
            )
        return items

    # ── 2. GET /v1/admin/enterprises ──────────────────────────────────────────

    async def list_enterprises(self, limit: int = 20, offset: int = 0) -> list[AdminEnterpriseItem]:
        """List all enterprises with user_count via subquery JOIN. Ordered by created_at DESC."""
        # Subquery: count users per enterprise
        user_count_subq = (
            select(
                UserModel.enterprise_id,
                func.count(UserModel.id).label("user_count"),
            )
            .group_by(UserModel.enterprise_id)
            .subquery()
        )

        result = await self._db.execute(
            select(
                EnterpriseModel.id,
                EnterpriseModel.name,
                EnterpriseModel.kyc_status,
                EnterpriseModel.trade_role,
                func.coalesce(user_count_subq.c.user_count, 0).label("user_count"),
                EnterpriseModel.created_at,
            )
            .outerjoin(
                user_count_subq,
                EnterpriseModel.id == user_count_subq.c.enterprise_id,
            )
            .order_by(EnterpriseModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        return [
            AdminEnterpriseItem(
                id=str(row.id),
                legal_name=row.name,
                kyc_status=_map_kyc_to_frontend(row.kyc_status),
                trade_role=row.trade_role,
                user_count=row.user_count,
                created_at=row.created_at.isoformat() if isinstance(row.created_at, datetime) else str(row.created_at),
            )
            for row in result.all()
        ]

    # ── 3. PATCH /v1/admin/enterprises/:id/kyc ────────────────────────────────

    async def apply_kyc_action(
        self, enterprise_id: uuid.UUID, action: str
    ) -> KYCActionResponse:
        """Apply KYC approve/reject/revoke action to an enterprise."""
        from fastapi import HTTPException

        result = await self._db.execute(
            select(EnterpriseModel).where(EnterpriseModel.id == enterprise_id)
        )
        enterprise = result.scalar_one_or_none()
        if enterprise is None:
            raise HTTPException(status_code=404, detail="Enterprise not found")

        # State machine: (action) → (required_from_frontend, target_frontend)
        _TRANSITION_MAP = {
            "approve": ("PENDING", "ACTIVE"),
            "reject":  ("PENDING", "REJECTED"),
            "revoke":  ("ACTIVE",  "NOT_SUBMITTED"),
        }
        required_from, target_frontend_status = _TRANSITION_MAP[action]

        # Map current DB status to frontend status for comparison
        current_frontend_status = _map_kyc_to_frontend(enterprise.kyc_status)

        if current_frontend_status != required_from:
            raise HTTPException(
                status_code=400,
                detail=f"Action '{action}' requires current status '{required_from}', "
                       f"but enterprise is '{current_frontend_status}'",
            )

        # Map the frontend target status to what the DB constraint allows
        # DB CHECK: PENDING, KYC_SUBMITTED, VERIFIED, ACTIVE
        db_status_map = {
            "ACTIVE": "ACTIVE",
            "REJECTED": "PENDING",        # No REJECTED in DB — reset to PENDING
            "NOT_SUBMITTED": "PENDING",   # No NOT_SUBMITTED in DB — reset to PENDING
        }
        db_status = db_status_map.get(target_frontend_status, "PENDING")

        enterprise.kyc_status = db_status
        await self._db.flush()

        return KYCActionResponse(
            id=str(enterprise_id),
            kyc_status=target_frontend_status,  # Return frontend-friendly status
            message="KYC action applied",
        )

    # ── 4. GET /v1/admin/users ────────────────────────────────────────────────

    async def list_users(self, limit: int = 20, offset: int = 0) -> list[AdminUserItem]:
        """List all users with enterprise_name via JOIN. Non-ADMIN roles mapped to 'USER'."""
        result = await self._db.execute(
            select(
                UserModel.id,
                UserModel.email,
                UserModel.role,
                UserModel.enterprise_id,
                UserModel.is_active,
                UserModel.last_login_at,
                UserModel.created_at,
                EnterpriseModel.name.label("enterprise_name"),
            )
            .join(EnterpriseModel, UserModel.enterprise_id == EnterpriseModel.id)
            .order_by(UserModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        return [
            AdminUserItem(
                id=str(row.id),
                full_name=row.email.split("@")[0].replace(".", " ").title(),  # Derive from email
                email=row.email,
                role="ADMIN" if row.role == "ADMIN" else "MEMBER",
                enterprise_id=str(row.enterprise_id),
                enterprise_name=row.enterprise_name,
                status="ACTIVE" if row.is_active else "SUSPENDED",
                last_login=row.last_login_at.isoformat() if isinstance(row.last_login_at, datetime) else None,
            )
            for row in result.all()
        ]

    # ── 5. PATCH /v1/admin/users/:id/suspend ──────────────────────────────────

    async def suspend_user(
        self, user_id: uuid.UUID, action: str
    ) -> UserSuspendResponse:
        """Suspend or reinstate a user. Blocks admin-on-admin suspension."""
        from fastapi import HTTPException

        result = await self._db.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        if action == "suspend" and user.role == "ADMIN":
            raise HTTPException(status_code=403, detail="Cannot suspend an ADMIN user")

        if action == "suspend":
            user.is_active = False
        else:  # reinstate
            user.is_active = True

        await self._db.flush()

        return UserSuspendResponse(
            id=str(user_id),
            status="ACTIVE" if user.is_active else "SUSPENDED",
        )

    # ── 6. GET /v1/admin/agents ───────────────────────────────────────────────

    async def list_agents(self) -> list[AdminAgentItem]:
        """List in-progress negotiation agents with buyer/seller names via JOINs."""
        BuyerEnt = aliased(EnterpriseModel, name="buyer_ent")
        SellerEnt = aliased(EnterpriseModel, name="seller_ent")

        # Subquery: avg latency per session from LLM logs
        try:
            latency_subq = (
                select(
                    LLMCallLogModel.session_id,
                    func.coalesce(func.avg(LLMCallLogModel.latency_ms), 0).label("avg_latency"),
                    func.max(LLMCallLogModel.model_name).label("last_model"),
                )
                .group_by(LLMCallLogModel.session_id)
                .subquery()
            )
            has_llm_table = True
        except Exception:
            has_llm_table = False
            latency_subq = None

        default_model = os.environ.get("LLM_MODEL", "gemini-2.0-flash")

        # Active or HUMAN_REVIEW (stalled) sessions
        active_statuses = ("ACTIVE", "HUMAN_REVIEW", "STALLED")

        if has_llm_table and latency_subq is not None:
            result = await self._db.execute(
                select(
                    NegotiationSessionModel.id.label("session_id"),
                    NegotiationSessionModel.status,
                    NegotiationSessionModel.current_round,
                    NegotiationSessionModel.created_at,
                    BuyerEnt.name.label("buyer_name"),
                    SellerEnt.name.label("seller_name"),
                    func.coalesce(latency_subq.c.avg_latency, 0).label("latency_ms"),
                    func.coalesce(latency_subq.c.last_model, default_model).label("model"),
                )
                .join(BuyerEnt, NegotiationSessionModel.buyer_enterprise_id == BuyerEnt.id)
                .join(SellerEnt, NegotiationSessionModel.seller_enterprise_id == SellerEnt.id)
                .outerjoin(
                    latency_subq,
                    NegotiationSessionModel.id == latency_subq.c.session_id,
                )
                .where(NegotiationSessionModel.status.in_(active_statuses))
                .order_by(NegotiationSessionModel.created_at.desc())
            )
        else:
            result = await self._db.execute(
                select(
                    NegotiationSessionModel.id.label("session_id"),
                    NegotiationSessionModel.status,
                    NegotiationSessionModel.current_round,
                    NegotiationSessionModel.created_at,
                    BuyerEnt.name.label("buyer_name"),
                    SellerEnt.name.label("seller_name"),
                )
                .join(BuyerEnt, NegotiationSessionModel.buyer_enterprise_id == BuyerEnt.id)
                .join(SellerEnt, NegotiationSessionModel.seller_enterprise_id == SellerEnt.id)
                .where(NegotiationSessionModel.status.in_(active_statuses))
                .order_by(NegotiationSessionModel.created_at.desc())
            )

        items = []
        for row in result.all():
            # Map DB statuses to frontend agent statuses
            agent_status: str
            if row.status in ("HUMAN_REVIEW", "STALLED"):
                agent_status = "PAUSED"
            else:
                agent_status = "RUNNING"

            items.append(
                AdminAgentItem(
                    session_id=str(row.session_id),
                    status=agent_status,
                    current_round=row.current_round,
                    model=getattr(row, "model", default_model),
                    latency_ms=int(getattr(row, "latency_ms", 0)),
                    buyer=row.buyer_name,
                    seller=row.seller_name,
                    started_at=row.created_at.isoformat() if isinstance(row.created_at, datetime) else str(row.created_at),
                )
            )
        return items

    # ── 7. POST /v1/admin/agents/:session_id/pause ────────────────────────────

    async def pause_agent(self, session_id: uuid.UUID) -> AgentStatusResponse:
        """Pause an active negotiation session (sets status to HUMAN_REVIEW)."""
        from fastapi import HTTPException

        result = await self._db.execute(
            select(NegotiationSessionModel).where(
                NegotiationSessionModel.id == session_id
            )
        )
        session = result.scalar_one_or_none()
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        if session.status != "ACTIVE":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot pause session with status '{session.status}'. Must be 'ACTIVE'.",
            )

        session.status = "HUMAN_REVIEW"
        await self._db.flush()

        return AgentStatusResponse(session_id=str(session_id), status="PAUSED")

    # ── 8. POST /v1/admin/agents/:session_id/resume ───────────────────────────

    async def resume_agent(self, session_id: uuid.UUID) -> AgentStatusResponse:
        """Resume a paused negotiation session (sets status back to ACTIVE)."""
        from fastapi import HTTPException

        result = await self._db.execute(
            select(NegotiationSessionModel).where(
                NegotiationSessionModel.id == session_id
            )
        )
        session = result.scalar_one_or_none()
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        if session.status not in ("HUMAN_REVIEW", "STALLED"):
            raise HTTPException(
                status_code=400, detail="Session is not paused."
            )

        session.status = "ACTIVE"
        await self._db.flush()

        return AgentStatusResponse(session_id=str(session_id), status="RUNNING")

    # ── 9. GET /v1/admin/llm-logs ─────────────────────────────────────────────

    async def list_llm_logs(
        self, limit: int = 100, session_id: uuid.UUID | None = None,
    ) -> list[LLMLogItem]:
        """Return LLM call log entries, ordered by created_at DESC."""
        try:
            stmt = (
                select(LLMCallLogModel)
                .order_by(LLMCallLogModel.created_at.desc())
                .limit(min(limit, 500))
            )
            if session_id is not None:
                stmt = stmt.where(LLMCallLogModel.session_id == session_id)
            result = await self._db.execute(stmt)
            rows = result.scalars().all()
        except Exception:
            # Table may not exist — return empty list
            return []

        return [
            LLMLogItem(
                id=str(row.id),
                session_id=str(row.session_id),
                round=row.round_number,
                agent=row.agent_role,
                model=row.model_name,
                prompt_tokens=row.prompt_tokens,
                completion_tokens=row.completion_tokens,
                latency_ms=row.latency_ms,
                status=row.status,
                created_at=row.created_at.isoformat() if isinstance(row.created_at, datetime) else str(row.created_at),
                prompt_summary=(row.prompt_text or "")[:200],
                response_summary=(row.response_text or "")[:200] if row.response_text else None,
            )
            for row in rows
        ]

    # ── 10. GET /v1/admin/activity ───────────────────────────────────────────

    async def list_activity(self, limit: int = 5) -> list[ActivityItem]:
        """Aggregate recent platform events from escrows and sessions."""
        items: list[ActivityItem] = []

        # Recent escrow state changes
        try:
            escrow_result = await self._db.execute(
                select(
                    EscrowContractModel.id,
                    EscrowContractModel.status,
                    EscrowContractModel.amount_microalgo,
                    EscrowContractModel.updated_at,
                )
                .order_by(EscrowContractModel.updated_at.desc())
                .limit(limit)
            )
            for row in escrow_result.all():
                amount_algo = (row.amount_microalgo or 0) / 1_000_000
                items.append(ActivityItem(
                    id=str(row.id),
                    event_type="escrow",
                    title=f"Escrow {row.status}",
                    detail="smart_contract",
                    amount=f"{amount_algo:.2f} ALGO",
                    created_at=row.updated_at.isoformat() if isinstance(row.updated_at, datetime) else str(row.updated_at),
                ))
        except Exception:
            pass

        # Recent session completions
        try:
            terminal_statuses = ("AGREED", "FAILED", "WALK_AWAY", "TIMEOUT")
            session_result = await self._db.execute(
                select(
                    NegotiationSessionModel.id,
                    NegotiationSessionModel.status,
                    NegotiationSessionModel.updated_at,
                )
                .where(NegotiationSessionModel.status.in_(terminal_statuses))
                .order_by(NegotiationSessionModel.updated_at.desc())
                .limit(limit)
            )
            for row in session_result.all():
                items.append(ActivityItem(
                    id=str(row.id),
                    event_type="negotiation",
                    title=f"Session {row.status}",
                    detail="negotiation_engine",
                    created_at=row.updated_at.isoformat() if isinstance(row.updated_at, datetime) else str(row.updated_at),
                ))
        except Exception:
            pass

        # Sort by created_at desc and limit
        items.sort(key=lambda x: x.created_at, reverse=True)
        return items[:limit]

    # ── 11. POST /v1/admin/broadcast ──────────────────────────────────────────

    async def broadcast(
        self, request: BroadcastRequest, sender_id: uuid.UUID
    ) -> BroadcastResponse:
        """Persist a broadcast and compute recipient count from target filter."""
        from fastapi import HTTPException

        if len(request.message) > 1000:
            raise HTTPException(
                status_code=400, detail="Message exceeds 1000 character limit"
            )

        # Compute recipient count based on target filter
        if request.target == "all":
            count_result = await self._db.execute(
                select(func.count(UserModel.id)).where(UserModel.is_active == True)  # noqa: E712
            )
        elif request.target == "active_enterprises":
            count_result = await self._db.execute(
                select(func.count(UserModel.id))
                .join(EnterpriseModel, UserModel.enterprise_id == EnterpriseModel.id)
                .where(
                    and_(
                        UserModel.is_active == True,  # noqa: E712
                        EnterpriseModel.kyc_status == "ACTIVE",
                    )
                )
            )
        elif request.target == "admins_only":
            count_result = await self._db.execute(
                select(func.count(UserModel.id)).where(
                    and_(
                        UserModel.is_active == True,  # noqa: E712
                        UserModel.role == "ADMIN",
                    )
                )
            )
        else:
            count_result = await self._db.execute(
                select(func.count(UserModel.id))
            )

        recipient_count = count_result.scalar_one()

        # Persist broadcast record
        broadcast_id = uuid.uuid4()
        broadcast_model = BroadcastModel(
            id=broadcast_id,
            message=request.message,
            target=request.target,
            priority=request.priority,
            sender_id=sender_id,
            recipient_count=recipient_count,
        )
        self._db.add(broadcast_model)
        await self._db.flush()

        log.info(
            "admin_broadcast_sent",
            broadcast_id=str(broadcast_id),
            target=request.target,
            priority=request.priority,
            recipients=recipient_count,
        )

        return BroadcastResponse(
            message_id=str(broadcast_id),
            recipients=recipient_count,
            delivered=True,
        )
