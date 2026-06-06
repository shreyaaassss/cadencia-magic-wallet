# context.md §10: marketplace API routes under /v1/marketplace/.
# Phase 3: all endpoints aligned with frontend TypeScript contracts.

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.identity.api.dependencies import get_current_buyer, get_current_seller, get_current_user
from src.identity.domain.user import User
from src.marketplace.api.schemas import (
    AddressResponse,
    CapabilityProfileResponse,
    CapabilityProfileUpdateRequest,
    CapabilityProfileUpdateResponse,
    CatalogueItemCreateRequest,
    CatalogueItemResponse,
    CatalogueItemUpdateRequest,
    ConfirmRFQRequest,
    ConfirmRFQResponse,
    EmbeddingRecomputeResponse,
    IncomingRFQResponse,
    MatchResponse,
    PincodeGeocodeResponse,
    RFQEditRequest,
    RFQResponse,
    RFQSubmitResponse,
    SellerCapacityProfileRequest,
    SellerCapacityProfileResponse,
    UploadRFQRequest,
)
from src.marketplace.application.commands import (
    ConfirmRFQCommand,
    UpdateCapabilityProfileCommand,
    UploadRFQCommand,
)
from src.marketplace.application.services import MarketplaceService
from src.marketplace.infrastructure.models import (
    AddressModel,
    CapabilityProfileModel,
    CatalogueItemModel,
    PincodeGeocodeModel,
    SellerCapacityProfileModel,
)
from src.marketplace.infrastructure.pgvector_matchmaker import (
    PgvectorMatchmaker,
)
from src.marketplace.infrastructure.repositories import (
    PostgresCapabilityProfileRepository,
    PostgresMatchRepository,
    PostgresRFQRepository,
)
from src.marketplace.infrastructure.rfq_parser import get_document_parser
from src.shared.api.responses import ApiResponse, success_response
from src.shared.infrastructure.db.session import get_db_session
from src.shared.infrastructure.events.publisher import get_publisher
from src.shared.infrastructure.logging import get_logger
from src.shared.middleware.x402_payment import require_x402_payment

log = get_logger(__name__)

router = APIRouter(prefix="/v1/marketplace", tags=["marketplace"])


async def _get_marketplace_service(
    session=Depends(get_db_session),
) -> MarketplaceService:
    """Build MarketplaceService with DI-injected infrastructure."""
    rfq_repo = PostgresRFQRepository(session)
    match_repo = PostgresMatchRepository(session)
    profile_repo = PostgresCapabilityProfileRepository(session)
    parser = get_document_parser()
    matchmaker = PgvectorMatchmaker(session)
    publisher = get_publisher()
    return MarketplaceService(
        rfq_repo=rfq_repo,
        match_repo=match_repo,
        profile_repo=profile_repo,
        document_parser=parser,
        matchmaking_engine=matchmaker,
        event_publisher=publisher,
    )


def _rfq_to_response(rfq) -> RFQResponse:
    """Convert RFQ domain entity to frontend-compatible RFQResponse."""
    return RFQResponse(
        id=rfq.id,
        raw_text=rfq.raw_document or "",
        status=rfq.status.value,
        parsed_fields=rfq.parsed_fields,
        created_at=rfq.created_at,
    )


# ── POST /v1/marketplace/rfq ────────────────────────────────────────────────


@router.post(
    "/rfq",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ApiResponse[RFQSubmitResponse],
    summary="Submit an RFQ (async NLP parsing)",
)
async def upload_rfq(
    body: UploadRFQRequest,
    current_user: User = Depends(get_current_buyer),
    svc: MarketplaceService = Depends(_get_marketplace_service),
    session: AsyncSession = Depends(get_db_session),
):
    rfq = await svc.upload_rfq(
        UploadRFQCommand(
            raw_text=body.raw_text,
            buyer_enterprise_id=current_user.enterprise_id,
            document_type=body.document_type,
        )
    )
    # Commit so background task (with its own session) can see the RFQ
    await session.commit()
    return success_response(
        RFQSubmitResponse(
            rfq_id=str(rfq.id),
            status="DRAFT",
            message="RFQ submitted for processing.",
        )
    )


# ── GET /v1/marketplace/rfqs ────────────────────────────────────────────────


@router.get(
    "/rfqs",
    response_model=ApiResponse[list[RFQResponse]],
    summary="List RFQs for the current enterprise",
)
async def list_rfqs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    current_user: User = Depends(get_current_buyer),
    svc: MarketplaceService = Depends(_get_marketplace_service),
):
    statuses = None
    if status_filter:
        statuses = [s.strip().upper() for s in status_filter.split(",")]

    rfqs = await svc.list_rfqs(
        buyer_enterprise_id=current_user.enterprise_id,
        limit=limit,
        offset=offset,
        statuses=statuses,
    )
    return success_response([_rfq_to_response(rfq) for rfq in rfqs])


# ── GET /v1/marketplace/rfq/{rfq_id} ────────────────────────────────────────


