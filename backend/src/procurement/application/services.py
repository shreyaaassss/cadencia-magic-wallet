"""Procurement document service — PO generation and seller acceptance."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import func as sa_func
from sqlalchemy import select

from src.procurement.infrastructure.models import ProcurementDocumentModel

log = structlog.get_logger(__name__)


class ProcurementDocumentService:
    """Generates and manages procurement documents (purchase orders)."""

    def __init__(self, session: object) -> None:
        self._session = session

    async def generate_po(self, session_id: uuid.UUID) -> dict:
        """Generate a PO from an agreed negotiation session."""
        from src.identity.infrastructure.models import EnterpriseModel
        from src.negotiation.infrastructure.models import NegotiationSessionModel, OfferModel
        from src.settlement.infrastructure.models import EscrowContractModel

        # Load session
        sess_result = await self._session.execute(
            select(NegotiationSessionModel).where(NegotiationSessionModel.id == session_id)
        )
        session_row = sess_result.scalar_one_or_none()
        if not session_row:
            raise ValueError("Session not found")
        if session_row.status != "AGREED":
            raise ValueError("Can only generate PO for AGREED sessions")

        # Check for existing PO
        existing = await self._session.execute(
            select(ProcurementDocumentModel).where(
                ProcurementDocumentModel.session_id == session_id
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError("PO already exists for this session")

        # Load buyer + seller enterprises
        buyer = await self._session.execute(
            select(EnterpriseModel).where(EnterpriseModel.id == session_row.buyer_enterprise_id)
        )
        seller = await self._session.execute(
            select(EnterpriseModel).where(EnterpriseModel.id == session_row.seller_enterprise_id)
        )
        buyer_ent = buyer.scalar_one()
        seller_ent = seller.scalar_one()

        # Load offers for trajectory
        offers_result = await self._session.execute(
            select(OfferModel)
            .where(OfferModel.session_id == session_id)
            .order_by(OfferModel.round_number)
        )
        offers = offers_result.scalars().all()

        # Load RFQ for product context
        rfq = None
        if session_row.rfq_id:
            from src.marketplace.infrastructure.models import RFQModel

            rfq_result = await self._session.execute(
                select(RFQModel).where(RFQModel.id == session_row.rfq_id)
            )
            rfq = rfq_result.scalar_one_or_none()

        # Load escrow (may not exist yet)
        escrow_result = await self._session.execute(
            select(EscrowContractModel).where(EscrowContractModel.session_id == session_id)
        )
        escrow = escrow_result.scalar_one_or_none()

        # Generate PO number
        po_number = await self._generate_po_number()

        # Build enriched document snapshot
        agreed_terms = session_row.agreed_terms_json or {}
        product_ctx = session_row.product_context or {}
        parsed = (rfq.parsed_fields or {}) if rfq else {}

        snapshot = {
            "po_number": po_number,
            "session_id": str(session_id),
            "rfq_reference": str(session_row.rfq_id) if session_row.rfq_id else None,
            "buyer": {
                "legal_name": buyer_ent.name,
                "pan": buyer_ent.pan,
                "gstin": buyer_ent.gstin,
                "enterprise_id": str(session_row.buyer_enterprise_id),
            },
            "seller": {
                "legal_name": seller_ent.name,
                "pan": seller_ent.pan,
                "gstin": seller_ent.gstin,
                "enterprise_id": str(session_row.seller_enterprise_id),
            },
            "product": {
                "name": product_ctx.get("product") or (rfq.product_name if rfq else None),
                "hsn_code": product_ctx.get("hsn_code") or (rfq.hsn_code if rfq else None),
                "quantity": product_ctx.get("quantity") or (rfq.quantity if rfq else None),
                "unit": product_ctx.get("unit") or (rfq.quantity_unit if rfq else None),
                "grade": product_ctx.get("grade") or parsed.get("grade"),
            },
            "commercial": {
                "agreed_price_inr": float(session_row.agreed_price) if session_row.agreed_price else None,
                "currency": "INR",
                "payment_terms": agreed_terms.get("payment_terms") or parsed.get("preferred_payment_terms"),
                "delivery_window_days": agreed_terms.get("delivery_window") or (rfq.delivery_window_days if rfq else None),
                "round_count": session_row.current_round,
                "deal_quality_score": session_row.deal_quality_score,
            },
            "offer_trajectory": [
                {
                    "round": o.round_number,
                    "role": o.proposer_role,
                    "price": float(o.price),
                }
                for o in offers
            ],
            "escrow": {
                "contract_id": str(escrow.id),
                "app_id": escrow.algo_app_id,
                "network": "algorand-testnet",
                "buyer_address": escrow.buyer_algorand_address,
                "seller_address": escrow.seller_algorand_address,
                "amount_microalgo": escrow.amount_microalgo,
                "fund_tx_id": escrow.fund_tx_id,
            } if escrow else None,
            "audit": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "po_version": 1,
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        doc = ProcurementDocumentModel(
            id=uuid.uuid4(),
            po_number=po_number,
            session_id=session_id,
            escrow_id=escrow.id if escrow else None,
            buyer_enterprise_id=session_row.buyer_enterprise_id,
            seller_enterprise_id=session_row.seller_enterprise_id,
            status="PENDING_SELLER_ACCEPTANCE",
            document_snapshot=snapshot,
            buyer_accepted_at=datetime.now(timezone.utc),
        )
        self._session.add(doc)
        await self._session.commit()

        log.info("po_generated", po_number=po_number, session_id=str(session_id))
        return {
            "id": str(doc.id),
            "po_number": po_number,
            "status": doc.status,
            "document_snapshot": snapshot,
        }

    async def seller_accept(self, document_id: uuid.UUID, seller_enterprise_id: uuid.UUID) -> dict:
        """Seller accepts the PO."""
        result = await self._session.execute(
            select(ProcurementDocumentModel).where(ProcurementDocumentModel.id == document_id)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            raise ValueError("Document not found")
        if str(doc.seller_enterprise_id) != str(seller_enterprise_id):
            raise ValueError("Only the seller can accept")
        if doc.status != "PENDING_SELLER_ACCEPTANCE":
            raise ValueError(f"Cannot accept document in {doc.status} state")

        doc.seller_accepted_at = datetime.now(timezone.utc)
        doc.status = "ACTIVE"
        await self._session.commit()

        log.info("po_accepted", document_id=str(document_id))
        return {"id": str(doc.id), "status": "ACTIVE"}

    async def list_documents(self, enterprise_id: uuid.UUID, limit: int = 20) -> list[dict]:
        """List POs for an enterprise (buyer or seller)."""
        from sqlalchemy import or_

        result = await self._session.execute(
            select(ProcurementDocumentModel)
            .where(or_(
                ProcurementDocumentModel.buyer_enterprise_id == enterprise_id,
                ProcurementDocumentModel.seller_enterprise_id == enterprise_id,
            ))
            .order_by(ProcurementDocumentModel.created_at.desc())
            .limit(limit)
        )
        docs = result.scalars().all()
        return [
            {
                "id": str(d.id),
                "po_number": d.po_number,
                "status": d.status,
                "buyer_enterprise_id": str(d.buyer_enterprise_id),
                "seller_enterprise_id": str(d.seller_enterprise_id),
                "created_at": str(d.created_at),
            }
            for d in docs
        ]

    async def _generate_po_number(self) -> str:
        """Generate sequential PO number: PO-YYYY-NNNNN."""
        year = datetime.now(timezone.utc).year
        result = await self._session.execute(
            select(sa_func.count()).select_from(ProcurementDocumentModel)
        )
        count = (result.scalar() or 0) + 1
        return f"PO-{year}-{count:05d}"
