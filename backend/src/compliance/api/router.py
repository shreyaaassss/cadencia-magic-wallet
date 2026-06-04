# context.md §10: All endpoints versioned under /v1/.
# context.md §10: All responses use ApiResponse[T] envelope.
# context.md §14: Auth via get_current_user + require_role.

from __future__ import annotations

import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from src.compliance.api.dependencies import ComplianceServiceDep, get_compliance_service
from src.compliance.api.schemas import (
    AuditChainVerifyResponse,
    AuditEntryResponse,
    AuditLogPageResponse,
    BulkExportRequest,
    ExportJobResponse,
    FEMARecordResponse,
    GSTRecordResponse,
    decode_cursor,
    encode_cursor,
)
from src.compliance.application.commands import (
    RequestBulkExportCommand,
)
from src.compliance.application.queries import (
    ExportFEMAPDFQuery,
    ExportGSTCSVQuery,
    GetAuditLogQuery,
    GetExportJobQuery,
    GetFEMARecordQuery,
    GetGSTRecordQuery,
    VerifyAuditChainQuery,
)
from src.identity.api.dependencies import get_current_user, rate_limit, require_role
from src.identity.domain.user import User
from src.shared.api.responses import ApiResponse, success_response
from src.shared.infrastructure.logging import get_logger

log = get_logger(__name__)

# Two routers: audit/ and compliance/
audit_router = APIRouter(prefix="/v1/audit", tags=["audit"])
compliance_router = APIRouter(prefix="/v1/compliance", tags=["compliance"])


# ── GET /v1/audit/{escrow_id} ─────────────────────────────────────────────────


@audit_router.get(
    "/{escrow_id}",
    response_model=ApiResponse[AuditLogPageResponse],
    summary="Get paginated audit log for an escrow",
    dependencies=[Depends(rate_limit)],
)
async def get_audit_log(
    escrow_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    svc: ComplianceServiceDep = Depends(get_compliance_service),
) -> ApiResponse[AuditLogPageResponse]:
    after_dt = decode_cursor(cursor) if cursor else None
    entries, raw_cursor = await svc.get_audit_log(
        GetAuditLogQuery(
            escrow_id=escrow_id,
            requesting_enterprise_id=current_user.enterprise_id,
            cursor=after_dt,
            limit=min(max(1, limit), 100),
        )
    )
    next_cursor = encode_cursor(
        entries[-1].created_at
    ) if raw_cursor and entries else None
    return success_response(
        AuditLogPageResponse(
            entries=[AuditEntryResponse.from_domain(e) for e in entries],
            next_cursor=next_cursor,
        )
    )


# ── GET /v1/audit/{escrow_id}/verify ─────────────────────────────────────────


@audit_router.get(
    "/{escrow_id}/verify",
    response_model=ApiResponse[AuditChainVerifyResponse],
    summary="Verify the SHA-256 hash chain integrity for an escrow audit log",
    dependencies=[Depends(rate_limit)],
)
async def verify_audit_chain(
    escrow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    svc: ComplianceServiceDep = Depends(get_compliance_service),
) -> ApiResponse[AuditChainVerifyResponse]:
    entries = await svc._audit.list_all_entries(escrow_id)
    is_valid, first_invalid = await svc.verify_audit_chain(
        VerifyAuditChainQuery(
            escrow_id=escrow_id,
            requesting_enterprise_id=current_user.enterprise_id,
        )
    )
    return success_response(
        AuditChainVerifyResponse(
            valid=is_valid,
            entry_count=len(entries),
            first_invalid_sequence_no=first_invalid,
        )
    )


# ── GET /v1/compliance/{escrow_id}/fema ──────────────────────────────────────


@compliance_router.get(
    "/{escrow_id}/fema",
    response_model=ApiResponse[FEMARecordResponse],
    summary="Get FEMA compliance record for an escrow",
    dependencies=[Depends(rate_limit)],
)
async def get_fema_record(
    escrow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    svc: ComplianceServiceDep = Depends(get_compliance_service),
) -> ApiResponse[FEMARecordResponse]:
    record = await svc.get_fema_record(
        GetFEMARecordQuery(
            escrow_id=escrow_id,
            requesting_enterprise_id=current_user.enterprise_id,
        )
    )
    return success_response(FEMARecordResponse.from_domain(record))


# ── GET /v1/compliance/{escrow_id}/gst ───────────────────────────────────────


@compliance_router.get(
    "/{escrow_id}/gst",
    response_model=ApiResponse[GSTRecordResponse],
    summary="Get GST compliance record for an escrow",
    dependencies=[Depends(rate_limit)],
)
async def get_gst_record(
    escrow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    svc: ComplianceServiceDep = Depends(get_compliance_service),
) -> ApiResponse[GSTRecordResponse]:
    record = await svc.get_gst_record(
        GetGSTRecordQuery(
            escrow_id=escrow_id,
            requesting_enterprise_id=current_user.enterprise_id,
        )
    )
    return success_response(GSTRecordResponse.from_domain(record))


# ── GET /v1/compliance/{escrow_id}/fema/pdf ──────────────────────────────────