@router.get(
    "/rfq/{rfq_id}",
    response_model=ApiResponse[RFQResponse],
    summary="Get RFQ details + parsed fields",
)
async def get_rfq(
    rfq_id: uuid.UUID,
    current_user: User = Depends(get_current_buyer),
    svc: MarketplaceService = Depends(_get_marketplace_service),
):
    rfq = await svc.get_rfq(rfq_id)

    # Ownership check
    if str(rfq.buyer_enterprise_id) != str(current_user.enterprise_id):
        raise HTTPException(status_code=403, detail="Access denied")

    return success_response(_rfq_to_response(rfq))


# ── GET /v1/marketplace/rfq/{rfq_id}/matches ────────────────────────────────


@router.get(
    "/rfq/{rfq_id}/matches",
    response_model=ApiResponse[list[MatchResponse]],
    summary="Get ranked matches for RFQ",
)
async def get_rfq_matches(
    rfq_id: uuid.UUID,
    current_user: User = Depends(get_current_buyer),
    svc: MarketplaceService = Depends(_get_marketplace_service),
    session=Depends(get_db_session),
):
    rfq = await svc.get_rfq(rfq_id)

    # Ownership check
    if str(rfq.buyer_enterprise_id) != str(current_user.enterprise_id):
        raise HTTPException(status_code=403, detail="Access denied")

    # Status check — matches only available after matching completes
    if rfq.status.value not in ("MATCHED", "NEGOTIATING", "CONFIRMED"):
        raise HTTPException(
            status_code=400,
            detail=f"RFQ is in status '{rfq.status.value}'. "
                   "Matches are only available when status is 'MATCHED', 'NEGOTIATING', or 'CONFIRMED'.",
        )

    # Use the detailed query that joins Enterprise + CapabilityProfile
    match_repo = PostgresMatchRepository(session)
    match_details = await match_repo.get_matches_with_details(rfq_id)

    return success_response(
        [MatchResponse(**md) for md in match_details]
    )


# ── PUT /v1/marketplace/rfq/{rfq_id} — Edit RFQ ─────────────────────────────


@router.put(
    "/rfq/{rfq_id}",
    response_model=ApiResponse[dict],
    summary="Edit an RFQ (DRAFT, PARSED, or PARSE_FAILED only)",
)
async def edit_rfq(
    rfq_id: uuid.UUID,
    payload: RFQEditRequest,
    current_user: User = Depends(get_current_buyer),
    svc: MarketplaceService = Depends(_get_marketplace_service),
):
    import asyncio

    from src.marketplace.domain.value_objects import RFQStatus

    rfq = await svc.get_rfq(rfq_id)
    if rfq is None:
        raise HTTPException(status_code=404, detail="RFQ not found")
    if rfq.buyer_enterprise_id != current_user.enterprise_id:
        raise HTTPException(status_code=403, detail="Only the buyer can edit their RFQ")

    editable_statuses = {"DRAFT", "PARSED", "PARSE_FAILED"}
    if rfq.status.value not in editable_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"RFQ in '{rfq.status.value}' status cannot be edited. Only {editable_statuses} are editable.",
        )

    # Update raw text if provided
    if payload.raw_text is not None:
        rfq.raw_document = payload.raw_text

    # Apply manual field overrides
    if payload.parsed_overrides:
        existing_parsed = rfq.parsed_fields or {}
        existing_parsed.update(payload.parsed_overrides)
        rfq.parsed_fields = existing_parsed
        if rfq.status == RFQStatus.PARSE_FAILED:
            rfq.status = RFQStatus.PARSED
            rfq.parse_error = None

    # Reset to DRAFT if raw_document changed (needs re-parse)
    if payload.raw_text is not None:
        rfq.status = RFQStatus.DRAFT
        rfq.parse_error = None

    from src.marketplace.infrastructure.repositories import PostgresRFQRepository
    from src.shared.infrastructure.db.session import get_session_factory
    async with get_session_factory()() as db_session:
        rfq_repo = PostgresRFQRepository(db_session)
        await rfq_repo.update(rfq)
        await db_session.commit()

    # Re-trigger parsing if raw document changed
    if payload.raw_text is not None:
        asyncio.create_task(svc._parse_and_match_standalone(rfq_id))

    return success_response({
        "rfq_id": str(rfq.id),
        "status": rfq.status.value,
        "message": "RFQ updated" + (" — re-parsing triggered" if payload.raw_text else ""),
    })


# ── POST /v1/marketplace/rfq/{rfq_id}/start-negotiations ────────────────────


@router.post(
    "/rfq/{rfq_id}/start-negotiations",
    status_code=status.HTTP_200_OK,
    summary="Start AI negotiations with all matched sellers",
)
async def start_negotiations(
    rfq_id: uuid.UUID,
    current_user: User = Depends(get_current_buyer),
    svc: MarketplaceService = Depends(_get_marketplace_service),
    session: AsyncSession = Depends(get_db_session),
):
    from src.marketplace.application.commands import StartNegotiationsCommand
    rfq = await svc.get_rfq(rfq_id)
    if str(rfq.buyer_enterprise_id) != str(current_user.enterprise_id):
        raise HTTPException(status_code=403, detail="Access denied")
    if rfq.status.value != "MATCHED":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start negotiations — RFQ status is '{rfq.status.value}', expected 'MATCHED'.",
        )

    result = await svc.start_all_negotiations(
        StartNegotiationsCommand(
            rfq_id=rfq_id,
            buyer_enterprise_id=current_user.enterprise_id,
        )
    )
    await session.commit()
    return success_response(result)


