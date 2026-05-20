"""
Domain event handler registry.

context.md §7: Event handler subscriptions wired here.
Phase 0: No subscriptions.
Phase 2: EscrowFunded, EscrowReleased, SessionAgreedStub stub handlers.
Phase 3: Full compliance handlers replace Phase 2 stubs.
         + EscrowRefunded, EscrowFrozen compliance handlers.
         + HMAC-signed webhook notifiers for all settlement events.
"""

from src.shared.infrastructure.events.publisher import EventPublisher
from src.shared.infrastructure.logging import get_logger

log = get_logger(__name__)


def register_handlers(publisher: EventPublisher) -> None:
    """
    Register all Phase 0 + Phase 1 cross-domain event handlers.

    Called once at application startup (lifespan).
    Phase 0: No subscriptions.
    """
    log.info("event_handlers_registered", phase="0_and_1", handler_count=0)


# ── Phase Two — Compliance Stub Handlers ─────────────────────────────────────


async def handle_escrow_funded_stub(event: object) -> None:
    """
    Phase Two stub: log EscrowFunded event for compliance pipeline.
    Replaced by handle_escrow_funded_compliance in Phase Three.
    """
    log.info(
        "escrow_funded_event_received",
        escrow_id=str(getattr(event, "escrow_id", "")),
        session_id=str(getattr(event, "session_id", "")),
        amount_microalgo=getattr(event, "amount_microalgo", 0),
        fund_tx_id=getattr(event, "fund_tx_id", ""),
        phase="stub_phase_two",
    )


async def handle_escrow_released_stub(event: object) -> None:
    """
    Phase Two stub: log EscrowReleased event for compliance pipeline.
    Replaced by handle_escrow_released_compliance in Phase Three.
    """
    log.info(
        "escrow_released_event_received",
        escrow_id=str(getattr(event, "escrow_id", "")),
        session_id=str(getattr(event, "session_id", "")),
        merkle_root=getattr(event, "merkle_root", ""),
        release_tx_id=getattr(event, "release_tx_id", ""),
        phase="stub_phase_two",
    )


async def handle_session_agreed_stub(event: object) -> None:
    """
    Phase Two stub: log SessionAgreedStub event (does NOT auto-deploy escrow).

    Full auto-deploy wiring activated in Phase Four when NegotiationService
    publishes the real SessionAgreed event.
    context.md §7: SessionAgreed → settlement DeployEscrow (Phase Four)
    """
    log.info(
        "session_agreed_stub_received",
        session_id=str(getattr(event, "session_id", "")),
        buyer_enterprise_id=str(getattr(event, "buyer_enterprise_id", "")),
        seller_enterprise_id=str(getattr(event, "seller_enterprise_id", "")),
        agreed_price_microalgo=getattr(event, "agreed_price_microalgo", 0),
        phase="stub_phase_two",
    )
    # TODO Phase Four: SettlementService.deploy_escrow(DeployEscrowCommand(...))


def register_phase_two_handlers(publisher: EventPublisher) -> None:
    """
    Register Phase Two stub event handlers.

    Called in main.py lifespan AFTER register_handlers(). Additive only.
    Phase Three replaces EscrowFunded and EscrowReleased with full compliance handlers.
    """
    publisher.subscribe("EscrowFunded", handle_escrow_funded_stub)
    publisher.subscribe("EscrowReleased", handle_escrow_released_stub)
    publisher.subscribe("SessionAgreedStub", handle_session_agreed_stub)

    log.info(
        "phase_two_event_handlers_registered",
        handlers=["EscrowFunded", "EscrowReleased", "SessionAgreedStub"],
    )


# ── Phase Three — Full Compliance Handlers ────────────────────────────────────


