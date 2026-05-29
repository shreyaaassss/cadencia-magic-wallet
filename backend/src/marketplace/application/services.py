# context.md §3: Application service — orchestrates use cases.
# All infrastructure deps injected via constructor (DIP).

from __future__ import annotations

import asyncio
import json
import uuid
from typing import TYPE_CHECKING

from src.marketplace.application.commands import (
    ConfirmRFQCommand,
    StartNegotiationsCommand,
    UpdateCapabilityProfileCommand,
    UploadRFQCommand,
)
from src.marketplace.domain.capability_profile import CapabilityProfile
from src.marketplace.domain.events import (
    CapabilityProfileUpdated,
    RFQConfirmed,
    RFQMatched,
    RFQParsed,
    RFQUploaded,
)
from src.marketplace.domain.match import Match
from src.marketplace.domain.rfq import RFQ
from src.marketplace.domain.value_objects import SimilarityScore
from src.shared.domain.exceptions import AuthorizationError, NotFoundError
from src.shared.infrastructure.logging import get_logger
from src.shared.infrastructure.metrics import RFQ_UPLOADS_TOTAL

if TYPE_CHECKING:
    from src.marketplace.domain.ports import (
        ICapabilityProfileRepository,
        IDocumentParser,
        IMatchmakingEngine,
        IMatchRepository,
        IRFQRepository,
    )
    from src.shared.infrastructure.events.publisher import EventPublisher

log = get_logger(__name__)

# Fix 6: module-level debounce lock — prevents parallel embedding recomputes
# for the same enterprise (e.g. seller bulk-uploading 20 catalogue items at once).
_EMBEDDING_RECOMPUTE_LOCK: dict[str, bool] = {}