# ── POST /v1/marketplace/rfq/{rfq_id}/confirm ───────────────────────────────


@router.post(
    "/rfq/{rfq_id}/confirm",
    response_model=ApiResponse[ConfirmRFQResponse],
    summary="Accept best deal from negotiations → confirm RFQ",
)
async def confirm_rfq(
    rfq_id: uuid.UUID,
    body: ConfirmRFQRequest,
    current_user: User = Depends(get_current_buyer),
    svc: MarketplaceService = Depends(_get_marketplace_service),
    session: AsyncSession = Depends(get_db_session),
):
    # Pre-validate RFQ status
    rfq = await svc.get_rfq(rfq_id)
    if str(rfq.buyer_enterprise_id) != str(current_user.enterprise_id):
        raise HTTPException(status_code=403, detail="Access denied")
    if rfq.status.value not in ("MATCHED", "NEGOTIATING"):
        raise HTTPException(
            status_code=400,
            detail=f"RFQ cannot be confirmed — current status is '{rfq.status.value}'. Must be 'MATCHED' or 'NEGOTIATING'.",
        )

    try:
        result = await svc.confirm_rfq(
            ConfirmRFQCommand(
                rfq_id=rfq_id,
                seller_enterprise_id=uuid.UUID(body.seller_enterprise_id),
                buyer_enterprise_id=current_user.enterprise_id,
            )
        )
    except Exception as exc:
        if "Match not found" in str(exc):
            raise HTTPException(
                status_code=404,
                detail="No match found for this seller and RFQ combination",
            )
        raise

    return success_response(
        ConfirmRFQResponse(
            message=result["message"],
            session_id=result["session_id"],
        )
    )


# ── GET /v1/marketplace/incoming-rfqs ────────────────────────────────────────


@router.get(
    "/incoming-rfqs",
    response_model=ApiResponse[list[IncomingRFQResponse]],
    summary="List incoming RFQs matched to this seller",
)
async def list_incoming_rfqs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_seller),
    svc: MarketplaceService = Depends(_get_marketplace_service),
):
    results = await svc.list_incoming_rfqs(
        seller_enterprise_id=current_user.enterprise_id,
        limit=limit,
        offset=offset,
    )
    return success_response([IncomingRFQResponse(**r) for r in results])


# ── GET /v1/marketplace/market-overview ────────────────────────────────────


@router.get(
    "/market-overview",
    response_model=ApiResponse[dict],
    summary="Anonymized market overview — industry/seller counts",
)
async def market_overview(
    current_user: User = Depends(get_current_user),
    session=Depends(get_db_session),
):
    """Return anonymized, aggregated market data for buyer orientation."""
    from sqlalchemy import and_, func

    from src.identity.infrastructure.models import EnterpriseModel

    # Count sellers by industry (industry_vertical is on CapabilityProfileModel)
    industry_stmt = (
        select(
            CapabilityProfileModel.industry_vertical,
            func.count(func.distinct(CapabilityProfileModel.enterprise_id)).label("seller_count"),
        )
        .where(CapabilityProfileModel.industry_vertical.isnot(None))
        .group_by(CapabilityProfileModel.industry_vertical)
        .order_by(func.count(func.distinct(CapabilityProfileModel.enterprise_id)).desc())
    )
    industry_result = await session.execute(industry_stmt)
    industries = [
        {"name": row[0], "seller_count": row[1]}
        for row in industry_result.all()
    ]

    # Count total active catalogue products
    product_count_stmt = select(func.count(CatalogueItemModel.id)).where(
        CatalogueItemModel.is_active == True  # noqa: E712
    )
    product_result = await session.execute(product_count_stmt)
    total_products = product_result.scalar() or 0

    # Count total sellers
    seller_count_stmt = select(func.count(EnterpriseModel.id)).where(
        EnterpriseModel.trade_role.in_(["SELLER", "BOTH"])
    )
    seller_result = await session.execute(seller_count_stmt)
    total_sellers = seller_result.scalar() or 0

    # Top product categories
    top_cats_stmt = (
        select(CatalogueItemModel.product_category, func.count().label("cnt"))
        .where(and_(CatalogueItemModel.is_active == True, CatalogueItemModel.product_category.isnot(None)))  # noqa: E712
        .group_by(CatalogueItemModel.product_category)
        .order_by(func.count().desc())
        .limit(10)
    )
    cat_result = await session.execute(top_cats_stmt)
    top_categories = [row[0] for row in cat_result.all() if row[0]]

    return success_response({
        "industries": industries,
        "total_sellers": total_sellers,
        "total_products": total_products,
        "top_categories": top_categories,
    })


# ── GET /v1/marketplace/capability-profile ───────────────────────────────────