def _build_compliance_service(session: object) -> object:
    """Construct ComplianceService with all concrete adapters for a given session."""
    from src.shared.infrastructure.merkle_service import MerkleService
    from src.shared.infrastructure.db.uow import SqlAlchemyUnitOfWork
    from src.compliance.application.services import ComplianceService
    from src.compliance.infrastructure.enterprise_reader import PostgresEnterpriseReader
    from src.compliance.infrastructure.fema_gst_exporter import FEMAGSTExporter
    from src.compliance.infrastructure.repositories import (
        PostgresAuditLogRepository,
        PostgresExportJobRepository,
        PostgresFEMARepository,
        PostgresGSTRepository,
    )
    return ComplianceService(
        audit_repo=PostgresAuditLogRepository(session),  # type: ignore[arg-type]
        fema_repo=PostgresFEMARepository(session),  # type: ignore[arg-type]
        gst_repo=PostgresGSTRepository(session),  # type: ignore[arg-type]
        export_job_repo=PostgresExportJobRepository(session),  # type: ignore[arg-type]
        enterprise_reader=PostgresEnterpriseReader(session),  # type: ignore[arg-type]
        merkle_service=MerkleService(),
        exporter=FEMAGSTExporter(),
        uow=SqlAlchemyUnitOfWork(session),  # type: ignore[arg-type]
    )


async def handle_escrow_funded_compliance(event: object) -> None:
    """
    Phase Three: append EscrowFunded to hash-chained audit log.

    context.md §7: EscrowFunded -> ComplianceService.append_audit_event()
    """
    escrow_id = getattr(event, "escrow_id", None)
    if not escrow_id:
        log.warning("handle_escrow_funded_compliance_missing_escrow_id")
        return

    payload = {
        "escrow_id": str(escrow_id),
        "session_id": str(getattr(event, "session_id", "")),
        "amount_microalgo": getattr(event, "amount_microalgo", 0),
        "fund_tx_id": getattr(event, "fund_tx_id", ""),
    }

    try:
        from src.shared.infrastructure.db.session import get_session_factory
        from src.compliance.application.commands import AppendAuditEventCommand
        async with get_session_factory()() as session:
            svc = _build_compliance_service(session)
            await svc.append_audit_event(  # type: ignore[union-attr]
                AppendAuditEventCommand(
                    escrow_id=escrow_id,
                    event_type="EscrowFunded",
                    payload=payload,
                )
            )
    except Exception:
        log.exception(
            "handle_escrow_funded_compliance_failed",
            escrow_id=str(escrow_id),
        )


async def handle_escrow_released_compliance(event: object) -> None:
    """
    Phase Three: append audit entry + generate FEMA/GST compliance records.

    context.md §7: EscrowReleased -> ComplianceService.generate_compliance_records()
    """
    import uuid
    escrow_id = getattr(event, "escrow_id", None)
    if not escrow_id:
        log.warning("handle_escrow_released_compliance_missing_escrow_id")
        return

    session_id = getattr(event, "session_id", uuid.uuid4())
    amount_microalgo = getattr(event, "amount_microalgo", 0)
    merkle_root = getattr(event, "merkle_root", "")
    buyer_enterprise_id = getattr(event, "buyer_enterprise_id", None)
    seller_enterprise_id = getattr(event, "seller_enterprise_id", None)

    audit_payload = {
        "escrow_id": str(escrow_id),
        "session_id": str(session_id),
        "amount_microalgo": amount_microalgo,
        "release_tx_id": getattr(event, "release_tx_id", ""),
        "merkle_root": merkle_root,
    }

    try:
        from src.shared.infrastructure.db.session import get_session_factory
        from src.compliance.application.commands import (
            AppendAuditEventCommand,
            GenerateComplianceRecordsCommand,
        )
        async with get_session_factory()() as session:
            svc = _build_compliance_service(session)
            # 1. Append audit entry
            await svc.append_audit_event(  # type: ignore[union-attr]
                AppendAuditEventCommand(
                    escrow_id=escrow_id,
                    event_type="EscrowReleased",
                    payload=audit_payload,
                )
            )
            # 2. Generate FEMA + GST compliance records
            await svc.generate_compliance_records(  # type: ignore[union-attr]
                GenerateComplianceRecordsCommand(
                    escrow_id=escrow_id,
                    session_id=session_id,
                    amount_microalgo=amount_microalgo,
                    merkle_root=merkle_root,
                    buyer_enterprise_id=buyer_enterprise_id,
                    seller_enterprise_id=seller_enterprise_id,
                )
            )
    except Exception:
        log.exception(
            "handle_escrow_released_compliance_failed",
            escrow_id=str(escrow_id),
        )


