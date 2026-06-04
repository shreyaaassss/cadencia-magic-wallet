"""
Admin API router — 10 platform administration endpoints.

All routes are gated behind ADMIN role via router-level dependency.
All responses use ApiResponse[T] envelope via success_response().

Frontend contract: cadencia_integration_audit.md §5.12
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.admin.schemas.admin_schemas import (
    ActivityItem,
    AdminAgentItem,
    AdminEnterpriseItem,
    AdminStatsResponse,
    AdminUserItem,
    AgentStatusResponse,
    BroadcastRequest,
    BroadcastResponse,
    KYCActionRequest,
    KYCActionResponse,
    LLMLogItem,
    PendingEscrowItem,
    UserSuspendRequest,
    UserSuspendResponse,
)
from src.admin.services.admin_service import AdminService
from src.identity.api.dependencies import get_current_user, verify_admin_token
from src.identity.domain.user import User
from src.shared.api.responses import ApiResponse, success_response
from src.shared.infrastructure.db.session import get_db_session
from src.shared.infrastructure.logging import get_logger

log = get_logger(__name__)


# ── Admin Guard ───────────────────────────────────────────────────────────────
# Using centralized verify_admin_token from identity dependencies
# This validates the user has ADMIN role via JWT + DB check


def _get_admin_service(
    db: AsyncSession = Depends(get_db_session),
) -> AdminService:
    """Dependency: build AdminService per request."""
    return AdminService(db)


# ── Router ────────────────────────────────────────────────────────────────────

router = APIRouter(
    prefix="/v1/admin",
    tags=["admin"],
    dependencies=[Depends(verify_admin_token)],
)


# ── 1. GET /v1/admin/stats ────────────────────────────────────────────────────

@router.get(
    "/stats",
    response_model=ApiResponse[AdminStatsResponse],
    summary="Platform-wide aggregate statistics",
)
async def get_stats(
    svc: AdminService = Depends(_get_admin_service),
) -> ApiResponse[AdminStatsResponse]:
    stats = await svc.get_stats()
    return success_response(stats)


# ── 1b. GET /v1/admin/pending-escrows ───────────────────────────────────

@router.get(
    "/pending-escrows",
    response_model=ApiResponse[list[PendingEscrowItem]],
    summary="List escrows awaiting admin approval with buyer/seller names",
)
async def list_pending_escrows(
    limit: int = Query(default=50, ge=1, le=100),
    svc: AdminService = Depends(_get_admin_service),
) -> ApiResponse[list[PendingEscrowItem]]:
    items = await svc.list_pending_escrows(limit=limit)
    return success_response(items)


# ── 2. GET /v1/admin/enterprises ──────────────────────────────────────────────

@router.get(
    "/enterprises",
    response_model=ApiResponse[list[AdminEnterpriseItem]],
    summary="List all registered enterprises with user counts",
)
async def list_enterprises(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    svc: AdminService = Depends(_get_admin_service),
) -> ApiResponse[list[AdminEnterpriseItem]]:
    enterprises = await svc.list_enterprises(limit=limit, offset=offset)
    return success_response(enterprises)


# ── 3. PATCH /v1/admin/enterprises/{enterprise_id}/kyc ────────────────────────

@router.patch(
    "/enterprises/{enterprise_id}/kyc",
    response_model=ApiResponse[KYCActionResponse],
    summary="Approve, reject, or revoke enterprise KYC",
)
async def apply_kyc_action(
    enterprise_id: uuid.UUID,
    body: KYCActionRequest,
    svc: AdminService = Depends(_get_admin_service),
) -> ApiResponse[KYCActionResponse]:
    result = await svc.apply_kyc_action(enterprise_id, body.action)
    return success_response(result)


# ── 4. GET /v1/admin/users ────────────────────────────────────────────────────

@router.get(
    "/users",
    response_model=ApiResponse[list[AdminUserItem]],
    summary="List all users across all enterprises",
)
async def list_users(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    svc: AdminService = Depends(_get_admin_service),
) -> ApiResponse[list[AdminUserItem]]:
    users = await svc.list_users(limit=limit, offset=offset)
    return success_response(users)


# ── 5. PATCH /v1/admin/users/{user_id}/suspend ───────────────────────────────

@router.patch(
    "/users/{user_id}/suspend",
    response_model=ApiResponse[UserSuspendResponse],
    summary="Suspend or reinstate a user account",
)
async def suspend_user(
    user_id: uuid.UUID,
    body: UserSuspendRequest,
    current_user: User = Depends(get_current_user),
    svc: AdminService = Depends(_get_admin_service),
) -> ApiResponse[UserSuspendResponse]:
    # Prevent admin from suspending themselves
    if str(user_id) == str(current_user.id):
        raise HTTPException(
            status_code=400,
            detail="Admins cannot suspend their own account",
        )
    result = await svc.suspend_user(user_id, body.action)
    return success_response(result)


# ── 6. GET /v1/admin/agents ───────────────────────────────────────────────────

@router.get(
    "/agents",
    response_model=ApiResponse[list[AdminAgentItem]],
    summary="List active negotiation agents with latency and buyer/seller names",
)
async def list_agents(
    svc: AdminService = Depends(_get_admin_service),
) -> ApiResponse[list[AdminAgentItem]]:
    agents = await svc.list_agents()
    return success_response(agents)


# ── 7. POST /v1/admin/agents/{session_id}/pause ──────────────────────────────

@router.post(
    "/agents/{session_id}/pause",
    response_model=ApiResponse[AgentStatusResponse],
    summary="Pause a running negotiation agent",
)
async def pause_agent(
    session_id: uuid.UUID,
    svc: AdminService = Depends(_get_admin_service),
) -> ApiResponse[AgentStatusResponse]:
    result = await svc.pause_agent(session_id)
    return success_response(result)


# ── 8. POST /v1/admin/agents/{session_id}/resume ─────────────────────────────

@router.post(
    "/agents/{session_id}/resume",
    response_model=ApiResponse[AgentStatusResponse],
    summary="Resume a paused negotiation agent",
)
async def resume_agent(
    session_id: uuid.UUID,
    svc: AdminService = Depends(_get_admin_service),
) -> ApiResponse[AgentStatusResponse]:
    result = await svc.resume_agent(session_id)
    return success_response(result)


# ── 9. GET /v1/admin/llm-logs ────────────────────────────────────────────────

@router.get(
    "/llm-logs",
    response_model=ApiResponse[list[LLMLogItem]],
    summary="Audit log of LLM API calls",
)
async def list_llm_logs(
    limit: int = 100,
    session_id: uuid.UUID | None = None,
    svc: AdminService = Depends(_get_admin_service),
) -> ApiResponse[list[LLMLogItem]]:
    logs = await svc.list_llm_logs(limit=limit, session_id=session_id)
    return success_response(logs)


# ── 10. GET /v1/admin/activity ────────────────────────────────────────────────

@router.get(
    "/activity",
    response_model=ApiResponse[list[ActivityItem]],
    summary="Recent platform activity (escrow events, KYC, user actions)",
)
async def list_activity(
    limit: int = 5,
    svc: AdminService = Depends(_get_admin_service),
) -> ApiResponse[list[ActivityItem]]:
    items = await svc.list_activity(limit=limit)
    return success_response(items)


# ── 11. POST /v1/admin/broadcast ─────────────────────────────────────────────

@router.post(
    "/broadcast",
    response_model=ApiResponse[BroadcastResponse],
    summary="Send a platform-wide notification to a target group",
)
async def send_broadcast(
    body: BroadcastRequest,
    current_user: User = Depends(get_current_user),
    svc: AdminService = Depends(_get_admin_service),
) -> ApiResponse[BroadcastResponse]:
    result = await svc.broadcast(body, sender_id=current_user.id)
    return success_response(result)
