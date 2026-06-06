"""Procurement API endpoints — PO generation, listing, seller acceptance."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.identity.api.dependencies import get_current_user
from src.identity.domain.user import User
from src.shared.api.responses import success_response
from src.shared.infrastructure.db.session import get_db_session

router = APIRouter(prefix="/v1/procurement", tags=["Procurement"])


@router.post("/generate", status_code=201, summary="Generate PO from agreed session")
async def generate_po(
    body: dict,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """POST /v1/procurement/generate — create PO from session_id."""
    from src.procurement.application.services import ProcurementDocumentService

    session_id = body.get("session_id")
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id required")

    svc = ProcurementDocumentService(session)
    try:
        result = await svc.generate_po(uuid.UUID(session_id))
        return success_response(data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", summary="List procurement documents")
async def list_documents(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """GET /v1/procurement — list POs for current enterprise."""
    from src.procurement.application.services import ProcurementDocumentService

    svc = ProcurementDocumentService(session)
    docs = await svc.list_documents(current_user.enterprise_id)
    return success_response(data=docs)


@router.get("/{document_id}", summary="Get procurement document")
async def get_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """GET /v1/procurement/{id} — get PO details."""
    from sqlalchemy import select

    from src.procurement.infrastructure.models import ProcurementDocumentModel

    result = await session.execute(
        select(ProcurementDocumentModel).where(ProcurementDocumentModel.id == document_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if current_user.enterprise_id not in (doc.buyer_enterprise_id, doc.seller_enterprise_id):
        raise HTTPException(status_code=403, detail="Access denied")

    return success_response(data={
        "id": str(doc.id),
        "po_number": doc.po_number,
        "status": doc.status,
        "document_snapshot": doc.document_snapshot,
        "version": doc.version,
        "buyer_accepted_at": str(doc.buyer_accepted_at) if doc.buyer_accepted_at else None,
        "seller_accepted_at": str(doc.seller_accepted_at) if doc.seller_accepted_at else None,
        "created_at": str(doc.created_at),
    })


@router.patch("/{document_id}/seller-accept", summary="Seller accepts PO")
async def seller_accept(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """PATCH /v1/procurement/{id}/seller-accept — seller accepts the PO."""
    from src.procurement.application.services import ProcurementDocumentService

    svc = ProcurementDocumentService(session)
    try:
        result = await svc.seller_accept(document_id, current_user.enterprise_id)
        return success_response(data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