@router.get(
    "/capability-profile",
    response_model=ApiResponse[CapabilityProfileResponse],
    summary="Get seller capability profile",
)
async def get_capability_profile(
    current_user: User = Depends(get_current_seller),
    svc: MarketplaceService = Depends(_get_marketplace_service),
    session=Depends(get_db_session),
):
    profile_repo = PostgresCapabilityProfileRepository(session)
    profile = await profile_repo.get_by_enterprise(current_user.enterprise_id)

    if not profile:
        # Return defaults — new sellers have no profile yet (NOT a 404)
        return success_response(CapabilityProfileResponse())

    # Derive embedding_status
    embedding_status = "outdated"
    if profile.embedding is not None:
        embedding_status = "active"

    return success_response(
        CapabilityProfileResponse(
            industry=profile.industry_vertical or "",
            geographies=profile.geography_scope or [],
            products=profile.product_categories or [],
            min_order_value=float(profile.trade_volume_min) if profile.trade_volume_min else 0.0,
            max_order_value=float(profile.trade_volume_max) if profile.trade_volume_max else 0.0,
            description=profile.profile_text or "",
            embedding_status=embedding_status,
            last_embedded=None,  # TODO: track last_embedded_at in profile model
        )
    )


# ── PUT /v1/marketplace/capability-profile ───────────────────────────────────


@router.put(
    "/capability-profile",
    response_model=ApiResponse[CapabilityProfileUpdateResponse],
    summary="Update seller capability profile",
)
async def update_capability_profile(
    body: CapabilityProfileUpdateRequest,
    current_user: User = Depends(get_current_seller),
    svc: MarketplaceService = Depends(_get_marketplace_service),
    session: AsyncSession = Depends(get_db_session),
):
    # Authorization: only sellers can update capability profile
    from src.identity.infrastructure.repositories import PostgresEnterpriseRepository
    enterprise_repo = PostgresEnterpriseRepository(session)
    enterprise = await enterprise_repo.get_by_id(current_user.enterprise_id)
    if enterprise and str(enterprise.trade_role.value) not in ("SELLER", "BOTH"):
        raise HTTPException(
            status_code=403,
            detail="Only enterprises with trade role SELLER or BOTH can maintain a capability profile",
        )

    await svc.update_capability_profile(
        UpdateCapabilityProfileCommand(
            enterprise_id=current_user.enterprise_id,
            industry_vertical=body.industry,
            product_categories=body.products,
            geography_scope=body.geographies,
            trade_volume_min=body.min_order_value if body.min_order_value else None,
            trade_volume_max=body.max_order_value if body.max_order_value else None,
            profile_text=body.description,
        )
    )
    # Commit so background embedding task (with its own session) can see the profile
    await session.commit()
    return success_response(
        CapabilityProfileUpdateResponse(
            message="Seller profile updated successfully",
            embedding_status="queued",
        )
    )


# ── POST /v1/marketplace/capability-profile/embeddings ──────────────────────


@router.post(
    "/capability-profile/embeddings",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ApiResponse[EmbeddingRecomputeResponse],
    summary="Trigger background embedding recompute",
)
async def recompute_embeddings(
    current_user: User = Depends(get_current_seller),
    svc: MarketplaceService = Depends(_get_marketplace_service),
    session=Depends(get_db_session),
):
    # Verify profile exists
    profile_repo = PostgresCapabilityProfileRepository(session)
    profile = await profile_repo.get_by_enterprise(current_user.enterprise_id)
    if not profile:
        raise HTTPException(
            status_code=400,
            detail="No capability profile found. Please create a profile before triggering embedding.",
        )

    await svc._recompute_embedding_standalone(current_user.enterprise_id)
    return success_response(
        EmbeddingRecomputeResponse(
            message="Embeddings recomputation queued. Profile will be active for matching in ~30 seconds."
        )
    )


# ── Enhanced Onboarding Endpoints ────────────────────────────────────────────