async def handle_escrow_refunded_compliance(event: object) -> None:
    """
    Phase Three: append EscrowRefunded to hash-chained audit log.

    Refunds generate an audit entry but do NOT generate FEMA/GST records
    (no settlement occurred — funds returned to buyer).
    """
    escrow_id = getattr(event, "escrow_id", None)
    if not escrow_id:
        log.warning("handle_escrow_refunded_compliance_missing_escrow_id")
        return

    payload = {
        "escrow_id": str(escrow_id),
        "session_id": str(getattr(event, "session_id", "")),
        "amount_microalgo": getattr(event, "amount_microalgo", 0),
        "refund_tx_id": getattr(event, "refund_tx_id", ""),
        "reason": getattr(event, "reason", ""),
    }

    try:
        from src.shared.infrastructure.db.session import get_session_factory
        from src.compliance.application.commands import AppendAuditEventCommand
        async with get_session_factory()() as session:
            svc = _build_compliance_service(session)
            await svc.append_audit_event(  # type: ignore[union-attr]
                AppendAuditEventCommand(
                    escrow_id=escrow_id,
                    event_type="EscrowRefunded",
                    payload=payload,
                )
            )
    except Exception:
        log.exception(
            "handle_escrow_refunded_compliance_failed",
            escrow_id=str(escrow_id),
        )


async def handle_escrow_frozen_compliance(event: object) -> None:
    """
    Phase Three: append EscrowFrozen to hash-chained audit log.

    Freeze events generate an audit entry for dispute tracking.
    """
    escrow_id = getattr(event, "escrow_id", None)
    if not escrow_id:
        log.warning("handle_escrow_frozen_compliance_missing_escrow_id")
        return

    payload = {
        "escrow_id": str(escrow_id),
        "session_id": str(getattr(event, "session_id", "")),
        "frozen_by": getattr(event, "frozen_by", "ADMIN"),
    }

    try:
        from src.shared.infrastructure.db.session import get_session_factory
        from src.compliance.application.commands import AppendAuditEventCommand
        async with get_session_factory()() as session:
            svc = _build_compliance_service(session)
            await svc.append_audit_event(  # type: ignore[union-attr]
                AppendAuditEventCommand(
                    escrow_id=escrow_id,
                    event_type="EscrowFrozen",
                    payload=payload,
                )
            )
    except Exception:
        log.exception(
            "handle_escrow_frozen_compliance_failed",
            escrow_id=str(escrow_id),
        )


async def handle_escrow_deployed_compliance(event: object) -> None:
    """
    Phase Three: append EscrowDeployed to hash-chained audit log.

    context.md §7: EscrowDeployed → compliance (AppendAuditEvent ESCROW_DEPLOYED)
    """
    escrow_id = getattr(event, "escrow_id", None)
    if not escrow_id:
        log.warning("handle_escrow_deployed_compliance_missing_escrow_id")
        return

    payload = {
        "escrow_id": str(escrow_id),
        "session_id": str(getattr(event, "session_id", "")),
        "algo_app_id": getattr(event, "algo_app_id", 0),
        "deploy_tx_id": getattr(event, "deploy_tx_id", ""),
    }

    try:
        from src.shared.infrastructure.db.session import get_session_factory
        from src.compliance.application.commands import AppendAuditEventCommand
        async with get_session_factory()() as session:
            svc = _build_compliance_service(session)
            await svc.append_audit_event(  # type: ignore[union-attr]
                AppendAuditEventCommand(
                    escrow_id=escrow_id,
                    event_type="EscrowDeployed",
                    payload=payload,
                )
            )
    except Exception:
        log.exception(
            "handle_escrow_deployed_compliance_failed",
            escrow_id=str(escrow_id),
        )


