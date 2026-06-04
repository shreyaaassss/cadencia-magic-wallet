"""
Admin API Pydantic schemas — request and response models.

All response models are used inside ApiResponse[T] envelope:
    { "success": true, "data": <schema>, "meta": {...}, "error": null }

Frontend contract reference: cadencia_integration_audit.md §5.12
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

# ── Request schemas ────────────────────────────────────────────────────────────


class KYCActionRequest(BaseModel):
    """PATCH /v1/admin/enterprises/:id/kyc"""
    action: Literal["approve", "reject", "revoke"]


class UserSuspendRequest(BaseModel):
    """PATCH /v1/admin/users/:id/suspend"""
    action: Literal["suspend", "reinstate"]


class BroadcastRequest(BaseModel):
    """POST /v1/admin/broadcast"""
    target: Literal["all", "active_enterprises", "admins_only"]
    priority: Literal["low", "normal", "high", "critical"]
    message: str = Field(..., max_length=1000)


# ── Response schemas ───────────────────────────────────────────────────────────


class AdminStatsResponse(BaseModel):
    """GET /v1/admin/stats — platform-wide aggregate metrics."""
    total_enterprises: int
    active_enterprises: int
    total_users: int
    active_sessions: int
    total_escrow_value: int
    pending_kyc: int
    pending_escrows: int = 0
    llm_calls_today: int
    avg_negotiation_rounds: float
    success_rate: float


class AdminEnterpriseItem(BaseModel):
    """Single enterprise in GET /v1/admin/enterprises list."""
    id: str
    legal_name: str
    kyc_status: str
    trade_role: str
    user_count: int
    created_at: str


class KYCActionResponse(BaseModel):
    """Response for PATCH /v1/admin/enterprises/:id/kyc."""
    id: str
    kyc_status: str
    message: str


class AdminUserItem(BaseModel):
    """Single user in GET /v1/admin/users list."""
    id: str
    full_name: str
    email: str
    role: Literal["ADMIN", "MEMBER"]
    enterprise_id: str
    enterprise_name: str
    status: Literal["ACTIVE", "SUSPENDED"]
    last_login: Optional[str] = None


class UserSuspendResponse(BaseModel):
    """Response for PATCH /v1/admin/users/:id/suspend."""
    id: str
    status: Literal["ACTIVE", "SUSPENDED"]


class AdminAgentItem(BaseModel):
    """Single active agent in GET /v1/admin/agents list."""
    session_id: str
    status: Literal["RUNNING", "PAUSED"]
    current_round: int
    model: str
    latency_ms: int
    buyer: str
    seller: str
    started_at: str


class AgentStatusResponse(BaseModel):
    """Response for POST /v1/admin/agents/:session_id/pause|resume."""
    session_id: str
    status: Literal["RUNNING", "PAUSED"]


class LLMLogItem(BaseModel):
    """Single LLM call entry in GET /v1/admin/llm-logs."""
    id: str
    session_id: str
    round: int
    agent: Literal["BUYER", "SELLER"]
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    status: Literal["SUCCESS", "TIMEOUT", "ERROR"]
    created_at: str
    prompt_summary: str
    response_summary: Optional[str] = None


class BroadcastResponse(BaseModel):
    """Response for POST /v1/admin/broadcast."""
    message_id: str
    recipients: int
    delivered: bool


class ActivityItem(BaseModel):
    """Single item in GET /v1/admin/activity list."""
    id: str
    event_type: str
    title: str
    detail: str
    actor: Optional[str] = None
    amount: Optional[str] = None
    created_at: str


class PendingEscrowItem(BaseModel):
    """Single pending escrow in GET /v1/admin/pending-escrows list."""
    escrow_id: str
    session_id: str
    buyer_name: str
    seller_name: str
    agreed_price_inr: Optional[float] = None
    amount_microalgo: int
    amount_algo: float
    status: str
    created_at: str