def _catalogue_to_response(item: CatalogueItemModel) -> CatalogueItemResponse:
    return CatalogueItemResponse(
        id=item.id,
        product_name=item.product_name,
        hsn_code=item.hsn_code,
        product_category=item.product_category,
        grade=item.grade,
        specification_text=item.specification_text,
        unit=item.unit,
        price_per_unit_inr=float(item.price_per_unit_inr),
        bulk_pricing_tiers=item.bulk_pricing_tiers,
        moq=float(item.moq),
        max_order_qty=float(item.max_order_qty),
        lead_time_days=item.lead_time_days,
        in_stock_qty=float(item.in_stock_qty) if item.in_stock_qty else 0,
        is_active=item.is_active,
        certifications=item.certifications or [],
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


# ── POST /v1/marketplace/catalogue ──────────────────────────────────────────


@router.post(
    "/catalogue",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiResponse[CatalogueItemResponse],
    summary="Add a product to the seller catalogue",
)
async def create_catalogue_item(
    body: CatalogueItemCreateRequest,
    current_user: User = Depends(get_current_seller),
    session: AsyncSession = Depends(get_db_session),
):
    import uuid as _uuid

    item = CatalogueItemModel(
        id=_uuid.uuid4(),
        enterprise_id=current_user.enterprise_id,
        product_name=body.product_name,
        hsn_code=body.hsn_code,
        product_category=body.product_category,
        grade=body.grade,
        specification_text=body.specification_text,
        unit=body.unit,
        price_per_unit_inr=body.price_per_unit_inr,
        bulk_pricing_tiers=body.bulk_pricing_tiers,
        moq=body.moq,
        max_order_qty=body.max_order_qty,
        lead_time_days=body.lead_time_days,
        in_stock_qty=body.in_stock_qty,
        certifications=body.certifications or [],
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    # Fix 6: new item added → regenerate seller embedding to include it
    import asyncio as _asyncio
    _svc = await _get_marketplace_service(session)
    _asyncio.create_task(_svc._recompute_embedding_standalone(current_user.enterprise_id))
    return success_response(_catalogue_to_response(item))


# ── GET /v1/marketplace/catalogue ───────────────────────────────────────────


@router.get(
    "/catalogue",
    response_model=ApiResponse[list[CatalogueItemResponse]],
    summary="List seller's catalogue items",
)
async def list_catalogue_items(
    active_only: bool = Query(default=True),
    current_user: User = Depends(get_current_seller),
    session: AsyncSession = Depends(get_db_session),
):
    stmt = select(CatalogueItemModel).where(
        CatalogueItemModel.enterprise_id == current_user.enterprise_id,
    )
    if active_only:
        stmt = stmt.where(CatalogueItemModel.is_active == True)  # noqa: E712
    stmt = stmt.order_by(CatalogueItemModel.product_name)
    result = await session.execute(stmt)
    items = result.scalars().all()
    return success_response([_catalogue_to_response(i) for i in items])


# ── GET /v1/marketplace/catalogue/{item_id} ─────────────────────────────────


@router.get(
    "/catalogue/{item_id}",
    response_model=ApiResponse[CatalogueItemResponse],
    summary="Get single catalogue item",
)
async def get_catalogue_item(
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_seller),
    session: AsyncSession = Depends(get_db_session),
):
    stmt = select(CatalogueItemModel).where(
        CatalogueItemModel.id == item_id,
        CatalogueItemModel.enterprise_id == current_user.enterprise_id,
    )
    result = await session.execute(stmt)
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Catalogue item not found")
    return success_response(_catalogue_to_response(item))


# ── PUT /v1/marketplace/catalogue/{item_id} ─────────────────────────────────


@router.put(
    "/catalogue/{item_id}",
    response_model=ApiResponse[CatalogueItemResponse],
    summary="Update a catalogue item",
)
async def update_catalogue_item(
    item_id: uuid.UUID,
    body: CatalogueItemUpdateRequest,
    current_user: User = Depends(get_current_seller),
    session: AsyncSession = Depends(get_db_session),
):
    stmt = select(CatalogueItemModel).where(
        CatalogueItemModel.id == item_id,
        CatalogueItemModel.enterprise_id == current_user.enterprise_id,
    )
    result = await session.execute(stmt)
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Catalogue item not found")

    update_data = body.model_dump(exclude_unset=True)

    # Write change log entries for auditing
    import uuid as _uuid

    from src.marketplace.infrastructure.models import CatalogueChangeLogModel
    for field_name, new_value in update_data.items():
        old_value = getattr(item, field_name, None)
        if str(old_value) != str(new_value):
            session.add(CatalogueChangeLogModel(
                id=_uuid.uuid4(),
                catalogue_item_id=item.id,
                field_name=field_name,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(new_value) if new_value is not None else None,
                changed_by=getattr(current_user, "id", None),
            ))

    # Track price changes specifically
    if "price_per_unit_inr" in update_data:
        from datetime import datetime, timezone
        item.price_updated_at = datetime.now(timezone.utc)

    for field_name, value in update_data.items():
        setattr(item, field_name, value)

    # Increment version
    item.version = (item.version or 1) + 1

    await session.commit()
    await session.refresh(item)
    # Fix 6: item changed (price/name/spec) → regenerate seller embedding
    import asyncio as _asyncio
    _svc = await _get_marketplace_service(session)
    _asyncio.create_task(_svc._recompute_embedding_standalone(current_user.enterprise_id))
    return success_response(_catalogue_to_response(item))


# ── DELETE /v1/marketplace/catalogue/{item_id} ──────────────────────────────


@router.delete(
    "/catalogue/{item_id}",
    response_model=ApiResponse[dict],
    summary="Deactivate a catalogue item (soft delete)",
)
async def deactivate_catalogue_item(
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_seller),
    session: AsyncSession = Depends(get_db_session),
):
    stmt = select(CatalogueItemModel).where(
        CatalogueItemModel.id == item_id,
        CatalogueItemModel.enterprise_id == current_user.enterprise_id,
    )
    result = await session.execute(stmt)
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Catalogue item not found")

    item.is_active = False
    await session.commit()
    # Fix 6: item deactivated → regenerate seller embedding to remove it from vector
    import asyncio as _asyncio
    _svc = await _get_marketplace_service(session)
    _asyncio.create_task(_svc._recompute_embedding_standalone(current_user.enterprise_id))
    return success_response({"message": "Catalogue item deactivated"})


