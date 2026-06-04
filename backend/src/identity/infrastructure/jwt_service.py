# context.md §14: JWT access tokens — RS256-signed, 15-minute expiry.
# context.md §14: Refresh tokens — httpOnly, Secure, SameSite=Strict cookie, 30-day.
# context.md §14: HS256 is PROHIBITED in production. RS256 required.

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt  # type: ignore[import-untyped]

from src.shared.domain.exceptions import ValidationError
from src.shared.infrastructure.logging import get_logger

log = get_logger(__name__)

_ACCESS_EXPIRE_MINUTES = int(os.environ.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
_REFRESH_EXPIRE_DAYS = int(os.environ.get("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "30"))


def _get_algorithm() -> str:
    """
    Use RS256 when private key is configured.
    Fall back to HS256 in development ONLY.

    context.md §14: HS256 PROHIBITED in production.
    """
    if os.environ.get("APP_ENV") == "production":
        if not os.environ.get("JWT_PRIVATE_KEY"):
            raise RuntimeError(
                "JWT_PRIVATE_KEY must be set in production (context.md §14)."
            )
    return "RS256" if os.environ.get("JWT_PRIVATE_KEY") else "HS256"


def _get_signing_key() -> str:
    private_key = os.environ.get("JWT_PRIVATE_KEY", "")
    if private_key:
        return private_key.replace("\\n", "\n")
    secret = os.environ.get("JWT_SECRET_KEY", "dev-insecure-secret-change-me")
    return secret


def _get_verifying_key() -> str:
    public_key = os.environ.get("JWT_PUBLIC_KEY", "")
    if public_key:
        return public_key.replace("\\n", "\n")
    return os.environ.get("JWT_SECRET_KEY", "dev-insecure-secret-change-me")


class JWTService:
    """
    Implements IJWTService.

    RS256 when JWT_PRIVATE_KEY / JWT_PUBLIC_KEY env vars set.
    HS256 fallback for development only (context.md §14).
    """

    def create_access_token(
        self,
        subject: str,
        enterprise_id: uuid.UUID,
        role: str,
        trade_role: str | None = None,
    ) -> str:
        now = datetime.now(tz=timezone.utc)
        payload = {
            "sub": subject,
            "enterprise_id": str(enterprise_id),
            "role": role,
            "trade_role": trade_role,  # BUYER | SELLER | BOTH | None
            "iat": now,
            "exp": now + timedelta(minutes=_ACCESS_EXPIRE_MINUTES),
            "jti": str(uuid.uuid4()),   # Enables future token revocation
            "type": "access",
        }
        return jwt.encode(payload, _get_signing_key(), algorithm=_get_algorithm())

    def create_refresh_token(self, subject: str) -> str:
        now = datetime.now(tz=timezone.utc)
        payload = {
            "sub": subject,
            "iat": now,
            "exp": now + timedelta(days=_REFRESH_EXPIRE_DAYS),
            "jti": str(uuid.uuid4()),
            "type": "refresh",
        }
        return jwt.encode(payload, _get_signing_key(), algorithm=_get_algorithm())

    def decode_access_token(self, token: str) -> dict:
        """
        Decode and verify an access token.

        Raises ValidationError on expired or invalid token.
        """
        try:
            payload: dict = jwt.decode(
                token,
                _get_verifying_key(),
                algorithms=[_get_algorithm()],
            )
            if payload.get("type") != "access":
                raise ValidationError("Token is not an access token.")
            return payload
        except JWTError as exc:
            raise ValidationError(f"Invalid or expired access token: {exc}") from exc

    def decode_refresh_token(self, token: str) -> dict:
        """
        Decode and verify a refresh token.

        Raises ValidationError on expired or invalid token.
        """
        try:
            payload: dict = jwt.decode(
                token,
                _get_verifying_key(),
                algorithms=[_get_algorithm()],
            )
            if payload.get("type") != "refresh":
                raise ValidationError("Token is not a refresh token.")
            return payload
        except JWTError as exc:
            raise ValidationError(f"Invalid or expired refresh token: {exc}") from exc
