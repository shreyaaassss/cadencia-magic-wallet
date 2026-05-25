# context.md §4 — LSP: implements IEnterpriseRepository, IUserRepository,
# IAPIKeyRepository Protocols exactly — Mypy strict verifies substitutability.
# context.md §3 — Infrastructure adapters implement ports; domain never imports adapters.

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.domain.exceptions import NotFoundError
from src.shared.infrastructure.logging import get_logger

from src.identity.domain.enterprise import Enterprise, KYCStatus, TradeRole
from src.identity.domain.user import User, UserRole
from src.identity.domain.value_objects import (
    AlgorandAddress,
    Email,
    GSTIN,
    HashedPassword,
    PAN,
)
from src.identity.infrastructure.models import APIKeyModel, EnterpriseModel, UserModel

log = get_logger(__name__)


# ── Mapping helpers ───────────────────────────────────────────────────────────

def _enterprise_to_domain(m: EnterpriseModel) -> Enterprise:
    """
    Reconstruct an Enterprise aggregate from an ORM model.

    Value object construction skips format validation on load — data was valid on save.
    """
    algo_wallet = None
    if m.algorand_wallet:
        # Skip validation on load — address was valid when stored
        object.__setattr__(AlgorandAddress.__new__(AlgorandAddress), "value", m.algorand_wallet)
        # Use direct construction to bypass __post_init__ validation on reload
        algo_wallet = _make_algorand_address_unchecked(m.algorand_wallet)

    enterprise = Enterprise(
        id=m.id,
        created_at=m.created_at if isinstance(m.created_at, datetime) else datetime.now(tz=timezone.utc),
        updated_at=m.updated_at if isinstance(m.updated_at, datetime) else datetime.now(tz=timezone.utc),
        legal_name=m.name,
        pan=_make_pan_unchecked(m.pan),
        gstin=_make_gstin_unchecked(m.gstin),
        kyc_status=KYCStatus(m.kyc_status),
        trade_role=TradeRole(m.trade_role),
        algorand_wallet=algo_wallet,
        industry_vertical=m.kyc_documents.get("industry_vertical") if m.kyc_documents else None,
        geography=m.kyc_documents.get("geography", "IN") if m.kyc_documents else "IN",
        commodities=list(m.kyc_documents.get("commodities", [])) if m.kyc_documents else [],
        min_order_value=Decimal(str(m.kyc_documents["min_order_value"]))
            if m.kyc_documents and m.kyc_documents.get("min_order_value") is not None else None,
        max_order_value=Decimal(str(m.kyc_documents["max_order_value"]))
            if m.kyc_documents and m.kyc_documents.get("max_order_value") is not None else None,
        kyc_documents=m.kyc_documents,
        agent_config=m.agent_config,
        listing_active=True,
    )
    # Enhanced onboarding fields (stored in dedicated DB columns)
    enterprise.facility_type = m.facility_type
    enterprise.payment_terms_accepted = list(m.payment_terms_accepted) if m.payment_terms_accepted else []
    enterprise.credit_period_days = m.credit_period_days
    enterprise.years_in_operation = m.years_in_operation
    enterprise.annual_turnover_inr = Decimal(str(m.annual_turnover_inr)) if m.annual_turnover_inr else None
    enterprise.quality_certifications = list(m.quality_certifications) if m.quality_certifications else []
    enterprise.test_certificate_available = bool(m.test_certificate_available) if m.test_certificate_available else False
    enterprise.third_party_inspection_allowed = bool(m.third_party_inspection_allowed) if m.third_party_inspection_allowed else False
    return enterprise