# ── POST /v1/marketplace/catalogue/bulk ─────────────────────────────────────


@router.post(
    "/catalogue/bulk",
    status_code=201,
    summary="Bulk import catalogue items (single transaction, one embedding recompute)",
)
async def bulk_create_catalogue_items(
    body: dict,
    current_user: User = Depends(get_current_seller),
    session: AsyncSession = Depends(get_db_session),
):
    """
    POST /v1/marketplace/catalogue/bulk — batch import catalogue items.

    Accepts {"items": [...]} where each item has the same shape as the
    single-item create request. All items are inserted in one transaction.
    If any item is invalid, the entire batch is rolled back.
    Triggers exactly ONE embedding recompute (not N).
    """
    from pydantic import ValidationError as PydanticValidationError

    from src.marketplace.api.schemas import CatalogueItemCreateRequest

    items_raw = body.get("items", [])
    if not items_raw or not isinstance(items_raw, list):
        raise HTTPException(status_code=422, detail="Request body must have 'items' array")
    if len(items_raw) > 200:
        raise HTTPException(status_code=422, detail="Maximum 200 items per bulk request")

    # Validate all items first (fail fast before any DB writes)
    validated: list[dict] = []
    for idx, item_data in enumerate(items_raw):
        try:
            parsed = CatalogueItemCreateRequest(**item_data)
            validated.append(parsed.model_dump())
        except (PydanticValidationError, Exception) as e:
            raise HTTPException(
                status_code=422,
                detail=f"Item {idx} invalid: {e}",
            )

    import uuid as _uuid

    created_ids = []
    for item_dict in validated:
        item_dict.pop("validity_end_date", None)  # handled separately if needed
        model = CatalogueItemModel(
            id=_uuid.uuid4(),
            enterprise_id=current_user.enterprise_id,
            **item_dict,
        )
        session.add(model)
        created_ids.append(str(model.id))

    await session.commit()

    # Single embedding recompute for the entire batch
    import asyncio as _asyncio
    _svc = await _get_marketplace_service(session)
    _asyncio.create_task(_svc._recompute_embedding_standalone(current_user.enterprise_id))

    return success_response(data={
        "created": len(created_ids),
        "item_ids": created_ids,
        "embedding_status": "COMPUTING",
    })


# ── PUT /v1/marketplace/capacity-profile ────────────────────────────────────


@router.put(
    "/capacity-profile",
    response_model=ApiResponse[SellerCapacityProfileResponse],
    summary="Create or update seller capacity profile",
)
async def upsert_capacity_profile(
    body: SellerCapacityProfileRequest,
    current_user: User = Depends(get_current_seller),
    session: AsyncSession = Depends(get_db_session),
):
    import uuid as _uuid

    stmt = select(SellerCapacityProfileModel).where(
        SellerCapacityProfileModel.enterprise_id == current_user.enterprise_id,
    )
    result = await session.execute(stmt)
    profile = result.scalar_one_or_none()

    available = body.monthly_production_capacity_mt * (1 - body.current_utilization_pct / 100)

    if profile:
        for field_name, value in body.model_dump().items():
            setattr(profile, field_name, value)
        profile.available_capacity_mt = available
    else:
        profile = SellerCapacityProfileModel(
            id=_uuid.uuid4(),
            enterprise_id=current_user.enterprise_id,
            available_capacity_mt=available,
            **body.model_dump(),
        )
        session.add(profile)

    await session.commit()
    await session.refresh(profile)
    return success_response(
        SellerCapacityProfileResponse(
            id=profile.id,
            enterprise_id=profile.enterprise_id,
            monthly_production_capacity_mt=float(profile.monthly_production_capacity_mt),
            capacity_unit=getattr(profile, "capacity_unit", "MT") or "MT",
            current_utilization_pct=profile.current_utilization_pct or 0,
            available_capacity_mt=float(profile.available_capacity_mt) if profile.available_capacity_mt else None,
            num_production_lines=profile.num_production_lines or 1,
            shift_pattern=profile.shift_pattern,
            avg_dispatch_days=profile.avg_dispatch_days,
            max_delivery_radius_km=profile.max_delivery_radius_km,
            has_own_transport=profile.has_own_transport,
            preferred_transport_modes=profile.preferred_transport_modes or [],
            ex_works_available=profile.ex_works_available,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )
    )


# ── GET /v1/marketplace/capacity-profile ────────────────────────────────────


@router.get(
    "/capacity-profile",
    response_model=ApiResponse[SellerCapacityProfileResponse],
    summary="Get seller capacity profile",
)
async def get_capacity_profile(
    current_user: User = Depends(get_current_seller),
    session: AsyncSession = Depends(get_db_session),
):
    stmt = select(SellerCapacityProfileModel).where(
        SellerCapacityProfileModel.enterprise_id == current_user.enterprise_id,
    )
    result = await session.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise HTTPException(status_code=404, detail="No capacity profile found. Create one first.")

    return success_response(
        SellerCapacityProfileResponse(
            id=profile.id,
            enterprise_id=profile.enterprise_id,
            monthly_production_capacity_mt=float(profile.monthly_production_capacity_mt),
            capacity_unit=getattr(profile, "capacity_unit", "MT") or "MT",
            current_utilization_pct=profile.current_utilization_pct or 0,
            available_capacity_mt=float(profile.available_capacity_mt) if profile.available_capacity_mt else None,
            num_production_lines=profile.num_production_lines or 1,
            shift_pattern=profile.shift_pattern,
            avg_dispatch_days=profile.avg_dispatch_days,
            max_delivery_radius_km=profile.max_delivery_radius_km,
            has_own_transport=profile.has_own_transport,
            preferred_transport_modes=profile.preferred_transport_modes or [],
            ex_works_available=profile.ex_works_available,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )
    )


