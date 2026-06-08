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


@router.get("/{document_id}/download", summary="Download PO as PDF")
async def download_po_pdf(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> "StreamingResponse":
    """GET /v1/procurement/{id}/download — stream a branded PDF of the PO."""
    import io

    from fastapi.responses import StreamingResponse
    from fpdf import FPDF
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

    snap = doc.document_snapshot or {}

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Header
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 10, "PURCHASE ORDER", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"PO Number: {doc.po_number}", ln=True, align="C")
    pdf.cell(0, 6, f"Status: {doc.status.replace('_', ' ')}", ln=True, align="C")
    pdf.ln(6)

    # Divider
    pdf.set_draw_color(180, 180, 180)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)

    # Parties
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(95, 7, "BUYER", ln=False)
    pdf.cell(95, 7, "SELLER", ln=True)
    pdf.set_font("Helvetica", "", 10)

    buyer = snap.get("buyer", {})
    seller = snap.get("seller", {})
    for field in ["legal_name", "pan", "gstin"]:
        pdf.cell(95, 6, buyer.get(field, ""), ln=False)
        pdf.cell(95, 6, seller.get(field, ""), ln=True)
    pdf.ln(4)

    # Commercial Terms
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "COMMERCIAL TERMS", ln=True)
    pdf.set_font("Helvetica", "", 10)

    agreed_price = snap.get("agreed_price_inr")
    if agreed_price:
        formatted = f"INR {agreed_price:,.2f}"
        pdf.cell(60, 6, "Agreed Price:", ln=False)
        pdf.cell(0, 6, formatted, ln=True)

    round_count = snap.get("round_count")
    if round_count:
        pdf.cell(60, 6, "Negotiation Rounds:", ln=False)
        pdf.cell(0, 6, str(round_count), ln=True)

    session_id = snap.get("session_id")
    if session_id:
        pdf.cell(60, 6, "Session Reference:", ln=False)
        pdf.set_font("Courier", "", 9)
        pdf.cell(0, 6, str(session_id), ln=True)
        pdf.set_font("Helvetica", "", 10)

    # Dates
    pdf.ln(2)
    pdf.cell(60, 6, "PO Issued:", ln=False)
    pdf.cell(0, 6, str(doc.created_at)[:10], ln=True)
    if doc.buyer_accepted_at:
        pdf.cell(60, 6, "Buyer Accepted:", ln=False)
        pdf.cell(0, 6, str(doc.buyer_accepted_at)[:10], ln=True)
    if doc.seller_accepted_at:
        pdf.cell(60, 6, "Seller Accepted:", ln=False)
        pdf.cell(0, 6, str(doc.seller_accepted_at)[:10], ln=True)

    # Footer
    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, "Generated by Cadencia — AI-native B2B Trade Platform", ln=True, align="C")
    pdf.cell(0, 5, "This document is legally binding upon seller acceptance.", ln=True, align="C")

    buf = io.BytesIO(pdf.output())
    filename = f"{doc.po_number.replace('-', '_')}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