def _enterprise_to_model(e: Enterprise, existing: EnterpriseModel | None = None) -> EnterpriseModel:
    """Map Enterprise domain aggregate to ORM model."""
    # Merge agent config into kyc_documents JSONB field for storage
    agent_config: dict = {}
    if e.industry_vertical is not None:
        agent_config["industry_vertical"] = e.industry_vertical
    if e.geography:
        agent_config["geography"] = e.geography
    if e.commodities:
        agent_config["commodities"] = e.commodities
    if e.min_order_value is not None:
        agent_config["min_order_value"] = float(e.min_order_value)
    if e.max_order_value is not None:
        agent_config["max_order_value"] = float(e.max_order_value)
    # Merge with existing kyc_documents
    if e.kyc_documents:
        agent_config = {**e.kyc_documents, **agent_config}

    if existing is not None:
        existing.name = e.legal_name
        existing.pan = e.pan.value
        existing.gstin = e.gstin.value
        existing.kyc_status = e.kyc_status.value
        existing.trade_role = e.trade_role.value
        existing.algorand_wallet = e.algorand_wallet.value if e.algorand_wallet else None
        existing.kyc_documents = agent_config or None
        existing.agent_config = e.agent_config
        # Enhanced onboarding fields
        existing.facility_type = getattr(e, "facility_type", None)
        existing.payment_terms_accepted = getattr(e, "payment_terms_accepted", None) or None
        existing.credit_period_days = getattr(e, "credit_period_days", None)
        existing.years_in_operation = getattr(e, "years_in_operation", None)
        existing.annual_turnover_inr = float(e.annual_turnover_inr) if getattr(e, "annual_turnover_inr", None) else None
        existing.quality_certifications = getattr(e, "quality_certifications", None) or None
        existing.test_certificate_available = getattr(e, "test_certificate_available", False)
        existing.third_party_inspection_allowed = getattr(e, "third_party_inspection_allowed", False)
        return existing

    return EnterpriseModel(
        id=e.id,
        name=e.legal_name,
        pan=e.pan.value,
        gstin=e.gstin.value,
        kyc_status=e.kyc_status.value,
        trade_role=e.trade_role.value,
        algorand_wallet=e.algorand_wallet.value if e.algorand_wallet else None,
        kyc_documents=agent_config or None,
        agent_config=e.agent_config,
        facility_type=getattr(e, "facility_type", None),
        payment_terms_accepted=getattr(e, "payment_terms_accepted", None) or None,
        credit_period_days=getattr(e, "credit_period_days", None),
        years_in_operation=getattr(e, "years_in_operation", None),
        annual_turnover_inr=float(e.annual_turnover_inr) if getattr(e, "annual_turnover_inr", None) else None,
        quality_certifications=getattr(e, "quality_certifications", None) or None,
        test_certificate_available=getattr(e, "test_certificate_available", False),
        third_party_inspection_allowed=getattr(e, "third_party_inspection_allowed", False),
    )


def _user_to_domain(m: UserModel) -> User:
    """Reconstruct User from ORM model — skip validation on load."""
    return User(
        id=m.id,
        created_at=m.created_at if isinstance(m.created_at, datetime) else datetime.now(tz=timezone.utc),
        updated_at=m.created_at if isinstance(m.created_at, datetime) else datetime.now(tz=timezone.utc),
        enterprise_id=m.enterprise_id,
        email=_make_email_unchecked(m.email),
        password=HashedPassword(value=m.password_hash),
        full_name=None,
        role=UserRole(m.role),
        last_login=m.last_login_at if isinstance(m.last_login_at, datetime) else None,
        is_active=bool(m.is_active),
    )


def _user_to_model(u: User, existing: UserModel | None = None) -> UserModel:
    if existing is not None:
        existing.email = u.email.value
        existing.password_hash = u.password.value
        existing.role = u.role.value
        existing.is_active = u.is_active
        existing.last_login_at = u.last_login
        return existing
    return UserModel(
        id=u.id,
        enterprise_id=u.enterprise_id,
        email=u.email.value,
        role=u.role.value,
        password_hash=u.password.value,
        is_active=u.is_active,
        last_login_at=u.last_login,
    )


# ── Unchecked value object constructors (bypass __post_init__ on reload) ──────

def _make_pan_unchecked(value: str) -> PAN:
    obj = object.__new__(PAN)
    object.__setattr__(obj, "value", value)
    return obj


def _make_gstin_unchecked(value: str) -> GSTIN:
    obj = object.__new__(GSTIN)
    object.__setattr__(obj, "value", value)
    return obj


def _make_email_unchecked(value: str) -> Email:
    obj = object.__new__(Email)
    object.__setattr__(obj, "value", value.lower())
    return obj


def _make_algorand_address_unchecked(value: str) -> AlgorandAddress:
    obj = object.__new__(AlgorandAddress)
    object.__setattr__(obj, "value", value)
    return obj


# ── PostgresEnterpriseRepository ──────────────────────────────────────────────

