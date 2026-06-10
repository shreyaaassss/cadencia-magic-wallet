"""Procurement API endpoints — PO generation, listing, seller acceptance."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
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
) -> StreamingResponse:
    """GET /v1/procurement/{id}/download — stream a branded PDF of the PO."""
    import io

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

    # ── Helper: section divider ──────────────────────────────────────────
    def _divider():
        pdf.set_draw_color(180, 180, 180)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(4)

    def _section_header(title: str):
        _divider()
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, title, ln=True)
        pdf.set_font("Helvetica", "", 10)

    def _row(label: str, value, mono: bool = False):
        if value is None:
            return
        pdf.cell(60, 6, label, ln=False)
        if mono:
            pdf.set_font("Courier", "", 9)
        pdf.cell(0, 6, str(value), ln=True)
        if mono:
            pdf.set_font("Helvetica", "", 10)

    # ── Header ───────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 10, "CADENCIA PROCUREMENT ORDER", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"PO Number: {doc.po_number}", ln=True, align="C")
    pdf.cell(0, 6, f"Status: {doc.status.replace('_', ' ')}", ln=True, align="C")
    rfq_ref = snap.get("rfq_reference")
    if rfq_ref:
        pdf.cell(0, 6, f"RFQ Reference: {rfq_ref}", ln=True, align="C")
    pdf.ln(4)

    # ── Parties ──────────────────────────────────────────────────────────
    _divider()
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(95, 7, "BUYER", ln=False)
    pdf.cell(95, 7, "SELLER", ln=True)
    pdf.set_font("Helvetica", "", 10)

    buyer = snap.get("buyer", {})
    seller = snap.get("seller", {})
    for field in ["legal_name", "gstin"]:
        pdf.cell(95, 6, str(buyer.get(field, "")), ln=False)
        pdf.cell(95, 6, str(seller.get(field, "")), ln=True)
    pdf.ln(2)

    # ── Product Details ──────────────────────────────────────────────────
    product = snap.get("product", {})
    if product and any(product.values()):
        _section_header("PRODUCT DETAILS")
        _row("Product:", product.get("name"))
        _row("HSN Code:", product.get("hsn_code"))
        qty = product.get("quantity")
        unit = product.get("unit")
        if qty:
            qty_str = f"{qty} {unit}" if unit else str(qty)
            _row("Quantity:", qty_str)
        _row("Grade:", product.get("grade"))

    # ── Commercial Terms ─────────────────────────────────────────────────
    commercial = snap.get("commercial", {})
    # Fallback for old snapshots that used top-level agreed_price_inr
    agreed_price = commercial.get("agreed_price_inr") or snap.get("agreed_price_inr")

    _section_header("COMMERCIAL TERMS")
    if agreed_price:
        _row("Agreed Price:", f"INR {agreed_price:,.2f}")
        # Calculate unit price if quantity is available
        qty_val = product.get("quantity") if product else None
        if qty_val and float(qty_val) > 0:
            unit_price = agreed_price / float(qty_val)
            unit_label = product.get("unit") or "unit"
            _row("Unit Price:", f"INR {unit_price:,.2f} / {unit_label}")
    _row("Currency:", commercial.get("currency"))
    _row("Payment Terms:", commercial.get("payment_terms"))
    delivery_days = commercial.get("delivery_window_days")
    if delivery_days:
        _row("Delivery Window:", f"{delivery_days} days from PO acceptance")
    round_count = commercial.get("round_count") or snap.get("round_count")
    _row("Negotiation Rounds:", round_count)
    dqs = commercial.get("deal_quality_score")
    if dqs is not None:
        if isinstance(dqs, dict):
            _row("Deal Quality Score:", dqs.get("score", ""))
        else:
            _row("Deal Quality Score:", dqs)

    session_ref = snap.get("session_id")
    if session_ref:
        _row("Session Reference:", session_ref, mono=True)

    # ── Offer Trajectory ─────────────────────────────────────────────────
    trajectory = snap.get("offer_trajectory", [])
    if trajectory:
        _section_header("OFFER TRAJECTORY")
        # Table header
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(30, 6, "Round", border=1, ln=False, align="C")
        pdf.cell(50, 6, "Role", border=1, ln=False, align="C")
        pdf.cell(60, 6, "Price (INR)", border=1, ln=True, align="C")
        pdf.set_font("Helvetica", "", 9)
        for entry in trajectory:
            pdf.cell(30, 6, str(entry.get("round", "")), border=1, ln=False, align="C")
            pdf.cell(50, 6, str(entry.get("role", "")), border=1, ln=False, align="C")
            price_val = entry.get("price")
            price_str = f"{price_val:,.2f}" if price_val else ""
            pdf.cell(60, 6, price_str, border=1, ln=True, align="C")
        if agreed_price:
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(80, 6, "AGREED", border=1, ln=False, align="C")
            pdf.cell(60, 6, f"{agreed_price:,.2f}", border=1, ln=True, align="C")
        pdf.set_font("Helvetica", "", 10)
        pdf.ln(2)

    # ── Escrow & Blockchain ──────────────────────────────────────────────
    escrow = snap.get("escrow")
    if escrow:
        _section_header("ESCROW & BLOCKCHAIN")
        _row("Contract ID:", escrow.get("contract_id"), mono=True)
        _row("Algorand App ID:", escrow.get("app_id"))
        _row("Network:", escrow.get("network"))
        buyer_addr = escrow.get("buyer_address")
        if buyer_addr:
            _row("Buyer Wallet:", f"{buyer_addr[:12]}...{buyer_addr[-6:]}", mono=True)
        seller_addr = escrow.get("seller_address")
        if seller_addr:
            _row("Seller Wallet:", f"{seller_addr[:12]}...{seller_addr[-6:]}", mono=True)
        amt = escrow.get("amount_microalgo")
        if amt:
            _row("Amount Locked:", f"{int(amt) / 1_000_000:.6f} ALGO")
        _row("Deploy Tx ID:", escrow.get("deploy_tx_id"), mono=True)
        _row("Fund Tx ID:", escrow.get("fund_tx_id"), mono=True)
        _row("Release Tx ID:", escrow.get("release_tx_id"), mono=True)

    # ── Dates ────────────────────────────────────────────────────────────
    _section_header("DATES")
    _row("PO Issued:", str(doc.created_at)[:10])
    if doc.buyer_accepted_at:
        _row("Buyer Accepted:", str(doc.buyer_accepted_at)[:10])
    if doc.seller_accepted_at:
        _row("Seller Accepted:", str(doc.seller_accepted_at)[:10])

    # ── Audit Trail ──────────────────────────────────────────────────────
    audit = snap.get("audit", {})
    if audit:
        _section_header("AUDIT TRAIL")
        _row("Session ID:", snap.get("session_id"), mono=True)
        _row("Generated At:", audit.get("generated_at"))
        _row("Document Version:", audit.get("po_version"))

    # ── Footer ───────────────────────────────────────────────────────────
    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, "Generated by Cadencia - AI-native B2B Trade Platform", ln=True, align="C")
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