@compliance_router.get(
    "/{escrow_id}/fema/pdf",
    summary="Export FEMA record as PDF (streaming)",
    dependencies=[Depends(rate_limit)],
)
async def export_fema_pdf(
    escrow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    svc: ComplianceServiceDep = Depends(get_compliance_service),
) -> StreamingResponse:
    pdf_bytes = await svc.export_fema_pdf(
        ExportFEMAPDFQuery(
            escrow_id=escrow_id,
            requesting_enterprise_id=current_user.enterprise_id,
        )
    )
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=fema_{escrow_id}.pdf",
            "Content-Length": str(len(pdf_bytes)),
        },
    )


# ── GET /v1/compliance/{escrow_id}/gst/csv ───────────────────────────────────


@compliance_router.get(
    "/{escrow_id}/gst/csv",
    summary="Export GST record as CSV (streaming)",
    dependencies=[Depends(rate_limit)],
)
async def export_gst_csv(
    escrow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    svc: ComplianceServiceDep = Depends(get_compliance_service),
) -> StreamingResponse:
    csv_bytes = await svc.export_gst_csv(
        ExportGSTCSVQuery(
            escrow_id=escrow_id,
            requesting_enterprise_id=current_user.enterprise_id,
        )
    )
    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=gst_{escrow_id}.csv",
            "Content-Length": str(len(csv_bytes)),
        },
    )


# ── POST /v1/compliance/export/zip ───────────────────────────────────────────


@compliance_router.post(
    "/export/zip",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ApiResponse[ExportJobResponse],
    summary="Request bulk ZIP export of FEMA + GST records (ADMIN only)",
    dependencies=[Depends(require_role("ADMIN")), Depends(rate_limit)],
)
async def request_bulk_export(
    request_body: BulkExportRequest,
    current_user: User = Depends(get_current_user),
    svc: ComplianceServiceDep = Depends(get_compliance_service),
) -> ApiResponse[ExportJobResponse]:
    """
    Generate a ZIP containing FEMA PDFs + GST CSV for the requested escrows.

    Phase 3: synchronous generation (stored in Redis with 1-hour TTL).
    The response includes the redis_key to retrieve the ZIP in a future
    GET /v1/compliance/export/zip/{job_id}/download endpoint (Phase 5+).
    """
    import uuid as _uuid
    cmd = RequestBulkExportCommand(
        escrow_ids=request_body.escrow_ids,
        requested_by_enterprise_id=current_user.enterprise_id,
        job_id=_uuid.uuid4(),
    )

    # Build zip synchronously; store in Redis via router (Phase 3 approach)
    zip_bytes_holder: dict = {}

    # Monkey-patch exporter to capture zip bytes
    original_build_zip = svc._exporter.build_zip

    def _capture_build_zip(fema_records, gst_records):  # type: ignore[no-untyped-def]
        result = original_build_zip(fema_records, gst_records)
        zip_bytes_holder["bytes"] = result
        return result

    svc._exporter.build_zip = _capture_build_zip  # type: ignore[method-assign]

    job_id = await svc.request_bulk_export(cmd)

    # Store in Redis if we captured bytes
    if zip_bytes_holder.get("bytes"):
        try:
            from src.shared.infrastructure.cache.redis_client import get_redis_client
            redis = get_redis_client()
            redis_key = f"compliance:export:{job_id}"
            await redis.setex(redis_key, 3600, zip_bytes_holder["bytes"])
        except Exception:
            log.warning("bulk_export_redis_store_failed", job_id=str(job_id))

    job = await svc.get_export_job(
        GetExportJobQuery(
            job_id=job_id,
            requesting_enterprise_id=current_user.enterprise_id,
        )
    )
    from datetime import datetime
    return success_response(
        ExportJobResponse(
            job_id=job_id,
            status=job["status"],
            redis_key=job.get("redis_key"),
            error_message=job.get("error_message"),
            created_at=job.get("created_at") or datetime.utcnow(),
            completed_at=job.get("completed_at"),
        )
    )


# ── GET /v1/compliance/export/zip/{job_id}/download ─────────────────────────


@compliance_router.get(
    "/export/zip/{job_id}/download",
    summary="Download a previously generated compliance ZIP export",
    dependencies=[Depends(require_role("ADMIN")), Depends(rate_limit)],
)
async def download_compliance_zip(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """
    Stream the ZIP file stored in Redis by the POST /export/zip handler.
    The ZIP is stored with a 1-hour TTL under key compliance:export:{job_id}.
    """
    from src.shared.infrastructure.cache.redis_client import get_redis_client

    redis = get_redis_client()
    redis_key = f"compliance:export:{job_id}"
    zip_data = await redis.get(redis_key)

    if not zip_data:
        raise HTTPException(
            status_code=404,
            detail="Export job not found or expired. Please request a new export.",
        )

    # zip_data may be str (if decode_responses=True) or bytes
    if isinstance(zip_data, str):
        zip_data = zip_data.encode("latin-1")

    return StreamingResponse(
        io.BytesIO(zip_data),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="compliance_{job_id}.zip"',
            "Content-Length": str(len(zip_data)),
        },
    )