def register_phase_three_handlers(publisher: EventPublisher) -> None:
    """
    Replace Phase Two stub handlers with full Phase Three compliance handlers
    and register HMAC-signed webhook notifiers.

    Unsubscribes Phase Two stubs for EscrowFunded and EscrowReleased,
    then subscribes the real compliance handlers + webhook notifiers.

    Called in main.py lifespan AFTER register_phase_two_handlers().
    """
    # ── Replace EscrowFunded stub with compliance handler ─────────────────────
    publisher.unsubscribe("EscrowFunded", handle_escrow_funded_stub)
    publisher.subscribe("EscrowFunded", handle_escrow_funded_compliance)

    # ── Replace EscrowReleased stub with compliance handler ───────────────────
    publisher.unsubscribe("EscrowReleased", handle_escrow_released_stub)
    publisher.subscribe("EscrowReleased", handle_escrow_released_compliance)

    # ── Subscribe EscrowRefunded compliance handler (new in Phase Three) ──────
    publisher.subscribe("EscrowRefunded", handle_escrow_refunded_compliance)

    # ── Subscribe EscrowFrozen compliance handler (new in Phase Three) ────────
    publisher.subscribe("EscrowFrozen", handle_escrow_frozen_compliance)

    # ── Subscribe EscrowDeployed compliance handler (context.md §7) ───────────
    publisher.subscribe("EscrowDeployed", handle_escrow_deployed_compliance)

    # ── Subscribe HMAC-signed webhook notifiers for all settlement events ─────
    from src.shared.infrastructure.webhook_notifier import (
        notify_escrow_funded,
        notify_escrow_released,
        notify_escrow_refunded,
        notify_escrow_frozen,
    )
    publisher.subscribe("EscrowFunded", notify_escrow_funded)
    publisher.subscribe("EscrowReleased", notify_escrow_released)
    publisher.subscribe("EscrowRefunded", notify_escrow_refunded)
    publisher.subscribe("EscrowFrozen", notify_escrow_frozen)

    log.info(
        "phase_three_event_handlers_registered",
        handlers=[
            "EscrowDeployed->compliance",
            "EscrowFunded->compliance",
            "EscrowReleased->compliance",
            "EscrowRefunded->compliance",
            "EscrowFrozen->compliance",
            "EscrowFunded->webhook",
            "EscrowReleased->webhook",
            "EscrowRefunded->webhook",
            "EscrowFrozen->webhook",
        ],
    )


# ── Phase Four — Negotiation Event Handlers ───────────────────────────────────
# WIRING: shared/handlers.py is the cross-domain event bus.
# It imports from bounded contexts to wire event → command.
# This is the ONLY permitted cross-domain import outside domain.
# REF: context.md §1.3, §3.2


async def handle_session_agreed_deploy(event: object) -> None:
    """
    Phase Four: SessionAgreed → Create PENDING_APPROVAL escrow.

    Instead of auto-deploying on-chain, creates an escrow record in
    PENDING_APPROVAL state. Admin must approve via the admin dashboard
    to trigger the actual on-chain deployment.

    Replaces handle_session_agreed_stub from Phase Two.
    context.md §3.2: SessionAgreed → settlement CreatePendingEscrow
    """
    session_id = getattr(event, "session_id", None)
    if not session_id:
        log.warning("handle_session_agreed_deploy_missing_session_id")
        return

    buyer_enterprise_id = getattr(event, "buyer_enterprise_id", None)
    seller_enterprise_id = getattr(event, "seller_enterprise_id", None)
    agreed_price = getattr(event, "agreed_price", 0)

    if not all([buyer_enterprise_id, seller_enterprise_id]):
        log.error(
            "handle_session_agreed_deploy_missing_enterprise_ids",
            session_id=str(session_id),
        )
        return

    log.info(
        "session_agreed_creating_pending_escrow",
        session_id=str(session_id),
        agreed_price=str(agreed_price),
        buyer_enterprise_id=str(buyer_enterprise_id),
        seller_enterprise_id=str(seller_enterprise_id),
    )

    # ── Build SettlementService and create pending escrow ──────────────────
    try:
        from src.shared.infrastructure.db.session import get_session_factory
        from src.shared.infrastructure.db.uow import SqlAlchemyUnitOfWork
        from src.shared.infrastructure.events.publisher import get_publisher
        from src.shared.infrastructure.merkle_service import MerkleService
        from src.settlement.application.services import SettlementService
        from src.settlement.application.commands import CreatePendingEscrowCommand
        from src.settlement.infrastructure.algorand_gateway import AlgorandGateway
        from src.settlement.infrastructure.repositories import (
            PostgresEscrowRepository,
            PostgresSettlementRepository,
        )

        async with get_session_factory()() as db_session:
            svc = SettlementService(
                escrow_repo=PostgresEscrowRepository(db_session),
                settlement_repo=PostgresSettlementRepository(db_session),
                blockchain_gateway=AlgorandGateway(),
                merkle_service=MerkleService(),
                anchor_service=None,
                event_publisher=get_publisher(),
                uow=SqlAlchemyUnitOfWork(db_session),
            )
            result = await svc.create_pending_escrow(
                CreatePendingEscrowCommand(
                    session_id=session_id,
                    buyer_enterprise_id=buyer_enterprise_id,
                    seller_enterprise_id=seller_enterprise_id,
                    agreed_price_inr=float(agreed_price),
                )
            )
            log.info(
                "session_agreed_pending_escrow_created",
                session_id=str(session_id),
                escrow_id=str(result["escrow_id"]),
            )
    except Exception:
        log.exception(
            "handle_session_agreed_deploy_failed",
            session_id=str(session_id),
        )