class MarketplaceService:
    """Orchestrates marketplace use cases."""

    def __init__(
        self,
        rfq_repo: IRFQRepository,
        match_repo: IMatchRepository,
        profile_repo: ICapabilityProfileRepository,
        document_parser: IDocumentParser,
        matchmaking_engine: IMatchmakingEngine,
        event_publisher: EventPublisher,
        top_n_matches: int = 10,
    ) -> None:
        self._rfq_repo = rfq_repo
        self._match_repo = match_repo
        self._profile_repo = profile_repo
        self._parser = document_parser
        self._matchmaker = matchmaking_engine
        self._publisher = event_publisher
        self._top_n = top_n_matches

    async def upload_rfq(self, cmd: UploadRFQCommand) -> RFQ:
        """Create RFQ in DRAFT, schedule background parse+match. Returns immediately."""
        rfq = RFQ(
            buyer_enterprise_id=cmd.buyer_enterprise_id,
            raw_document=cmd.raw_text,
        )
        await self._rfq_repo.save(rfq)

        await self._publisher.publish(
            RFQUploaded(
                aggregate_id=rfq.id,
                event_type="RFQUploaded",
                rfq_id=rfq.id,
                buyer_enterprise_id=rfq.buyer_enterprise_id,
                raw_document_length=len(cmd.raw_text),
            )
        )

        # Background parse & match — non-blocking (uses its own DB session)
        asyncio.create_task(self._parse_and_match_standalone(rfq.id))

        # Prometheus: RFQ upload success
        RFQ_UPLOADS_TOTAL.labels(status="success").inc()

        log.info("rfq_uploaded", rfq_id=str(rfq.id), status=rfq.status.value)
        return rfq

    async def _parse_and_match_standalone(self, rfq_id: uuid.UUID) -> None:
        """Background task with its own DB session — avoids asyncpg concurrency errors."""
        import os
        from src.marketplace.infrastructure.pgvector_matchmaker import PgvectorMatchmaker, StubMatchmakingEngine
        from src.marketplace.infrastructure.keyword_matchmaker import KeywordMatchmaker
        from src.marketplace.infrastructure.repositories import (
            PostgresCapabilityProfileRepository,
            PostgresMatchRepository,
            PostgresRFQRepository,
        )
        from src.shared.infrastructure.db.session import get_session_factory

        # Wait for the parent request's transaction to commit before we read.
        # Retry with backoff if the row isn't visible yet (transaction isolation).
        await asyncio.sleep(0.3)

        factory = get_session_factory()
        async with factory() as session:
            try:
                rfq_repo = PostgresRFQRepository(session)
                match_repo = PostgresMatchRepository(session)
                llm_provider = os.environ.get("LLM_PROVIDER", "stub")
                if llm_provider == "stub":
                    matchmaker = StubMatchmakingEngine(session=session)
                else:
                    matchmaker = PgvectorMatchmaker(session)

                rfq = await rfq_repo.get_by_id(rfq_id)
                if rfq is None:
                    # Retry: parent transaction may not have committed yet
                    for _attempt in range(3):
                        await asyncio.sleep(0.5)
                        rfq = await rfq_repo.get_by_id(rfq_id)
                        if rfq is not None:
                            break
                if rfq is None:
                    log.error("rfq_not_found_for_parse", rfq_id=str(rfq_id))
                    return

                # 1. Extract fields via LLM (with fallback to stub parser)
                try:
                    parsed = await self._parser.extract_rfq_fields(rfq.raw_document or "")
                except Exception as parse_exc:
                    log.warning("rfq_llm_extraction_failed_using_fallback", rfq_id=str(rfq_id), error=str(parse_exc))
                    from src.marketplace.infrastructure.rfq_parser import StubDocumentParser
                    fallback = StubDocumentParser()
                    parsed = await fallback.extract_rfq_fields(rfq.raw_document or "")
                if not parsed:
                    log.warning("rfq_extraction_empty", rfq_id=str(rfq_id))
                    return  # Stay DRAFT — no fields extracted

                from src.marketplace.infrastructure.rfq_parser import (
                    build_parsed_variants,
                    normalize_rfq_parsed_fields,
                )
                parsed = normalize_rfq_parsed_fields(parsed)

                # 2. Mark parsed
                event_data = rfq.mark_parsed(parsed)
                await rfq_repo.update(rfq)
                await session.commit()

                await self._publisher.publish(
                    RFQParsed(
                        aggregate_id=rfq.id,
                        event_type="RFQParsed",
                        **event_data,
                    )
                )

                # 3. Generate embedding
                embed_text = (rfq.raw_document or "") + " " + json.dumps(parsed)
                embedding = await self._parser.generate_embedding(embed_text)
                rfq.embedding = embedding

                # 4. Find matches — loop variants for multi-product RFQs
                import re as _re
                from sqlalchemy import select as sa_select  # noqa: E402 — must be before address query
                from src.marketplace.infrastructure.models import AddressModel, MatchModel

                parsed_variants = build_parsed_variants(parsed)
                merged_raw_scores: dict = {}
                merged_enhanced_by_seller: dict = {}

                buyer_pincode = None
                addr_result = await session.execute(
                    sa_select(AddressModel).where(
                        AddressModel.enterprise_id == rfq.buyer_enterprise_id,
                        AddressModel.is_primary == True,  # noqa: E712
                    )
                )
                buyer_addr = addr_result.scalar_one_or_none()
                if buyer_addr:
                    buyer_pincode = buyer_addr.pincode

                # Track which variant produced the best score per seller (for single-product logic)
                best_variant_by_seller: dict = {}

                # Per-product top matches: { product_name → [(seller_id, score), ...] }
                # Used to create per-product sessions for multi-product RFQs
                per_product_matches: dict = {}   # product → [(eid, score)]
                per_product_variant: dict = {}   # product → parsed_variant dict

                for variant in parsed_variants:
                    rfq.parsed_fields = variant
                    has_delivery_data = bool(
                        variant.get("delivery_window_days")
                        or variant.get("quantity")
                        or variant.get("budget_min")
                    )
                    buyer_delivery_window = variant.get("delivery_window_days")
                    buyer_qty_raw = variant.get("quantity")
                    buyer_qty = None
                    if buyer_qty_raw is not None:
                        qty_match = _re.search(r"[\d.]+", str(buyer_qty_raw))
                        if qty_match:
                            try:
                                buyer_qty = float(qty_match.group())
                            except ValueError:
                                buyer_qty = None
                    buyer_budget_min = variant.get("budget_min")
                    buyer_budget_max = variant.get("budget_max")
                    product_category = variant.get("product_category")

                    if has_delivery_data and hasattr(matchmaker, "find_enhanced_matches"):
                        enhanced_results = await matchmaker.find_enhanced_matches(
                            rfq=rfq,
                            rfq_embedding=embedding,
                            buyer_pincode=buyer_pincode,
                            buyer_delivery_window=int(buyer_delivery_window) if buyer_delivery_window else None,
                            buyer_qty=float(buyer_qty) if buyer_qty else None,
                            buyer_budget_min=float(buyer_budget_min) if buyer_budget_min else None,
                            buyer_budget_max=float(buyer_budget_max) if buyer_budget_max else None,
                            product_category=product_category,
                            top_n=self._top_n,
                        )
                        if enhanced_results:
                            prod_key = variant.get("product", "unknown")
                            per_product_variant[prod_key] = variant
                            if prod_key not in per_product_matches:
                                per_product_matches[prod_key] = []
                            for m_data in enhanced_results:
                                eid = m_data["enterprise_id"]
                                prev = merged_enhanced_by_seller.get(eid)
                                if not prev or m_data["composite_score"] > prev["composite_score"]:
                                    merged_enhanced_by_seller[eid] = m_data
                                    best_variant_by_seller[eid] = variant  # Track which product
                                per_product_matches[prod_key].append((eid, m_data["composite_score"]))
                        else:
                            _kw = KeywordMatchmaker(session)
                            _kw_results = await _kw.find_matches(rfq, embedding, self._top_n)
                            prod_key_kw = variant.get("product", "unknown")
                            per_product_variant[prod_key_kw] = variant
                            if prod_key_kw not in per_product_matches:
                                per_product_matches[prod_key_kw] = []
                            for eid, sc in _kw_results:
                                if eid not in merged_raw_scores or sc > merged_raw_scores[eid]:
                                    merged_raw_scores[eid] = sc
                                    best_variant_by_seller[eid] = variant  # Track which product
                                per_product_matches[prod_key_kw].append((eid, sc))
                    else:
                        variant_raw = await matchmaker.find_matches(
                            rfq, embedding, self._top_n
                        )
                        if not variant_raw or all(s < 0.3 for _, s in variant_raw):
                            keyword_matchmaker = KeywordMatchmaker(session)
                            variant_raw = await keyword_matchmaker.find_matches(
                                rfq, embedding, self._top_n
                            )
                        for eid, sc in variant_raw:
                            if eid not in merged_raw_scores or sc > merged_raw_scores[eid]:
                                merged_raw_scores[eid] = sc
                                best_variant_by_seller[eid] = variant  # Track which product
                        # Track per-product top sellers
                        prod_key = variant.get("product", "unknown")
                        per_product_variant[prod_key] = variant
                        if prod_key not in per_product_matches:
                            per_product_matches[prod_key] = []
                        for eid, sc in variant_raw:
                            per_product_matches[prod_key].append((eid, sc))

                rfq.parsed_fields = parsed
                # Persist all product names for multi-product RFQs
                all_prods = list({v.get("product") for v in parsed_variants if v.get("product")})
                is_multi_product = len(all_prods) > 1
                if is_multi_product:
                    rfq.all_products = all_prods

                # ── Multi-product: create per-product matches ─────────────────
                # For a 3-product RFQ (camera + tripod + lens), build a flat
                # list of (seller, product_variant) pairs — best seller per product.
                # Each pair becomes its own Match so sessions can negotiate the
                # correct product/budget independently.
                # Single-product RFQs fall through to the original global top-N path.
                if is_multi_product and per_product_matches:
                    # Collect top-3 sellers per product, deduplicate bundle sellers
                    multi_matches: list = []
                    seen_seller_products: set = set()  # (eid, product) dedup
                    rank_counter = 0
                    for prod_key, prod_scores in per_product_matches.items():
                        variant = per_product_variant.get(prod_key, {})
                        # Sort by score descending, take top 3 per product
                        top_sellers = sorted(prod_scores, key=lambda x: x[1], reverse=True)[:3]
                        for eid, sc in top_sellers:
                            pair = (str(eid), prod_key)
                            if pair in seen_seller_products:
                                continue
                            seen_seller_products.add(pair)
                            rank_counter += 1
                            multi_matches.append(Match(
                                rfq_id=rfq.id,
                                seller_enterprise_id=eid,
                                similarity_score=SimilarityScore(value=sc),
                                rank=rank_counter,
                                matched_rfq_variant={
                                    "product": variant.get("product"),
                                    "quantity": variant.get("quantity"),
                                    "budget_max": variant.get("budget_max"),
                                    "budget_min": variant.get("budget_min"),
                                    "budget_per_unit": variant.get("budget_per_unit"),
                                    "budget_per_unit_min": variant.get("budget_per_unit_min"),
                                    "hsn_code": variant.get("hsn_code"),
                                },
                            ))
                    if multi_matches:
                        await match_repo.save_bulk(multi_matches)
                        rfq_matched_data = rfq.mark_matched(len(multi_matches))
                        await rfq_repo.update(rfq)
                        await session.commit()
                        try:
                            from src.marketplace.domain.events import RFQMatched as _RFQMatched
                            await self._publisher.publish(
                                _RFQMatched(
                                    aggregate_id=rfq.id,
                                    event_type="RFQMatched",
                                    top_score=max(m.similarity_score.value for m in multi_matches),
                                    **(rfq_matched_data or {}),
                                )
                            )
                        except Exception:
                            pass  # Event publish is non-fatal
                        log.info("rfq_multi_product_matched", rfq_id=str(rfq_id),
                                 products=all_prods, match_count=len(multi_matches))
                        return  # ← Skip single-product path

                enhanced_results = sorted(
                    merged_enhanced_by_seller.values(),
                    key=lambda m: m["composite_score"],
                    reverse=True,
                )[: self._top_n]
                raw_matches: list = []
                matches: list = []

                if enhanced_results:
                    matches = [
                        Match(
                            rfq_id=rfq.id,
                            seller_enterprise_id=m["enterprise_id"],
                            similarity_score=SimilarityScore(value=m["composite_score"]),
                            rank=rank + 1,
                        )
                        for rank, m in enumerate(enhanced_results)
                    ]
                    await match_repo.save_bulk(matches)
                    for m_data in enhanced_results:
                        match_row = await session.execute(
                            sa_select(MatchModel).where(
                                MatchModel.rfq_id == rfq.id,
                                MatchModel.seller_enterprise_id == m_data["enterprise_id"],
                            )
                        )
                        row = match_row.scalar_one_or_none()
                        if row:
                            row.semantic_score = m_data.get("semantic_score")
                            row.delivery_feasibility_score = m_data.get("delivery_feasibility_score")
                            row.capacity_score = m_data.get("capacity_score")
                            row.price_score = m_data.get("price_score")
                            row.proximity_score = m_data.get("proximity_score")
                            row.composite_score = m_data.get("composite_score")
                            row.estimated_delivery_days = m_data.get("estimated_delivery_days")
                            row.distance_km = m_data.get("distance_km")
                            raw_item_id = m_data.get("matched_catalogue_item_id")
                            if raw_item_id:
                                import uuid as _uuid
                                try:
                                    row.matched_catalogue_item_id = _uuid.UUID(raw_item_id)
                                except (ValueError, AttributeError):
                                    pass
                            # Attach which product variant this match was scored on
                            variant_for_match = best_variant_by_seller.get(m_data["enterprise_id"])
                            if variant_for_match:
                                row.matched_rfq_variant = {
                                    "product": variant_for_match.get("product"),
                                    "quantity": variant_for_match.get("quantity"),
                                    "budget_max": variant_for_match.get("budget_max"),
                                    "budget_per_unit": variant_for_match.get("budget_per_unit"),
                                }
                    raw_matches = [
                        (m["enterprise_id"], m["composite_score"]) for m in enhanced_results
                    ]
                elif merged_raw_scores:
                    raw_matches = sorted(
                        merged_raw_scores.items(), key=lambda x: x[1], reverse=True
                    )[: self._top_n]
                    matches = [
                        Match(
                            rfq_id=rfq.id,
                            seller_enterprise_id=ent_id,
                            similarity_score=SimilarityScore(value=score),
                            rank=rank + 1,
                            matched_rfq_variant={
                                "product": best_variant_by_seller.get(ent_id, {}).get("product"),
                                "quantity": best_variant_by_seller.get(ent_id, {}).get("quantity"),
                                "budget_max": best_variant_by_seller.get(ent_id, {}).get("budget_max"),
                            } if best_variant_by_seller.get(ent_id) else None,
                        )
                        for rank, (ent_id, score) in enumerate(raw_matches)
                    ]
                    await match_repo.save_bulk(matches)

                # Fallback: if no matches found, try direct enterprise commodity matching
                if not raw_matches:
                    log.info("rfq_trying_enterprise_fallback", rfq_id=str(rfq_id))
                    try:
                        from src.identity.infrastructure.models import EnterpriseModel
                        from sqlalchemy import select as sa_select, or_
                        parsed_product = (rfq.parsed_fields or {}).get("product", "") or (rfq.parsed_fields or {}).get("product_name", "")
                        parsed_category = (rfq.parsed_fields or {}).get("product_category", "")
                        search_terms = [t.lower() for t in [parsed_product, parsed_category] if t]

                        ent_stmt = sa_select(EnterpriseModel).where(
                            EnterpriseModel.id != rfq.buyer_enterprise_id,
                            or_(
                                EnterpriseModel.trade_role == "SELLER",
                                EnterpriseModel.trade_role == "BOTH",
                            ),
                        )
                        ent_result = await session.execute(ent_stmt)
                        seller_ents = ent_result.scalars().all()

                        fallback_matches = []
                        for ent in seller_ents:
                            kyc = ent.kyc_documents or {}
                            ent_commodities = [c.lower() for c in kyc.get("products_services", kyc.get("commodities", []))]
                            ent_industry = (kyc.get("industry_vertical") or "").lower()

                            # Check if any search term overlaps
                            match_score = 0.0
                            for term in search_terms:
                                if any(term in c or c in term for c in ent_commodities):
                                    match_score += 0.5
                                if term in ent_industry or ent_industry in term:
                                    match_score += 0.3
                            # Do NOT give a base score to all sellers when no product
                            # is identified — that would match every seller regardless.

                            if match_score > 0:
                                fallback_matches.append((ent.id, round(min(match_score, 1.0), 3)))

                        fallback_matches.sort(key=lambda x: x[1], reverse=True)
                        raw_matches = fallback_matches[:self._top_n]

                        if raw_matches:
                            matches = [
                                Match(
                                    rfq_id=rfq.id,
                                    seller_enterprise_id=ent_id,
                                    similarity_score=SimilarityScore(value=score),
                                    rank=rank + 1,
                                )
                                for rank, (ent_id, score) in enumerate(raw_matches)
                            ]
                            await match_repo.save_bulk(matches)
                            log.info("rfq_enterprise_fallback_matched", rfq_id=str(rfq_id), count=len(raw_matches))
                    except Exception:
                        log.exception("rfq_enterprise_fallback_failed", rfq_id=str(rfq_id))

                if not raw_matches:
                    log.info("rfq_no_matches", rfq_id=str(rfq_id))
                    await rfq_repo.update(rfq)
                    await session.commit()
                    return  # Stay PARSED

                # 6. Mark matched
                rfq_matched_data = rfq.mark_matched(len(matches))
                await rfq_repo.update(rfq)
                await session.commit()

                await self._publisher.publish(
                    RFQMatched(
                        aggregate_id=rfq.id,
                        event_type="RFQMatched",
                        top_score=raw_matches[0][1] if raw_matches else 0.0,
                        **rfq_matched_data,
                    )
                )

                log.info(
                    "rfq_parsed_and_matched",
                    rfq_id=str(rfq_id),
                    match_count=len(matches),
                )

            except Exception:
                log.exception("rfq_parse_match_failed", rfq_id=str(rfq_id))

    async def get_rfq(self, rfq_id: uuid.UUID) -> RFQ:
        rfq = await self._rfq_repo.get_by_id(rfq_id)
        if rfq is None:
            raise NotFoundError("RFQ", rfq_id)
        return rfq

    async def get_matches(self, rfq_id: uuid.UUID) -> list[Match]:
        return await self._match_repo.list_by_rfq(rfq_id)

    async def confirm_rfq(self, cmd: ConfirmRFQCommand) -> dict:
        """Confirm an RFQ match — resolves match from seller_enterprise_id,
        transitions RFQ to CONFIRMED, creates negotiation session SYNCHRONOUSLY,
        and returns the real session_id."""
        rfq = await self._rfq_repo.get_by_id(cmd.rfq_id)
        if rfq is None:
            raise NotFoundError("RFQ", cmd.rfq_id)

        if rfq.buyer_enterprise_id != cmd.buyer_enterprise_id:
            raise AuthorizationError("Only the buyer can confirm an RFQ.")

        # Resolve match from seller_enterprise_id
        match = await self._match_repo.get_match_by_seller(
            rfq_id=cmd.rfq_id,
            seller_enterprise_id=cmd.seller_enterprise_id,
        )
        if match is None:
            raise NotFoundError("Match", f"seller={cmd.seller_enterprise_id}")

        # Confirm RFQ + select match
        confirm_data = rfq.confirm(match.id)
        match.select()

        # Reject all other matches for this RFQ
        all_matches = await self._match_repo.list_by_rfq(rfq.id)
        for m in all_matches:
            if m.id != match.id and m.status.value == "PENDING":
                m.reject()
                await self._match_repo.update(m)

        await self._rfq_repo.update(rfq)
        await self._match_repo.update(match)

        # Create negotiation session SYNCHRONOUSLY to avoid session_id mismatch
        session_id = await self._create_negotiation_session_sync(
            match_id=match.id,
            rfq_id=rfq.id,
            buyer_enterprise_id=rfq.buyer_enterprise_id,
            seller_enterprise_id=match.seller_enterprise_id,
        )

        # Publish RFQConfirmed for audit/observability (non-blocking)
        await self._publisher.publish(
            RFQConfirmed(
                aggregate_id=rfq.id,
                event_type="RFQConfirmed",
                rfq_id=rfq.id,
                match_id=match.id,
                buyer_enterprise_id=rfq.buyer_enterprise_id,
                seller_enterprise_id=match.seller_enterprise_id,
            )
        )

        log.info(
            "rfq_confirmed",
            rfq_id=str(rfq.id),
            match_id=str(match.id),
            session_id=str(session_id),
        )
        return {
            "message": "Negotiation session created",
            "session_id": str(session_id),
        }

    async def start_all_negotiations(self, cmd: StartNegotiationsCommand) -> dict:
        """Start negotiations with ALL matched sellers simultaneously.
        Transitions RFQ from MATCHED → NEGOTIATING, creates sessions for each match."""
        rfq = await self._rfq_repo.get_by_id(cmd.rfq_id)
        if rfq is None:
            raise NotFoundError("RFQ", cmd.rfq_id)

        if rfq.buyer_enterprise_id != cmd.buyer_enterprise_id:
            raise AuthorizationError("Only the buyer can start negotiations.")

        # Get all pending matches
        all_matches = await self._match_repo.list_by_rfq(rfq.id)
        pending_matches = [m for m in all_matches if m.status.value == "PENDING"]

        if not pending_matches:
            raise NotFoundError("Matches", f"No pending matches for RFQ {cmd.rfq_id}")

        # Transition RFQ to NEGOTIATING
        rfq.start_negotiations(len(pending_matches))
        await self._rfq_repo.update(rfq)

        # Create negotiation sessions for ALL matches
        session_ids = []
        for match in pending_matches:
            try:
                session_id = await self._create_negotiation_session_sync(
                    match_id=match.id,
                    rfq_id=rfq.id,
                    buyer_enterprise_id=rfq.buyer_enterprise_id,
                    seller_enterprise_id=match.seller_enterprise_id,
                    # Pass per-product context so the session negotiates the correct product
                    override_rfq_parsed_fields=getattr(match, "matched_rfq_variant", None),
                )
                session_ids.append(str(session_id))
                log.info(
                    "negotiation_session_started",
                    rfq_id=str(rfq.id),
                    match_id=str(match.id),
                    session_id=str(session_id),
                    seller_id=str(match.seller_enterprise_id),
                )
            except Exception:
                log.exception(
                    "negotiation_session_start_failed",
                    rfq_id=str(rfq.id),
                    match_id=str(match.id),
                )

        log.info(
            "all_negotiations_started",
            rfq_id=str(rfq.id),
            session_count=len(session_ids),
            match_count=len(pending_matches),
        )

        # Auto-run negotiations in the background for each session.
        # Stagger starts by 8s to avoid exhausting Groq free-tier rate limits
        # (30 RPM per key) when multiple sessions fire LLM calls concurrently.
        for i, sid in enumerate(session_ids):
            async def _delayed_start(s_id: uuid.UUID, delay: float) -> None:
                if delay > 0:
                    await asyncio.sleep(delay)
                await self._run_auto_negotiation_standalone(s_id)
            asyncio.create_task(_delayed_start(uuid.UUID(sid), i * 8.0))

        return {
            "message": f"Started {len(session_ids)} negotiation sessions — auto-negotiating",
            "session_ids": session_ids,
            "rfq_status": "NEGOTIATING",
        }

    async def _create_negotiation_session_sync(
        self,
        match_id: uuid.UUID,
        rfq_id: uuid.UUID,
        buyer_enterprise_id: uuid.UUID,
        seller_enterprise_id: uuid.UUID,
        override_rfq_parsed_fields: dict | None = None,
    ) -> uuid.UUID:
        """Create a negotiation session synchronously with its own DB session."""
        from src.shared.infrastructure.db.session import get_session_factory
        from src.shared.infrastructure.db.uow import SqlAlchemyUnitOfWork
        from src.shared.infrastructure.events.publisher import get_publisher
        from src.negotiation.application.services import NegotiationService
        from src.negotiation.application.commands import CreateSessionCommand
        from src.negotiation.infrastructure.llm_agent_driver import get_agent_driver
        from src.negotiation.infrastructure.neutral_engine import NeutralEngine
        from src.negotiation.infrastructure.personalization import PersonalizationBuilder
        from src.negotiation.infrastructure.repositories import (
            PostgresAgentProfileRepository,
            PostgresNegotiationInsightRepository,
            PostgresNegotiationRecordRepository,
            PostgresOfferRepository,
            PostgresPlaybookRepository,
            PostgresSessionRepository,
        )

        async with get_session_factory()() as db_session:
            engine = NeutralEngine(
                agent_driver=get_agent_driver(),
                personalization_builder=PersonalizationBuilder(),
                sse_publisher=None,
                record_repo=PostgresNegotiationRecordRepository(db_session),
                insight_repo=PostgresNegotiationInsightRepository(db_session),
            )
            svc = NegotiationService(
                session_repo=PostgresSessionRepository(db_session),
                offer_repo=PostgresOfferRepository(db_session),
                profile_repo=PostgresAgentProfileRepository(db_session),
                playbook_repo=PostgresPlaybookRepository(db_session),
                neutral_engine=engine,
                sse_publisher=None,
                event_publisher=get_publisher(),
                uow=SqlAlchemyUnitOfWork(db_session),
            )
            session = await svc.create_session(
                CreateSessionCommand(
                    match_id=match_id,
                    rfq_id=rfq_id,
                    buyer_enterprise_id=buyer_enterprise_id,
                    seller_enterprise_id=seller_enterprise_id,
                    override_rfq_parsed_fields=override_rfq_parsed_fields,
                )
            )
            return session.id

    async def _run_auto_negotiation_standalone(self, session_id: uuid.UUID) -> None:
        """Background: run auto-negotiation for a session with its own DB session."""
        from src.shared.infrastructure.db.session import get_session_factory
        from src.shared.infrastructure.db.uow import SqlAlchemyUnitOfWork
        from src.shared.infrastructure.events.publisher import get_publisher
        from src.negotiation.application.services import NegotiationService
        from src.negotiation.infrastructure.llm_agent_driver import get_agent_driver
        from src.negotiation.infrastructure.neutral_engine import NeutralEngine
        from src.negotiation.infrastructure.personalization import PersonalizationBuilder
        from src.negotiation.infrastructure.repositories import (
            PostgresAgentProfileRepository,
            PostgresNegotiationInsightRepository,
            PostgresNegotiationRecordRepository,
            PostgresOfferRepository,
            PostgresPlaybookRepository,
            PostgresSessionRepository,
        )

        # Wait for session creation to be committed
        await asyncio.sleep(1.0)

        max_rounds = 20
        async with get_session_factory()() as db_session:
            try:
                engine = NeutralEngine(
                    agent_driver=get_agent_driver(),
                    personalization_builder=PersonalizationBuilder(),
                    sse_publisher=None,
                    record_repo=PostgresNegotiationRecordRepository(db_session),
                    insight_repo=PostgresNegotiationInsightRepository(db_session),
                )
                svc = NegotiationService(
                    session_repo=PostgresSessionRepository(db_session),
                    offer_repo=PostgresOfferRepository(db_session),
                    profile_repo=PostgresAgentProfileRepository(db_session),
                    playbook_repo=PostgresPlaybookRepository(db_session),
                    neutral_engine=engine,
                    sse_publisher=None,
                    event_publisher=get_publisher(),
                    uow=SqlAlchemyUnitOfWork(db_session),
                )

                import os as _os
                _inter_turn_delay = float(_os.getenv("AUTO_TURN_DELAY_SECONDS", "1.5"))

                for _round in range(max_rounds):
                    session = await svc.session_repo.get_by_id(session_id)
                    if not session or not session.status.is_active:
                        break
                    try:
                        await svc.run_agent_turn(session_id)
                    except Exception as turn_exc:
                        log.warning(
                            "auto_negotiation_turn_error",
                            session_id=str(session_id),
                            error=str(turn_exc),
                        )
                        break
                    if _inter_turn_delay > 0 and _round < max_rounds - 1:
                        await asyncio.sleep(_inter_turn_delay)

                session = await svc.session_repo.get_by_id(session_id)
                log.info(
                    "auto_negotiation_complete",
                    session_id=str(session_id),
                    final_status=session.status.value if session else "unknown",
                )
            except Exception:
                log.exception("auto_negotiation_failed", session_id=str(session_id))

    async def list_rfqs(
        self,
        buyer_enterprise_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
        statuses: list[str] | None = None,
    ) -> list[RFQ]:
        """List RFQs for the buyer's enterprise with optional status filter."""
        return await self._rfq_repo.list_by_buyer(
            buyer_enterprise_id=buyer_enterprise_id,
            limit=limit,
            offset=offset,
            statuses=statuses,
        )

    async def list_incoming_rfqs(
        self,
        seller_enterprise_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        """List RFQs where this seller enterprise is in the match results."""
        matches = await self._match_repo.list_by_seller(
            seller_enterprise_id=seller_enterprise_id,
            limit=limit,
            offset=offset,
        )
        results = []
        for match in matches:
            rfq = await self._rfq_repo.get_by_id(match.rfq_id)
            if rfq:
                results.append({
                    "match_id": match.id,
                    "rfq_id": rfq.id,
                    "raw_text": rfq.raw_document or "",
                    "status": rfq.status.value,
                    "parsed_fields": rfq.parsed_fields,
                    "created_at": rfq.created_at,
                    "similarity_score": match.similarity_score.value if match.similarity_score else 0.0,
                    "rank": match.rank,
                    "match_status": match.status.value,
                    "buyer_enterprise_id": rfq.buyer_enterprise_id,
                })
        return results

    async def update_capability_profile(
        self, cmd: UpdateCapabilityProfileCommand
    ) -> CapabilityProfile:
        profile = await self._profile_repo.get_by_enterprise(cmd.enterprise_id)
        if profile is None:
            profile = CapabilityProfile(enterprise_id=cmd.enterprise_id)

        event_data = profile.update_profile(
            industry_vertical=cmd.industry_vertical,
            product_categories=cmd.product_categories,
            geography_scope=cmd.geography_scope,
            trade_volume_min=cmd.trade_volume_min,
            trade_volume_max=cmd.trade_volume_max,
            profile_text=cmd.profile_text,
        )

        if await self._profile_repo.get_by_enterprise(cmd.enterprise_id):
            await self._profile_repo.update(profile)
        else:
            await self._profile_repo.save(profile)

        await self._publisher.publish(
            CapabilityProfileUpdated(
                aggregate_id=profile.id,
                event_type="CapabilityProfileUpdated",
                **event_data,
            )
        )

        # Schedule background embedding recompute (uses its own DB session)
        asyncio.create_task(self._recompute_embedding_standalone(cmd.enterprise_id))
        return profile

    async def _recompute_embedding_standalone(self, enterprise_id: uuid.UUID) -> None:
        """Background: generate embedding for capability profile with its own DB session.

        Fix 5: embedding text now includes all active catalogue items
        (product_name, hsn_code, grade, specification_text) so the seller vector
        reflects their actual product range, not just coarse commodity tags.

        Fix 6: debounce guard prevents N concurrent recomputes when a seller
        bulk-uploads multiple catalogue items in quick succession.
        """
        from src.marketplace.infrastructure.repositories import (
            PostgresCapabilityProfileRepository,
        )
        from src.shared.infrastructure.db.session import get_session_factory

        eid_str = str(enterprise_id)
        # Fix 6: debounce — if another task already queued for this seller, skip
        if _EMBEDDING_RECOMPUTE_LOCK.get(eid_str):
            log.info("embedding_recompute_debounced", enterprise_id=eid_str)
            return
        _EMBEDDING_RECOMPUTE_LOCK[eid_str] = True

        try:
            # Wait for the parent request's transaction to commit before we read.
            await asyncio.sleep(0.5)

            factory = get_session_factory()
            async with factory() as session:
                try:
                    profile_repo = PostgresCapabilityProfileRepository(session)
                    profile = await profile_repo.get_by_enterprise(enterprise_id)

                    # Retry if profile not yet visible (transaction isolation)
                    if profile is None:
                        for _attempt in range(3):
                            await asyncio.sleep(0.5)
                            profile = await profile_repo.get_by_enterprise(enterprise_id)
                            if profile is not None:
                                break
                    if profile is None:
                        log.warning("embedding_profile_not_found", enterprise_id=eid_str)
                        return

                    text_parts = [
                        profile.profile_text or "",
                        " ".join(profile.product_categories),
                        " ".join(profile.geography_scope),
                        profile.industry_vertical or "",
                    ]

                    # Fix 5: fetch all active catalogue items and include in embedding
                    from src.marketplace.infrastructure.models import CatalogueItemModel
                    from sqlalchemy import select as _sa_select
                    cat_result = await session.execute(
                        _sa_select(CatalogueItemModel).where(
                            CatalogueItemModel.enterprise_id == enterprise_id,
                            CatalogueItemModel.is_active == True,  # noqa: E712
                        )
                    )
                    catalogue_items = cat_result.scalars().all()
                    catalogue_lines = []
                    for item in catalogue_items:
                        parts = [
                            item.product_name,
                            item.hsn_code,
                            item.product_category,
                        ]
                        if item.grade:
                            parts.append(item.grade)
                        if item.specification_text:
                            parts.append(item.specification_text[:200])
                        catalogue_lines.append(" | ".join(p for p in parts if p))
                    if catalogue_lines:
                        text_parts.append(". ".join(catalogue_lines))

                    text = " ".join(p for p in text_parts if p)
                    if not text.strip():
                        return
                    embedding = await self._parser.generate_embedding(text)
                    profile.set_embedding(embedding)
                    await profile_repo.update(profile)
                    await session.commit()
                    log.info(
                        "embedding_recomputed",
                        enterprise_id=eid_str,
                        catalogue_items=len(catalogue_items),
                    )
                except Exception:
                    log.exception("embedding_recompute_failed", enterprise_id=eid_str)
        finally:
            _EMBEDDING_RECOMPUTE_LOCK.pop(eid_str, None)  # always release
