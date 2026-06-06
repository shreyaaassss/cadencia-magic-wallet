"""GDPR enterprise deletion service.

Anonymizes enterprise data when deletion is requested. Blocks deletion
if active escrows or pending obligations exist.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, update

log = structlog.get_logger(__name__)


class GDPRDeletionService:
    """Manages GDPR-compliant enterprise data deletion."""

    def __init__(self, session: object) -> None:
        self._session = session

    async def request_deletion(self, enterprise_id: uuid.UUID) -> dict:
        """Mark an enterprise for GDPR deletion. Validates no active obligations."""
        from src.identity.infrastructure.models import EnterpriseModel
        from src.settlement.infrastructure.models import EscrowContractModel

        # Check for active escrows
        active_escrows = await self._session.execute(
            select(EscrowContractModel).where(
                EscrowContractModel.buyer_enterprise_id == enterprise_id,
                EscrowContractModel.status.in_(["PENDING_APPROVAL", "APPROVED", "DEPLOYED", "FUNDED", "DISPATCHED"]),
            )
        )
        if active_escrows.scalars().first():
            raise ValueError("Cannot delete: active escrows exist. Complete or refund them first.")

        seller_escrows = await self._session.execute(
            select(EscrowContractModel).where(
                EscrowContractModel.seller_enterprise_id == enterprise_id,
                EscrowContractModel.status.in_(["PENDING_APPROVAL", "APPROVED", "DEPLOYED", "FUNDED", "DISPATCHED"]),
            )
        )
        if seller_escrows.scalars().first():
            raise ValueError("Cannot delete: active escrows as seller exist.")

        # Mark deletion requested
        await self._session.execute(
            update(EnterpriseModel)
            .where(EnterpriseModel.id == enterprise_id)
            .values(gdpr_deletion_requested_at=datetime.now(timezone.utc))
        )
        await self._session.commit()
        log.info("gdpr_deletion_requested", enterprise_id=str(enterprise_id))
        return {"status": "deletion_requested", "enterprise_id": str(enterprise_id)}

    async def execute_deletion(self, enterprise_id: uuid.UUID) -> dict:
        """Anonymize enterprise data (irreversible)."""
        from src.identity.infrastructure.models import EnterpriseModel, UserModel

        now = datetime.now(timezone.utc)
        hash_suffix = hashlib.sha256(str(enterprise_id).encode()).hexdigest()[:8]

        # Anonymize enterprise
        await self._session.execute(
            update(EnterpriseModel)
            .where(EnterpriseModel.id == enterprise_id)
            .values(
                name=f"DELETED-{hash_suffix}",
                pan="XXXXXXXXXX",
                gstin="XXXXXXXXXXXXXXX",
                algorand_wallet=None,
                kyc_documents=None,
                agent_config=None,
                is_anonymized=True,
                gdpr_deleted_at=now,
            )
        )

        # Anonymize users
        await self._session.execute(
            update(UserModel)
            .where(UserModel.enterprise_id == enterprise_id)
            .values(
                email=f"deleted-{hash_suffix}@anonymized.local",
                full_name=f"Deleted User {hash_suffix}",
                hashed_password="DELETED",
            )
        )

        await self._session.commit()
        log.warning("gdpr_deletion_executed", enterprise_id=str(enterprise_id))
        return {"status": "deleted", "enterprise_id": str(enterprise_id)}