async def handle_session_agreed_audit(event: object) -> None:
    """Phase Four: append SESSION_AGREED audit entry."""
    session_id = getattr(event, "session_id", None)
    if not session_id:
        return

    payload = {
        "session_id": str(session_id),
        "agreed_price": str(getattr(event, "agreed_price", "")),
        "agreed_currency": getattr(event, "agreed_currency", "INR"),
        "buyer_enterprise_id": str(getattr(event, "buyer_enterprise_id", "")),
        "seller_enterprise_id": str(getattr(event, "seller_enterprise_id", "")),
    }

    try:
        from src.shared.infrastructure.db.session import get_session_factory
        from src.compliance.application.commands import AppendAuditEventCommand
        async with get_session_factory()() as session:
            svc = _build_compliance_service(session)
            await svc.append_audit_event(  # type: ignore[union-attr]
                AppendAuditEventCommand(
                    escrow_id=session_id,
                    event_type="SessionAgreed",
                    payload=payload,
                )
            )
    except Exception:
        log.exception("handle_session_agreed_audit_failed", session_id=str(session_id))


async def handle_offer_submitted_audit(event: object) -> None:
    """Phase Four: append OFFER_SUBMITTED audit entry."""
    session_id = getattr(event, "session_id", None)
    if not session_id:
        return
    log.info(
        "offer_submitted_audit",
        session_id=str(session_id),
        offer_id=str(getattr(event, "offer_id", "")),
        round_number=getattr(event, "round_number", 0),
        proposer_role=getattr(event, "proposer_role", ""),
    )


async def handle_human_override_audit(event: object) -> None:
    """Phase Four: append HUMAN_OVERRIDE audit entry."""
    session_id = getattr(event, "session_id", None)
    if not session_id:
        return
    log.info(
        "human_override_audit",
        session_id=str(session_id),
        offer_id=str(getattr(event, "offer_id", "")),
        price=str(getattr(event, "price", "")),
        applied_by_user_id=str(getattr(event, "applied_by_user_id", "")),
    )


async def handle_session_failed_audit(event: object) -> None:
    """Phase Four: append SESSION_FAILED audit entry."""
    session_id = getattr(event, "session_id", None)
    if not session_id:
        return
    log.info(
        "session_failed_audit",
        session_id=str(session_id),
        reason=getattr(event, "reason", ""),
        round_count=getattr(event, "round_count", 0),
    )


async def handle_session_agreed_confirm_rfq(event: object) -> None:
    """
    Phase Four: SessionAgreed → Transition RFQ from NEGOTIATING → CONFIRMED.

    When a negotiation session reaches agreement, the corresponding RFQ
    should be marked as CONFIRMED with the winning match selected.
    """
    rfq_id = getattr(event, "rfq_id", None)
    match_id = getattr(event, "match_id", None)
    seller_enterprise_id = getattr(event, "seller_enterprise_id", None)

    if not rfq_id:
        log.warning("handle_session_agreed_confirm_rfq_missing_rfq_id")
        return

    try:
        from src.shared.infrastructure.db.session import get_session_factory
        from src.marketplace.infrastructure.repositories import (
            PostgresRFQRepository,
            PostgresMatchRepository,
        )

        async with get_session_factory()() as db_session:
            rfq_repo = PostgresRFQRepository(db_session)
            match_repo = PostgresMatchRepository(db_session)

            rfq = await rfq_repo.get_by_id(rfq_id)
            if not rfq:
                log.warning("handle_session_agreed_confirm_rfq_rfq_not_found", rfq_id=str(rfq_id))
                return

            # Only transition if still in NEGOTIATING state
            if rfq.status.value != "NEGOTIATING":
                log.info(
                    "handle_session_agreed_confirm_rfq_skip",
                    rfq_id=str(rfq_id),
                    current_status=rfq.status.value,
                )
                return

            # Confirm with the winning match
            if match_id:
                rfq.confirm(match_id)

                # Select the winning match and reject others
                all_matches = await match_repo.list_by_rfq(rfq_id)
                for m in all_matches:
                    if m.id == match_id:
                        m.select()
                        await match_repo.update(m)
                    elif m.status.value == "PENDING":
                        m.reject()
                        await match_repo.update(m)
            else:
                # No match_id — still confirm the RFQ with a placeholder
                import uuid as uuid_mod
                rfq.confirm(uuid_mod.uuid4())

            await rfq_repo.update(rfq)
            await db_session.commit()

            log.info(
                "rfq_confirmed_via_session_agreed",
                rfq_id=str(rfq_id),
                match_id=str(match_id),
            )
    except Exception:
        log.exception(
            "handle_session_agreed_confirm_rfq_failed",
            rfq_id=str(rfq_id),
        )