# ── GET /v1/marketplace/addresses ───────────────────────────────────────────


@router.get(
    "/addresses",
    response_model=ApiResponse[list[AddressResponse]],
    summary="List addresses for current enterprise",
)
async def list_addresses(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    stmt = select(AddressModel).where(
        AddressModel.enterprise_id == current_user.enterprise_id,
    ).order_by(AddressModel.is_primary.desc())
    result = await session.execute(stmt)
    addresses = result.scalars().all()
    return success_response([
        AddressResponse(
            id=a.id,
            address_type=a.address_type,
            address_line1=a.address_line1,
            address_line2=a.address_line2,
            city=a.city,
            state=a.state,
            pincode=a.pincode,
            latitude=a.latitude,
            longitude=a.longitude,
            is_primary=a.is_primary,
        )
        for a in addresses
    ])


# ── GET /v1/marketplace/pincode/{pincode} ───────────────────────────────────


@router.get(
    "/pincode/{pincode}",
    response_model=ApiResponse[PincodeGeocodeResponse],
    summary="Lookup pincode geocode (public)",
)
async def lookup_pincode(
    pincode: str,
    session: AsyncSession = Depends(get_db_session),
):
    stmt = select(PincodeGeocodeModel).where(PincodeGeocodeModel.pincode == pincode)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail=f"Pincode {pincode} not found")
    return success_response(
        PincodeGeocodeResponse(
            pincode=row.pincode,
            city=row.city,
            state=row.state,
            latitude=row.latitude,
            longitude=row.longitude,
        )
    )


# ── x402-gated premium endpoints ─────────────────────────────────────────────
# These endpoints require an Algorand micropayment via the x402 protocol.
# Clients that call without payment receive HTTP 402 with payment requirements.
# The require_x402_payment dependency handles validation + on-chain confirmation.


@router.get(
    "/loans/{loan_id}/analytics",
    response_model=ApiResponse[dict],
    summary="[x402] Detailed loan analytics — requires micropayment",
    dependencies=[Depends(require_x402_payment)],
)
async def get_loan_analytics(
    loan_id: uuid.UUID,
    current_user: User = Depends(get_current_buyer),
) -> dict:
    """
    Returns detailed analytics for a loan/RFQ deal.

    Protected by x402 Algorand payment (0.1 ALGO per call).
    Stub: returns placeholder analytics structure.
    Full implementation: query RFQ + negotiation + escrow tables for the deal.
    """
    return success_response(
        {
            "loan_id": str(loan_id),
            "analytics": {
                "deal_value_inr": None,
                "negotiation_rounds": None,
                "price_convergence_pct": None,
                "escrow_status": None,
                "note": "Analytics data will be populated in future implementation",
            },
        }
    )


@router.get(
    "/loans/{loan_id}/credit-report",
    response_model=ApiResponse[dict],
    summary="[x402] Borrower credit report — requires micropayment",
    dependencies=[Depends(require_x402_payment)],
)
async def get_loan_credit_report(
    loan_id: uuid.UUID,
    current_user: User = Depends(get_current_buyer),
) -> dict:
    """
    Returns the credit report for the seller/borrower in a loan deal.

    Protected by x402 Algorand payment (0.1 ALGO per call).
    Stub: returns placeholder credit report structure.
    Full implementation: integrate with KYC/credit provider (Karza, Digilocker).
    """
    return success_response(
        {
            "loan_id": str(loan_id),
            "credit_report": {
                "gstin_verified": None,
                "credit_score": None,
                "kyc_status": None,
                "trade_history_summary": None,
                "note": "Credit report will be populated in future implementation",
            },
        }
    )


@router.post(
    "/match",
    response_model=ApiResponse[dict],
    summary="[x402] AI-powered loan matching — requires micropayment",
    dependencies=[Depends(require_x402_payment)],
)
async def premium_match(
    body: dict,
    current_user: User = Depends(get_current_buyer),
) -> dict:
    """
    Runs AI-powered premium matching against the full seller catalogue.

    Protected by x402 Algorand payment (0.1 ALGO per call).
    Stub: returns placeholder match result structure.
    Full implementation: run PgvectorMatchmaker with extended scoring.
    """
    return success_response(
        {
            "matches": [],
            "note": "Premium matching will be populated in future implementation",
        }
    )


# ── Industry Taxonomy ──────────────────────────────────────────────────────────


