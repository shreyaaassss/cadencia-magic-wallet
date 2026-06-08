"""
Global error handlers.

ALL error responses must use:  { "status": "error", "detail": "..." }
No { "error": { "code": ..., "message": ... } } shape is allowed.
"""

from __future__ import annotations

import structlog
from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.shared.api.responses import error_dict
from src.shared.domain.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BlockchainSimulationError,
    ConflictError,
    DomainError,
    NotFoundError,
    PolicyViolation,
    RateLimitError,
    ValidationError,
)

log = structlog.get_logger(__name__)

# Map exception type → HTTP status code
_STATUS_MAP: dict[type[DomainError], int] = {
    NotFoundError: 404,
    PolicyViolation: 422,
    ValidationError: 400,
    ConflictError: 409,
    RateLimitError: 429,
    BlockchainSimulationError: 502,
    AuthenticationError: 401,
    AuthorizationError: 403,
}


def _resolve_status(exc: DomainError) -> int:
    """Walk the MRO to find the most specific matching status code."""
    for exc_type in type(exc).__mro__:
        if exc_type in _STATUS_MAP:
            return _STATUS_MAP[exc_type]  # type: ignore[index]
    return 500


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    """Handle all DomainError subclasses → { "status": "error", "detail": "..." }."""
    status_code = _resolve_status(exc)

    log.warning(
        "domain_error",
        error_code=exc.error_code,
        message=exc.message,
        status_code=status_code,
        path=str(request.url.path),
    )

    headers: dict[str, str] = {}
    if status_code == 429:
        headers["Retry-After"] = "60"

    return JSONResponse(
        status_code=status_code,
        content=error_dict(exc.message),
        headers=headers,
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle FastAPI HTTPException → { "status": "error", "detail": "..." }.

    For HTTP 402 (x402 payment required), detail is a dict with payment
    requirements — preserve it as-is so clients can parse the JSON fields.
    """
    if exc.status_code == 402 and isinstance(exc.detail, dict):
        return JSONResponse(
            status_code=402,
            content={"status": "error", "detail": exc.detail},
        )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_dict(exc.detail if isinstance(exc.detail, str) else str(exc.detail)),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic validation errors → { "status": "error", "detail": [...] }."""
    # Log the raw body and specific field errors for debugging
    try:
        body = await request.body()
        body_str = body.decode("utf-8", errors="replace")[:2000]  # cap at 2KB
    except Exception:
        body_str = "<unreadable>"

    errors = exc.errors()
    log.warning(
        "validation_error_422",
        path=str(request.url.path),
        method=request.method,
        body_preview=body_str,
        error_count=len(errors),
        errors=errors,
    )

    # Return structured error details so callers can fix their requests
    return JSONResponse(
        status_code=422,
        content={
            "status": "error",
            "detail": errors,
        },
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unhandled exceptions → { "status": "error", "detail": "..." }."""
    log.error(
        "unhandled_exception",
        error=str(exc),
        path=str(request.url.path),
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content=error_dict("An unexpected error occurred. Please try again."),
    )