async def handle_escrow_released_settle_rfq(event: object) -> None:
    """
    Phase Four: EscrowReleased → Transition RFQ from CONFIRMED → SETTLED.

    When the escrow is released (funds sent to seller), the RFQ is fully settled.
    Looks up rfq_id via the negotiation session linked to the escrow.
    """
    session_id = getattr(event, "session_id", None)
    if not session_id:
        log.warning("handle_escrow_released_settle_rfq_missing_session_id")
        return

    try:
        from src.shared.infrastructure.db.session import get_session_factory
        from src.marketplace.infrastructure.repositories import PostgresRFQRepository
        from src.negotiation.infrastructure.models import NegotiationSessionModel
        from sqlalchemy import select as sa_select

        async with get_session_factory()() as db_session:
            # Look up rfq_id from the negotiation session
            result = await db_session.execute(
                sa_select(NegotiationSessionModel.rfq_id).where(
                    NegotiationSessionModel.id == session_id
                )
            )
            rfq_id = result.scalar_one_or_none()
            if not rfq_id:
                log.warning(
                    "handle_escrow_released_settle_rfq_session_not_found",
                    session_id=str(session_id),
                )
                return

            rfq_repo = PostgresRFQRepository(db_session)
            rfq = await rfq_repo.get_by_id(rfq_id)
            if not rfq:
                log.warning(
                    "handle_escrow_released_settle_rfq_rfq_not_found",
                    rfq_id=str(rfq_id),
                )
                return

            # Only transition if in CONFIRMED state
            if rfq.status.value != "CONFIRMED":
                log.info(
                    "handle_escrow_released_settle_rfq_skip",
                    rfq_id=str(rfq_id),
                    current_status=rfq.status.value,
                )
                return

            rfq.mark_settled()
            await rfq_repo.update(rfq)
            await db_session.commit()

            log.info(
                "rfq_settled_via_escrow_released",
                rfq_id=str(rfq_id),
                session_id=str(session_id),
            )
    except Exception:
        log.exception(
            "handle_escrow_released_settle_rfq_failed",
            session_id=str(session_id),
        )


def register_phase_four_handlers(publisher: EventPublisher) -> None:
    """
    Replace SessionAgreedStub with real handlers and register
    negotiation audit event handlers.

    Called in main.py lifespan AFTER register_phase_three_handlers().
    """
    # Replace SessionAgreedStub with real SessionAgreed handlers
    # NOTE: handle_session_agreed_deploy REMOVED — buyer must explicitly select a deal
    # via POST /v1/escrow/select-deal before any escrow is created.
    publisher.unsubscribe("SessionAgreedStub", handle_session_agreed_stub)
    publisher.subscribe("SessionAgreed", handle_session_agreed_audit)
    publisher.subscribe("SessionAgreed", handle_session_agreed_confirm_rfq)

    # EscrowReleased → settle RFQ
    publisher.subscribe("EscrowReleased", handle_escrow_released_settle_rfq)

    # Wire negotiation audit events
    publisher.subscribe("OfferSubmitted", handle_offer_submitted_audit)
    publisher.subscribe("HumanOverrideApplied", handle_human_override_audit)
    publisher.subscribe("SessionFailed", handle_session_failed_audit)

    log.info(
        "phase_four_event_handlers_registered",
        handlers=[
            "SessionAgreed->deploy",
            "SessionAgreed->audit",
            "SessionAgreed->confirm_rfq",
            "EscrowReleased->settle_rfq",
            "OfferSubmitted->audit",
            "HumanOverrideApplied->audit",
            "SessionFailed->audit",
        ],
    )


# ── Phase Five — Marketplace → Negotiation Handlers ────────────────────────