@router.get(
    "/industries",
    summary="List industry taxonomies",
)
async def list_industries(
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    GET /v1/marketplace/industries — list all industry taxonomies.

    Returns default units, certifications, capacity unit, and manufacturing
    flag for each industry so the frontend can render conditional forms.
    """
    from sqlalchemy import select as _sa_select

    from src.marketplace.infrastructure.models import IndustryTaxonomyModel

    result = await session.execute(
        _sa_select(IndustryTaxonomyModel).order_by(IndustryTaxonomyModel.display_name)
    )
    rows = result.scalars().all()
    return success_response(data=[
        {
            "id": str(row.id),
            "industry_code": row.industry_code,
            "display_name": row.display_name,
            "parent_code": row.parent_code,
            "default_units": row.default_units,
            "default_certifications": row.default_certifications,
            "capacity_unit": row.capacity_unit,
            "is_manufacturing": row.is_manufacturing,
        }
        for row in rows
    ])


# ── Background Task Status ──────────────────────────────────────────────────


@router.get(
    "/task-status/embedding",
    summary="Check embedding recompute status for current seller",
)
async def get_embedding_task_status(
    current_user: User = Depends(get_current_seller),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    GET /v1/marketplace/task-status/embedding — poll embedding status.

    Returns the current embedding_status, embedding_version, and last_embedded_at
    so the frontend can show progress/retry UI.
    """
    from src.marketplace.infrastructure.models import CapabilityProfileModel

    result = await session.execute(
        select(CapabilityProfileModel).where(
            CapabilityProfileModel.enterprise_id == current_user.enterprise_id
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        return success_response(data={"status": "NO_PROFILE"})

    return success_response(data={
        "embedding_status": getattr(profile, "embedding_status", "UNKNOWN"),
        "embedding_version": getattr(profile, "embedding_version", 0),
        "last_embedded_at": (
            profile.last_embedded_at.isoformat() if getattr(profile, "last_embedded_at", None) else None
        ),
        "has_embedding": profile.embedding is not None,
    })


# ── Platform Statistics (Public) ─────────────────────────────────────────────


@router.get(
    "/stats",
    summary="Platform statistics (public, no auth)",
)
async def get_platform_stats(
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    GET /v1/marketplace/stats — aggregate platform statistics.

    Public endpoint (no auth) for marketplace credibility and demo impact.
    """
    from sqlalchemy import func as sa_func

    from src.identity.infrastructure.models import EnterpriseModel

    seller_count = await session.execute(
        select(sa_func.count()).where(EnterpriseModel.trade_role.in_(["SELLER", "BOTH"]))
    )

    # Industries represented
    from src.marketplace.infrastructure.models import CapabilityProfileModel
    industries_result = await session.execute(
        select(sa_func.array_agg(sa_func.distinct(CapabilityProfileModel.industry_vertical)))
        .where(CapabilityProfileModel.industry_vertical != None)  # noqa: E711
    )
    industries = industries_result.scalar() or []

    # Only expose seller count + industries — no buyer count or deal data
    return success_response(data={
        "total_sellers": seller_count.scalar() or 0,
        "industries_represented": [i for i in industries if i],
    })


# ── Anonymized Supplier Directory (Public) ───────────────────────────────────


@router.get(
    "/suppliers",
    summary="Anonymized supplier directory (public, no auth)",
)
async def list_suppliers(
    industry: str | None = Query(None, description="Filter by industry vertical"),
    state: str | None = Query(None, description="Filter by geography/state"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    GET /v1/marketplace/suppliers — anonymized seller profiles.

    Returns seller capability profiles without revealing enterprise identity.
    Sellers are identified by opaque tokens (not enterprise_id).
    """
    import hashlib

    from src.identity.infrastructure.models import EnterpriseModel
    from src.marketplace.infrastructure.models import CapabilityProfileModel

    stmt = (
        select(CapabilityProfileModel, EnterpriseModel)
        .join(EnterpriseModel, CapabilityProfileModel.enterprise_id == EnterpriseModel.id)
        .where(EnterpriseModel.trade_role.in_(["SELLER", "BOTH"]))
    )
    if industry:
        stmt = stmt.where(CapabilityProfileModel.industry_vertical.ilike(f"%{industry}%"))
    if state:
        stmt = stmt.where(CapabilityProfileModel.geographies_served.any(state))

    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(stmt)
    rows = result.all()

    suppliers = []
    for profile, enterprise in rows:
        # Opaque token — not reversible to enterprise_id
        opaque_id = hashlib.sha256(str(profile.enterprise_id).encode()).hexdigest()[:16]
        suppliers.append({
            "supplier_id": opaque_id,
            "industry": profile.industry_vertical,
            "categories": profile.commodities or [],
            "geographies": profile.geographies_served or [],
            "certifications": enterprise.quality_certifications or [],
            "years_in_operation_bucket": (
                "< 1" if (enterprise.years_in_operation or 0) < 1
                else "1-3" if (enterprise.years_in_operation or 0) < 4
                else "3-5" if (enterprise.years_in_operation or 0) < 6
                else "5-10" if (enterprise.years_in_operation or 0) < 11
                else "10+"
            ),
            # min_order_value_inr removed — pricing should not be exposed publicly
        })

    return success_response(data=suppliers)