class PostgresEnterpriseRepository:
    """
    Implements IEnterpriseRepository using async SQLAlchemy.
    context.md §4 LSP: any conforming IEnterpriseRepository is substitutable.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, enterprise: Enterprise) -> None:
        model = _enterprise_to_model(enterprise)
        self._session.add(model)
        await self._session.flush()

    async def get_by_id(self, enterprise_id: uuid.UUID) -> Enterprise | None:
        result = await self._session.execute(
            select(EnterpriseModel).where(EnterpriseModel.id == enterprise_id)
        )
        model = result.scalar_one_or_none()
        return _enterprise_to_domain(model) if model else None

    async def get_by_pan(self, pan: str) -> Enterprise | None:
        result = await self._session.execute(
            select(EnterpriseModel).where(EnterpriseModel.pan == pan)
        )
        model = result.scalar_one_or_none()
        return _enterprise_to_domain(model) if model else None

    async def get_by_gstin(self, gstin: str) -> Enterprise | None:
        result = await self._session.execute(
            select(EnterpriseModel).where(EnterpriseModel.gstin == gstin)
        )
        model = result.scalar_one_or_none()
        return _enterprise_to_domain(model) if model else None

    async def get_by_wallet_address(self, wallet_address: str) -> Enterprise | None:
        result = await self._session.execute(
            select(EnterpriseModel).where(EnterpriseModel.algorand_wallet == wallet_address)
        )
        model = result.scalar_one_or_none()
        return _enterprise_to_domain(model) if model else None

    async def update(self, enterprise: Enterprise) -> None:
        result = await self._session.execute(
            select(EnterpriseModel).where(EnterpriseModel.id == enterprise.id)
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            raise NotFoundError("Enterprise", str(enterprise.id))
        _enterprise_to_model(enterprise, existing=existing)
        await self._session.flush()


# ── PostgresUserRepository ────────────────────────────────────────────────────

class PostgresUserRepository:
    """Implements IUserRepository using async SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, user: User) -> None:
        model = _user_to_model(user)
        self._session.add(model)
        await self._session.flush()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
        model = result.scalar_one_or_none()
        return _user_to_domain(model) if model else None

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.email == email.lower())
        )
        model = result.scalar_one_or_none()
        return _user_to_domain(model) if model else None

    async def update(self, user: User) -> None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.id == user.id)
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            raise NotFoundError("User", str(user.id))
        _user_to_model(user, existing=existing)
        await self._session.flush()

    async def list_by_enterprise(self, enterprise_id: uuid.UUID) -> list[User]:
        result = await self._session.execute(
            select(UserModel).where(UserModel.enterprise_id == enterprise_id)
        )
        return [_user_to_domain(m) for m in result.scalars().all()]


# ── PostgresAPIKeyRepository ──────────────────────────────────────────────────

class PostgresAPIKeyRepository:
    """
    Implements IAPIKeyRepository.
    context.md §14: only key_hash stored — plaintext never touches DB.
    Revoked keys (revoked_at IS NOT NULL) are not returned by get_by_hash.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(
        self,
        key_hash: str,
        enterprise_id: uuid.UUID,
        key_id: uuid.UUID,
        label: str | None,
    ) -> None:
        model = APIKeyModel(
            id=key_id,
            enterprise_id=enterprise_id,
            name=label or "API Key",
            key_hash=key_hash,
            is_active=True,
        )
        self._session.add(model)
        await self._session.flush()

    async def get_by_hash(self, key_hash: str) -> dict | None:
        """Return key metadata or None if not found or revoked."""
        from sqlalchemy import and_

        result = await self._session.execute(
            select(APIKeyModel).where(
                and_(
                    APIKeyModel.key_hash == key_hash,
                    APIKeyModel.is_active == True,  # noqa: E712
                )
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return {
            "key_id": model.id,
            "enterprise_id": model.enterprise_id,
            "label": model.name,
        }

    async def revoke(self, key_id: uuid.UUID, enterprise_id: uuid.UUID) -> None:
        result = await self._session.execute(
            select(APIKeyModel).where(
                APIKeyModel.id == key_id,
                APIKeyModel.enterprise_id == enterprise_id,
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            raise NotFoundError("APIKey", str(key_id))
        model.is_active = False
        await self._session.flush()

    async def list_by_enterprise(self, enterprise_id: uuid.UUID) -> list[dict]:
        result = await self._session.execute(
            select(APIKeyModel).where(APIKeyModel.enterprise_id == enterprise_id)
        )
        return [
            {
                "key_id": m.id,
                "label": m.name,
                "is_active": m.is_active,
                "created_at": m.created_at,
                "last_used_at": m.last_used_at,
            }
            for m in result.scalars().all()
        ]