async def handle_rfq_confirmed(event: object) -> None:
    """
    Phase Five: RFQConfirmed → NegotiationService.create_session().

    Builds a standalone NegotiationService with its own DB session
    and creates a negotiation session from the confirmed RFQ match.
    """
    rfq_id = getattr(event, "rfq_id", None)
    match_id = getattr(event, "match_id", None)
    buyer_id = getattr(event, "buyer_enterprise_id", None)
    seller_id = getattr(event, "seller_enterprise_id", None)

    if not all([rfq_id, match_id, buyer_id, seller_id]):
        log.error("rfq_confirmed_missing_fields", event=str(event))
        return

    log.info(
        "rfq_confirmed_creating_session",
        rfq_id=str(rfq_id),
        match_id=str(match_id),
        buyer_enterprise_id=str(buyer_id),
        seller_enterprise_id=str(seller_id),
    )

    try:
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
            PostgresOfferRepository,
            PostgresPlaybookRepository,
            PostgresSessionRepository,
        )

        async with get_session_factory()() as db_session:
            session_repo = PostgresSessionRepository(db_session)

            # Idempotency: skip if session already exists (created synchronously by confirm_rfq)
            existing = await session_repo.get_by_match_id(match_id)
            if existing:
                log.info(
                    "rfq_confirmed_session_already_exists",
                    session_id=str(existing.id),
                    match_id=str(match_id),
                )
                return

            engine = NeutralEngine(
                agent_driver=get_agent_driver(),
                personalization_builder=PersonalizationBuilder(),
                sse_publisher=None,
            )
            svc = NegotiationService(
                session_repo=session_repo,
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
                    buyer_enterprise_id=buyer_id,
                    seller_enterprise_id=seller_id,
                )
            )
            log.info(
                "rfq_confirmed_session_created",
                session_id=str(session.id),
                rfq_id=str(rfq_id),
                match_id=str(match_id),
            )
    except Exception:
        log.exception(
            "handle_rfq_confirmed_create_session_failed",
            rfq_id=str(rfq_id),
            match_id=str(match_id),
        )


async def handle_rfq_parsed_audit(event: object) -> None:
    """Phase Five: log RFQParsed for observability."""
    log.info(
        "rfq_parsed_audit",
        rfq_id=str(getattr(event, "rfq_id", "")),
        hsn_code=getattr(event, "hsn_code", None),
        has_budget=getattr(event, "has_budget", False),
    )


async def handle_rfq_matched_audit(event: object) -> None:
    """Phase Five: log RFQMatched for observability."""
    log.info(
        "rfq_matched_audit",
        rfq_id=str(getattr(event, "rfq_id", "")),
        match_count=getattr(event, "match_count", 0),
        top_score=getattr(event, "top_score", 0.0),
    )


