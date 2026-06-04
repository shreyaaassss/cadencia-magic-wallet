# context.md §4 DIP: dependencies wired here via FastAPI Depends().
# context.md §3: FastAPI imports ONLY in api/ layer.

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.compliance.application.services import ComplianceService
from src.compliance.infrastructure.enterprise_reader import PostgresEnterpriseReader
from src.compliance.infrastructure.fema_gst_exporter import FEMAGSTExporter
from src.compliance.infrastructure.repositories import (
    PostgresAuditLogRepository,
    PostgresExportJobRepository,
    PostgresFEMARepository,
    PostgresGSTRepository,
)
from src.shared.infrastructure.db.session import get_db_session
from src.shared.infrastructure.db.uow import SqlAlchemyUnitOfWork
from src.shared.infrastructure.merkle_service import MerkleService


def get_compliance_service(
    session: AsyncSession = Depends(get_db_session),
) -> ComplianceService:
    """Wire ComplianceService with all concrete adapters."""
    return ComplianceService(
        audit_repo=PostgresAuditLogRepository(session),
        fema_repo=PostgresFEMARepository(session),
        gst_repo=PostgresGSTRepository(session),
        export_job_repo=PostgresExportJobRepository(session),
        enterprise_reader=PostgresEnterpriseReader(session),
        merkle_service=MerkleService(),
        exporter=FEMAGSTExporter(),
        uow=SqlAlchemyUnitOfWork(session),
    )


# Type alias for mypy
ComplianceServiceDep = ComplianceService