async def handle_enterprise_registered_create_profile(event: object) -> None:
    """
    Phase Five: EnterpriseRegistered → auto-create CapabilityProfile for sellers.

    Reads enterprise data from DB and creates a CapabilityProfile with
    commodities, industry, geography, and order values from registration.
    Also triggers background embedding generation.
    """
    enterprise_id = getattr(event, "enterprise_id", None)
    trade_role = getattr(event, "trade_role", "")

    if trade_role not in ("SELLER", "BOTH"):
        log.info(
            "enterprise_registered_skip_profile",
            enterprise_id=str(enterprise_id),
            trade_role=trade_role,
            reason="not_seller",
        )
        return

    if not enterprise_id:
        log.warning("enterprise_registered_missing_id")
        return

    import asyncio
    await asyncio.sleep(0.5)  # Wait for parent transaction to commit

    try:
        from src.shared.infrastructure.db.session import get_session_factory
        from src.identity.infrastructure.models import EnterpriseModel
        from src.marketplace.infrastructure.models import CapabilityProfileModel
        from sqlalchemy import select as sa_select
        import uuid as uuid_mod

        async with get_session_factory()() as session:
            # Read enterprise data
            result = await session.execute(
                sa_select(EnterpriseModel).where(EnterpriseModel.id == enterprise_id)
            )
            ent = result.scalar_one_or_none()
            if not ent:
                log.error("enterprise_not_found_for_profile", enterprise_id=str(enterprise_id))
                return

            # Check if profile already exists
            existing = await session.execute(
                sa_select(CapabilityProfileModel).where(
                    CapabilityProfileModel.enterprise_id == enterprise_id
                )
            )
            if existing.scalar_one_or_none():
                log.info("profile_already_exists", enterprise_id=str(enterprise_id))
                return

            # Extract enterprise details from kyc_documents JSONB
            kyc = ent.kyc_documents or {}
            commodities = kyc.get("commodities", [])
            industry = kyc.get("industry_vertical", "")
            geography = kyc.get("geography", "IN")
            min_order = kyc.get("min_order_value")
            max_order = kyc.get("max_order_value")

            # Build profile text from registration data
            profile_parts = []
            if ent.name:
                profile_parts.append(ent.name)
            if industry:
                profile_parts.append(f"Industry: {industry}")
            if commodities:
                profile_parts.append(f"Products: {', '.join(commodities)}")
            if geography:
                profile_parts.append(f"Geography: {geography}")
            profile_text = ". ".join(profile_parts)

            # Create CapabilityProfile
            profile = CapabilityProfileModel(
                id=uuid_mod.uuid4(),
                enterprise_id=enterprise_id,
                industry_vertical=industry or None,
                commodities=commodities,
                geographies_served=[geography] if geography else [],
                min_order_value=float(min_order) if min_order is not None else None,
                max_order_value=float(max_order) if max_order is not None else None,
                profile_text=profile_text,
                embedding=None,
            )
            session.add(profile)
            await session.commit()

            log.info(
                "seller_profile_auto_created",
                enterprise_id=str(enterprise_id),
                commodities=commodities,
                industry=industry,
            )

            # Trigger background embedding generation
            from src.marketplace.infrastructure.repositories import (
                PostgresCapabilityProfileRepository,
            )
            from src.marketplace.infrastructure.document_parser import get_document_parser
            from src.marketplace.infrastructure.models import CatalogueItemModel
            from sqlalchemy import select as _sa_select

            parser = get_document_parser()
            text_parts = [
                profile_text,
                " ".join(commodities),
                geography,
                industry or "",
            ]

            # Fix 5: include any catalogue items the seller may have already added
            # before their profile was created (registration order can vary).
            try:
                cat_result = await session.execute(
                    _sa_select(CatalogueItemModel).where(
                        CatalogueItemModel.enterprise_id == enterprise_id,
                        CatalogueItemModel.is_active == True,  # noqa: E712
                    )
                )
                cat_items = cat_result.scalars().all()
                catalogue_lines = []
                for item in cat_items:
                    parts = [item.product_name, item.hsn_code, item.product_category]
                    if item.grade:
                        parts.append(item.grade)
                    if item.specification_text:
                        parts.append(item.specification_text[:200])
                    catalogue_lines.append(" | ".join(p for p in parts if p))
                if catalogue_lines:
                    text_parts.append(". ".join(catalogue_lines))
            except Exception:
                log.warning("seller_profile_catalogue_fetch_failed", enterprise_id=str(enterprise_id))

            text = " ".join(p for p in text_parts if p)
            if text.strip():
                try:
                    embedding = await parser.generate_embedding(text)
                    profile.embedding = embedding
                    await session.commit()
                    log.info(
                        "seller_profile_embedding_generated",
                        enterprise_id=str(enterprise_id),
                        catalogue_items=len(cat_items) if "cat_items" in dir() else 0,
                    )
                except Exception:
                    log.exception("seller_profile_embedding_failed", enterprise_id=str(enterprise_id))

    except Exception:
        log.exception(
            "handle_enterprise_registered_create_profile_failed",
            enterprise_id=str(enterprise_id),
        )


def register_phase_five_handlers(publisher: EventPublisher) -> None:
    """
    Register marketplace event handlers.

    Called in main.py lifespan AFTER register_phase_four_handlers().
    """
    publisher.subscribe("RFQConfirmed", handle_rfq_confirmed)
    publisher.subscribe("RFQParsed", handle_rfq_parsed_audit)
    publisher.subscribe("RFQMatched", handle_rfq_matched_audit)
    publisher.subscribe("EnterpriseRegistered", handle_enterprise_registered_create_profile)

    log.info(
        "phase_five_event_handlers_registered",
        handlers=[
            "RFQConfirmed->create_session",
            "RFQParsed->audit",
            "RFQMatched->audit",
            "EnterpriseRegistered->create_seller_profile",
        ],
    )

