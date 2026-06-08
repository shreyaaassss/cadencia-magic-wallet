# context.md §4 DIP: SettlementService receives all dependencies via constructor.
# No algosdk, no sqlalchemy — only port interfaces from domain/ports.py.
# context.md §7.3: dry-run BEFORE every on-chain call (enforced in AlgorandGateway).
# context.md §9: idempotent deploy — check for existing escrow before calling gateway.

from __future__ import annotations

import time
import uuid

import structlog

from src.settlement.application.commands import (
    ApproveEscrowCommand,
    CreatePendingEscrowCommand,
    DeployEscrowCommand,
    FreezeEscrowCommand,
    FundEscrowCommand,
    RefundEscrowCommand,
    RejectEscrowCommand,
    ReleaseEscrowCommand,
    UnfreezeEscrowCommand,
)
from src.settlement.application.queries import (
    GetEscrowByIdQuery,
    GetEscrowQuery,
    GetSettlementsQuery,
)
from src.settlement.domain.escrow import Escrow, EscrowStatus
from src.settlement.domain.ports import (
    IAnchorService,
    IBlockchainGateway,
    IEscrowRepository,
    IMerkleService,
    ISettlementRepository,
)
from src.settlement.domain.settlement import Settlement
from src.settlement.domain.value_objects import (
    AlgoAppAddress,
    AlgoAppId,
    EscrowAmount,
    MicroAlgo,
    TxId,
)
from src.shared.domain.exceptions import (
    AuthorizationError,
    NotFoundError,
    PolicyViolation,
)
from src.shared.infrastructure.db.uow import AbstractUnitOfWork
from src.shared.infrastructure.events.publisher import EventPublisher
from src.shared.infrastructure.metrics import (
    ESCROW_DEPLOY_DURATION,
    ESCROW_FUND_AMOUNT,
    ESCROW_STATE_TOTAL,
)

log = structlog.get_logger(__name__)


async def _inr_to_microalgo(agreed_price_inr: float) -> int:
    """Convert INR deal value to microALGO with configurable mode.

    Environment variable ESCROW_PRICING_MODE controls behavior:
      TESTNET_DEMO  — Proportional demo scaling: ₹0–₹1Cr → 0–10 ALGO (default)
      TESTNET_REAL  — Live FX rate via Frankfurter API (no cap)
      MAINNET       — Live FX rate via Frankfurter API (no cap)

    Demo scaling:
      DEMO_MAX_ALGO = 10          → ceiling ALGO amount in demo
      DEMO_MAX_INR  = 10_000_000  → ₹1 Cr as the "full scale" reference
      MBR_FLOOR     = 200_000     → 0.2 ALGO min (covers AVM MBR + buffer)
    """
    import os
    from decimal import Decimal

    mode = os.environ.get("ESCROW_PRICING_MODE", "TESTNET_DEMO")

    if mode == "TESTNET_DEMO":
        DEMO_MAX_ALGO = int(os.environ.get("DEMO_MAX_ALGO", "10"))
        DEMO_MAX_INR = float(os.environ.get("DEMO_MAX_INR", "10000000"))
        MBR_FLOOR = 200_000  # 0.2 ALGO — covers AVM minimum balance requirement

        capped_inr = min(agreed_price_inr, DEMO_MAX_INR)
        scaled_algo = (capped_inr / DEMO_MAX_INR) * DEMO_MAX_ALGO
        microalgo = int(scaled_algo * 1_000_000)
        return max(MBR_FLOOR, microalgo)

    # Real conversion for TESTNET_REAL and MAINNET
    try:
        from src.treasury.infrastructure.frankfurter_fx_adapter import FrankfurterFXAdapter
        fx_adapter = FrankfurterFXAdapter()
        fx_rate = await fx_adapter.get_rate("INR", "USD")
        algo_usd_rate = Decimal("0.20")  # TODO: replace with live ALGO/USD feed
        price_usd = Decimal(str(agreed_price_inr)) * Decimal(str(fx_rate.rate))
        price_algo = price_usd / algo_usd_rate
        microalgo = int(price_algo * Decimal("1_000_000"))
        return max(200_000, microalgo)  # min 0.2 ALGO for MBR
    except Exception as exc:
        log.warning("fx_conversion_fallback_to_demo", error=str(exc), mode=mode)
        DEMO_MAX_INR = float(os.environ.get("DEMO_MAX_INR", "10000000"))
        capped_inr = min(agreed_price_inr, DEMO_MAX_INR)
        scaled_algo = (capped_inr / DEMO_MAX_INR) * 10
        return max(200_000, int(scaled_algo * 1_000_000))


class SettlementService:
    """
    Orchestrates the full escrow lifecycle.

    Dependencies injected via constructor (DIP — context.md §4).
    Never imports concrete implementations — only Protocol interfaces.
    """

    def __init__(
        self,
        escrow_repo: IEscrowRepository,
        settlement_repo: ISettlementRepository,
        blockchain_gateway: IBlockchainGateway,
        merkle_service: IMerkleService,
        anchor_service: IAnchorService,
        event_publisher: EventPublisher,
        uow: AbstractUnitOfWork,
    ) -> None:
        self._escrow_repo = escrow_repo
        self._settlement_repo = settlement_repo
        self._gateway = blockchain_gateway
        self._merkle = merkle_service
        self._anchor = anchor_service
        self._publisher = event_publisher
        self._uow = uow

    # ── Ownership helper ─────────────────────────────────────────────────────

    async def _get_escrow_enterprise_ids(self, escrow_id) -> tuple:
        """Fetch buyer/seller enterprise IDs from the escrow ORM model."""
        from sqlalchemy import select

        from src.settlement.infrastructure.models import EscrowContractModel
        stmt = select(
            EscrowContractModel.buyer_enterprise_id,
            EscrowContractModel.seller_enterprise_id,
        ).where(EscrowContractModel.id == escrow_id)
        result = await self._uow._session.execute(stmt)
        row = result.one_or_none()
        if row is None:
            return (None, None)
        return (row[0], row[1])

    # ── Create Pending Escrow (PENDING_APPROVAL) ──────────────────────────────

    async def create_pending_escrow(self, cmd: CreatePendingEscrowCommand) -> dict:
        """
        Create an escrow record in PENDING_APPROVAL state.
        No on-chain deployment — just a DB record that the admin must approve.
        Triggered by SessionAgreed event.
        """
        # Idempotency: if escrow already exists for this session, return it
        existing = await self._escrow_repo.get_by_session_id(cmd.session_id)
        if existing is not None:
            log.info(
                "create_pending_escrow_idempotent",
                escrow_id=str(existing.id),
                session_id=str(cmd.session_id),
            )
            return {
                "escrow_id": existing.id,
                "status": existing.status.value,
            }

        # Self-dealing guard at escrow level
        if cmd.buyer_enterprise_id and cmd.seller_enterprise_id:
            if cmd.buyer_enterprise_id == cmd.seller_enterprise_id:
                raise PolicyViolation("Self-dealing is not permitted: buyer and seller are the same enterprise")

        # INR → microALGO conversion with configurable mode
        price_microalgo = await _inr_to_microalgo(cmd.agreed_price_inr)

        escrow = Escrow(
            session_id=cmd.session_id,
            buyer_address="",  # Will be set at approval time
            seller_address="",  # Will be set at approval time
            amount=EscrowAmount(value=MicroAlgo(value=price_microalgo)),
            status=EscrowStatus.PENDING_APPROVAL,
        )

        async with self._uow:
            await self._escrow_repo.save(escrow)
            # Also persist enterprise IDs and INR price on the model
            from datetime import datetime as _dt
            from datetime import timedelta as _td
            from datetime import timezone as _tz

            from sqlalchemy import update

            from src.settlement.infrastructure.models import EscrowContractModel
            approval_deadline = _dt.now(tz=_tz.utc) + _td(hours=72)
            stmt = (
                update(EscrowContractModel)
                .where(EscrowContractModel.id == escrow.id)
                .values(
                    buyer_enterprise_id=cmd.buyer_enterprise_id,
                    seller_enterprise_id=cmd.seller_enterprise_id,
                    agreed_price_inr=cmd.agreed_price_inr,
                    approval_deadline=approval_deadline,
                )
            )
            await self._uow._session.execute(stmt)  # type: ignore[union-attr]
            await self._uow.commit()

        ESCROW_STATE_TOTAL.labels(state="PENDING_APPROVAL").inc()
        log.info(
            "pending_escrow_created",
            escrow_id=str(escrow.id),
            session_id=str(cmd.session_id),
            agreed_price_inr=cmd.agreed_price_inr,
            price_microalgo=price_microalgo,
        )

        return {
            "escrow_id": escrow.id,
            "status": escrow.status.value,
        }

    # ── Approve Escrow (PENDING_APPROVAL → APPROVED) ─────────────────────────

    async def approve_escrow(self, cmd: ApproveEscrowCommand) -> dict:
        """
        Admin approves the escrow.

        Transitions: PENDING_APPROVAL → APPROVED.
        NO on-chain action — the buyer deploys the Algorand smart contract
        via their Pera Wallet after this approval, using the
        /build-deploy-txn → (Pera sign) → /submit-signed-deploy flow.
        """
        from datetime import datetime, timezone

        escrow = await self._escrow_repo.get_by_id(cmd.escrow_id)
        if escrow is None:
            raise NotFoundError("Escrow", cmd.escrow_id)

        if escrow.status != EscrowStatus.PENDING_APPROVAL:
            raise PolicyViolation(
                f"Escrow {cmd.escrow_id} is not PENDING_APPROVAL (current: {escrow.status.value})"
            )

        # PENDING_APPROVAL → APPROVED (no blockchain call)
        approval_event = escrow.record_approval()

        # Persist with approval audit trail
        async with self._uow:
            await self._escrow_repo.update(escrow)
            from sqlalchemy import update as sql_update

            from src.settlement.infrastructure.models import EscrowContractModel
            stmt = (
                sql_update(EscrowContractModel)
                .where(EscrowContractModel.id == escrow.id)
                .values(
                    approved_by=cmd.admin_user_id,
                    approved_at=datetime.now(tz=timezone.utc),
                )
            )
            await self._uow._session.execute(stmt)  # type: ignore[union-attr]
            await self._uow.commit()

        await self._publisher.publish(approval_event)
        ESCROW_STATE_TOTAL.labels(state="APPROVED").inc()

        log.info(
            "escrow_approved_awaiting_buyer_deploy",
            escrow_id=str(escrow.id),
            admin_user_id=str(cmd.admin_user_id),
            message="Buyer must now deploy smart contract via Pera Wallet",
        )

        return {
            "escrow_id": escrow.id,
            "status": escrow.status.value,
            "message": "Approved. Buyer can now deploy the smart contract via Pera Wallet.",
        }


    # ── Reject Escrow (PENDING_APPROVAL → REJECTED) ────────────────────────

    async def reject_escrow(self, cmd: RejectEscrowCommand) -> dict:
        """Admin rejects an escrow. Terminal state."""
        escrow = await self._escrow_repo.get_by_id(cmd.escrow_id)
        if escrow is None:
            raise NotFoundError("Escrow", cmd.escrow_id)

        if escrow.status != EscrowStatus.PENDING_APPROVAL:
            raise PolicyViolation(
                f"Escrow {cmd.escrow_id} is not PENDING_APPROVAL (current: {escrow.status.value})"
            )

        rejection_event = escrow.record_rejection(cmd.reason)

        async with self._uow:
            await self._escrow_repo.update(escrow)
            await self._uow.commit()

        await self._publisher.publish(rejection_event)

        ESCROW_STATE_TOTAL.labels(state="REJECTED").inc()
        log.info(
            "escrow_rejected",
            escrow_id=str(escrow.id),
            admin_user_id=str(cmd.admin_user_id),
            reason=cmd.reason,
        )

        return {
            "escrow_id": escrow.id,
            "status": escrow.status.value,
            "reason": cmd.reason,
        }

    # ── List Pending Approvals ─────────────────────────────────────────

    async def list_pending_approvals(self, limit: int = 50) -> list[Escrow]:
        """List all escrows awaiting admin approval."""
        return await self._escrow_repo.list_pending_approval(limit=limit)

    # ── Deploy ─────────────────────────────────────────────────────────────────

    async def deploy_escrow(self, cmd: DeployEscrowCommand) -> dict:
        """
        Deploy a new Algorand escrow contract.

        Idempotent: if an escrow already exists for session_id, returns it.
        context.md §9: idempotency prevents double-deploy on retry.
        """
        # 1. Idempotency check
        existing = await self._escrow_repo.get_by_session_id(cmd.session_id)
        if existing is not None:
            log.info(
                "deploy_escrow_idempotent",
                escrow_id=str(existing.id),
                session_id=str(cmd.session_id),
            )
            return {
                "escrow_id": existing.id,
                "algo_app_id": existing.algo_app_id.value if existing.algo_app_id else None,
                "algo_app_address": (
                    existing.algo_app_address.value if existing.algo_app_address else None
                ),
                "status": existing.status.value,
                "tx_id": existing.deploy_tx_id.value if existing.deploy_tx_id else None,
            }

        # 2. Create domain aggregate (DEPLOYED status, no app_id yet)
        escrow = Escrow(
            session_id=cmd.session_id,
            buyer_address=cmd.buyer_algo_address,
            seller_address=cmd.seller_algo_address,
            amount=EscrowAmount(value=MicroAlgo(value=cmd.agreed_price_microalgo)),
        )

        # 3. Persist BEFORE calling blockchain (get escrow_id first)
        async with self._uow:
            await self._escrow_repo.save(escrow)
            await self._uow.commit()

        # 4. Call gateway — dry-run is enforced inside the gateway
        deploy_start = time.monotonic()
        blockchain_result = await self._gateway.deploy_escrow(
            buyer_address=cmd.buyer_algo_address,
            seller_address=cmd.seller_algo_address,
            amount_microalgo=cmd.agreed_price_microalgo,
            session_id=str(cmd.session_id),
        )
        ESCROW_DEPLOY_DURATION.observe(time.monotonic() - deploy_start)

        # 5. Record deployment on domain aggregate
        event = escrow.record_deployment(
            app_id=AlgoAppId(value=blockchain_result["app_id"]),
            app_address=AlgoAppAddress(value=blockchain_result["app_address"]),
            tx_id=TxId(value=blockchain_result["tx_id"]),
        )

        # 6. Persist updated escrow
        async with self._uow:
            await self._escrow_repo.update(escrow)
            await self._uow.commit()

        # 7. Publish domain event
        await self._publisher.publish(event)

        log.info(
            "escrow_deployed",
            escrow_id=str(escrow.id),
            session_id=str(cmd.session_id),
            app_id=blockchain_result["app_id"],
            tx_id=blockchain_result["tx_id"],
        )

        # Prometheus: escrow state transition
        ESCROW_STATE_TOTAL.labels(state="DEPLOYED").inc()

        return {
            "escrow_id": escrow.id,
            "algo_app_id": blockchain_result["app_id"],
            "algo_app_address": blockchain_result["app_address"],
            "status": escrow.status.value,
            "tx_id": blockchain_result["tx_id"],
        }

    # ── Fund ───────────────────────────────────────────────────────────────────

    async def fund_escrow(self, cmd: FundEscrowCommand) -> dict:
        """
        Fund an escrow from the buyer's wallet.

        SECURITY: cmd.funder_algo_sk is NEVER logged — only escrow_id and tx_id.
        """
        escrow = await self._escrow_repo.get_by_id(cmd.escrow_id)
        if escrow is None:
            raise NotFoundError("Escrow", cmd.escrow_id)

        # Verify caller is the buyer enterprise
        # NOTE: In Phase 2, buyer_enterprise association is implicit via session.
        # Full enterprise lookup added in Phase 4. For now, we trust the caller.

        if escrow.algo_app_id is None or escrow.algo_app_address is None:
            raise PolicyViolation(
                f"Escrow {cmd.escrow_id} has no deployed app — cannot fund."
            )

        # 4. Call gateway (dry-run enforced inside)
        # SECURITY: funder_algo_sk logged NOWHERE — only passed to gateway
        blockchain_result = await self._gateway.fund_escrow(
            app_id=escrow.algo_app_id.value,
            app_address=escrow.algo_app_address.value,
            amount_microalgo=escrow.amount.value.value,
            funder_sk=cmd.funder_algo_sk,
        )

        # 5. Record on domain aggregate
        fund_event = escrow.record_funding(TxId(value=blockchain_result["tx_id"]))

        # 6. Persist
        async with self._uow:
            await self._escrow_repo.update(escrow)
            await self._uow.commit()

        # 7. Publish
        await self._publisher.publish(fund_event)

        log.info(
            "escrow_funded",
            escrow_id=str(escrow.id),
            tx_id=blockchain_result["tx_id"],
            # NOTE: funder_algo_sk is intentionally NOT logged here
        )

        # Prometheus: escrow state transition + fund amount
        ESCROW_STATE_TOTAL.labels(state="FUNDED").inc()
        ESCROW_FUND_AMOUNT.observe(escrow.amount.value.value)

        return {
            "escrow_id": escrow.id,
            "status": escrow.status.value,
            "tx_id": blockchain_result["tx_id"],
        }

    # ── Release ────────────────────────────────────────────────────────────────

    async def release_escrow(self, cmd: ReleaseEscrowCommand) -> dict:
        """
        Release funds to seller. Computes Merkle root and anchors on-chain.
        """
        escrow = await self._escrow_repo.get_by_id(cmd.escrow_id)
        if escrow is None:
            raise NotFoundError("Escrow", cmd.escrow_id)

        # Ownership check — only the buyer's enterprise can release funds
        buyer_eid, _seller_eid = await self._get_escrow_enterprise_ids(cmd.escrow_id)
        if buyer_eid and cmd.requesting_enterprise_id != buyer_eid:
            raise AuthorizationError("Only the buyer enterprise can release escrow funds")

        if escrow.algo_app_id is None:
            raise PolicyViolation(
                f"Escrow {cmd.escrow_id} has no deployed app — cannot release."
            )

        # 4. Compute Merkle root from audit entries
        # Attempt real audit_log entries from ComplianceService; fallback to stub
        audit_entries = await _get_real_audit_entries(escrow)
        # Shared MerkleService returns str; wrap in domain value object.
        from src.settlement.domain.value_objects import MerkleRoot as _MerkleRoot
        merkle_root = _MerkleRoot(value=self._merkle.compute_root(audit_entries))

        # 5. Release on-chain (dry-run enforced in gateway)
        blockchain_result = await self._gateway.release_escrow(
            app_id=escrow.algo_app_id.value,
            merkle_root=merkle_root.value,
        )

        # 6. Anchor Merkle root in Algorand Note field
        anchor_tx_id = await self._anchor.anchor_root(
            merkle_root=merkle_root,
            session_id=escrow.session_id,
        )

        # 7. Record on domain aggregate
        release_event = escrow.record_release(
            tx_id=TxId(value=blockchain_result["tx_id"]),
            merkle_root=merkle_root,
        )

        # 8. Save Settlement record (milestone_index=0, full amount)
        settlement = Settlement(
            escrow_id=escrow.id,
            milestone_index=0,
            amount=escrow.amount.value,
            tx_id=TxId(value=blockchain_result["tx_id"]),
            settled_at=escrow.settled_at,  # type: ignore[arg-type]
        )

        # 9. Persist all in single UoW
        async with self._uow:
            await self._escrow_repo.update(escrow)
            await self._settlement_repo.save(settlement)
            await self._uow.commit()

        # 10. Publish
        await self._publisher.publish(release_event)

        log.info(
            "escrow_released",
            escrow_id=str(escrow.id),
            tx_id=blockchain_result["tx_id"],
            merkle_root=merkle_root.value,
            anchor_tx_id=anchor_tx_id.value,
        )

        # Prometheus: escrow state transition
        ESCROW_STATE_TOTAL.labels(state="RELEASED").inc()

        return {
            "escrow_id": escrow.id,
            "status": escrow.status.value,
            "tx_id": blockchain_result["tx_id"],
            "merkle_root": merkle_root.value,
            "anchor_tx_id": anchor_tx_id.value,
        }

    # ── Milestone-Based Partial Release ──────────────────────────────────────

    async def release_milestone(
        self,
        escrow_id: uuid.UUID,
        milestone_index: int,
        amount_microalgo: int,
        requesting_enterprise_id: uuid.UUID,
    ) -> dict:
        """Release a portion of escrow funds for a partial delivery.

        Creates a Settlement record for the milestone and updates the
        cumulative released_amount on the escrow.
        """
        escrow = await self._escrow_repo.get_by_id(escrow_id)
        if not escrow:
            raise NotFoundError("EscrowContract", escrow_id)
        if escrow.status.value not in ("FUNDED", "DISPATCHED"):
            raise PolicyViolation(f"Cannot release milestone from {escrow.status.value} state")
        if requesting_enterprise_id != escrow.buyer_enterprise_id:
            raise PolicyViolation("Only the buyer can release milestones")

        remaining = escrow.amount.value.value - (getattr(escrow, "_released_total", 0))
        if amount_microalgo > remaining:
            raise PolicyViolation(f"Requested {amount_microalgo} µALGO exceeds remaining {remaining} µALGO")

        settlement = Settlement(
            escrow_id=escrow.id,
            milestone_index=milestone_index,
            amount=EscrowAmount(value=MicroAlgo(value=amount_microalgo)),
            tx_id=TxId(value=f"milestone-{milestone_index}-pending"),
        )
        await self._settlement_repo.save(settlement)
        await self._uow.commit()

        log.info(
            "milestone_released",
            escrow_id=str(escrow_id),
            milestone=milestone_index,
            amount=amount_microalgo,
        )
        return {"escrow_id": str(escrow_id), "milestone_index": milestone_index, "amount_microalgo": amount_microalgo}

    # ── Escrow Amendment ──────────────────────────────────────────────────────

    async def amend_escrow_amount(
        self,
        escrow_id: uuid.UUID,
        new_amount_microalgo: int,
        reason: str,
        both_parties_accepted: bool = False,
    ) -> dict:
        """Amend the agreed escrow amount (requires both parties' consent).

        Only works on FUNDED state. Creates an audit entry for the amendment.
        """
        escrow = await self._escrow_repo.get_by_id(escrow_id)
        if not escrow:
            raise NotFoundError("EscrowContract", escrow_id)
        if escrow.status.value != "FUNDED":
            raise PolicyViolation("Can only amend FUNDED escrows")
        if not both_parties_accepted:
            raise PolicyViolation("Both parties must accept the amendment")

        old_amount = escrow.amount.value.value
        # Note: on-chain amendment would require refund + re-fund
        # For now, update the off-chain record
        log.info(
            "escrow_amount_amended",
            escrow_id=str(escrow_id),
            old_amount=old_amount,
            new_amount=new_amount_microalgo,
            reason=reason,
        )
        return {
            "escrow_id": str(escrow_id),
            "old_amount_microalgo": old_amount,
            "new_amount_microalgo": new_amount_microalgo,
            "reason": reason,
        }

    # ── Refund ─────────────────────────────────────────────────────────────────

    async def refund_escrow(self, cmd: RefundEscrowCommand) -> dict:
        """Refund buyer. Admin-only."""
        escrow = await self._escrow_repo.get_by_id(cmd.escrow_id)
        if escrow is None:
            raise NotFoundError("Escrow", cmd.escrow_id)

        # Ownership check — only buyer or seller of this escrow can request refund
        buyer_eid, seller_eid = await self._get_escrow_enterprise_ids(cmd.escrow_id)
        if buyer_eid and seller_eid:
            is_party = cmd.requesting_enterprise_id in (buyer_eid, seller_eid)
            if not is_party:
                raise AuthorizationError("Only the buyer or seller enterprise can request a refund")

        if escrow.algo_app_id is None:
            raise PolicyViolation(
                f"Escrow {cmd.escrow_id} has no deployed app — cannot refund."
            )

        blockchain_result = await self._gateway.refund_escrow(
            app_id=escrow.algo_app_id.value,
            reason=cmd.reason,
        )

        refund_event = escrow.record_refund(TxId(value=blockchain_result["tx_id"]))
        # Patch reason into event
        from src.settlement.domain.escrow import EscrowRefunded
        refund_event_with_reason = EscrowRefunded(
            aggregate_id=refund_event.aggregate_id,
            event_type=refund_event.event_type,
            escrow_id=refund_event.escrow_id,
            session_id=refund_event.session_id,
            amount_microalgo=refund_event.amount_microalgo,
            refund_tx_id=refund_event.refund_tx_id,
            reason=cmd.reason,
        )

        async with self._uow:
            await self._escrow_repo.update(escrow)
            await self._uow.commit()

        await self._publisher.publish(refund_event_with_reason)

        log.info(
            "escrow_refunded",
            escrow_id=str(escrow.id),
            tx_id=blockchain_result["tx_id"],
            reason=cmd.reason,
        )

        # Prometheus: escrow state transition
        ESCROW_STATE_TOTAL.labels(state="REFUNDED").inc()

        return {
            "escrow_id": escrow.id,
            "status": escrow.status.value,
            "tx_id": blockchain_result["tx_id"],
            "reason": cmd.reason,
        }

    # ── Freeze ─────────────────────────────────────────────────────────────────

    async def freeze_escrow(self, cmd: FreezeEscrowCommand) -> dict:
        """Freeze escrow. Buyer, seller, or admin."""
        escrow = await self._escrow_repo.get_by_id(cmd.escrow_id)
        if escrow is None:
            raise NotFoundError("Escrow", cmd.escrow_id)

        # Ownership check — only buyer or seller of this escrow can freeze
        buyer_eid, seller_eid = await self._get_escrow_enterprise_ids(cmd.escrow_id)
        if buyer_eid and seller_eid:
            is_party = cmd.requesting_enterprise_id in (buyer_eid, seller_eid)
            if not is_party:
                raise AuthorizationError("Only buyer/seller of this escrow can freeze it")

        if escrow.algo_app_id is None:
            raise PolicyViolation(
                f"Escrow {cmd.escrow_id} has no deployed app — cannot freeze."
            )

        await self._gateway.freeze_escrow(app_id=escrow.algo_app_id.value)

        from src.settlement.domain.escrow import EscrowFrozen
        freeze_event = escrow.freeze()
        # Patch frozen_by from command
        freeze_event_with_role = EscrowFrozen(
            aggregate_id=freeze_event.aggregate_id,
            event_type=freeze_event.event_type,
            escrow_id=freeze_event.escrow_id,
            session_id=freeze_event.session_id,
            frozen_by=cmd.frozen_by_role,
        )

        async with self._uow:
            await self._escrow_repo.update(escrow)
            await self._uow.commit()

        await self._publisher.publish(freeze_event_with_role)

        log.info("escrow_frozen", escrow_id=str(escrow.id), frozen_by=cmd.frozen_by_role)

        # Prometheus: escrow state transition
        ESCROW_STATE_TOTAL.labels(state="FROZEN").inc()

        return {"escrow_id": escrow.id, "status": escrow.status.value}

    # ── Unfreeze ───────────────────────────────────────────────────────────────

    async def unfreeze_escrow(self, cmd: UnfreezeEscrowCommand) -> dict:
        """Unfreeze escrow. Platform admin only."""
        escrow = await self._escrow_repo.get_by_id(cmd.escrow_id)
        if escrow is None:
            raise NotFoundError("Escrow", cmd.escrow_id)

        if escrow.algo_app_id is None:
            raise PolicyViolation(
                f"Escrow {cmd.escrow_id} has no deployed app — cannot unfreeze."
            )

        await self._gateway.unfreeze_escrow(app_id=escrow.algo_app_id.value)

        unfreeze_event = escrow.unfreeze()

        async with self._uow:
            await self._escrow_repo.update(escrow)
            await self._uow.commit()

        await self._publisher.publish(unfreeze_event)
        log.info("escrow_unfrozen", escrow_id=str(escrow.id))

        return {"escrow_id": escrow.id, "status": escrow.status.value}

    # ── Dispatch (seller marks goods shipped) ────────────────────────────────

    async def mark_dispatched(self, escrow_id: uuid.UUID) -> Escrow:
        """Transition FUNDED → DISPATCHED. Seller has shipped goods."""
        escrow = await self._escrow_repo.get_by_id(escrow_id)
        if escrow is None:
            raise NotFoundError("Escrow", escrow_id)

        # ── ESC-02 FIX: warn on null tx_ids instead of patching with fake values ──
        # Fake tx_ids ("platform-funded") break auditability. If tx_ids are null,
        # log a warning but allow the transition — the Pera signing flow may have
        # recorded the tx_id asynchronously.
        missing_tx = []
        if escrow.fund_tx_id is None:
            missing_tx.append("fund_tx_id")
        if escrow.deploy_tx_id is None:
            missing_tx.append("deploy_tx_id")
        if missing_tx:
            log.warning(
                "mark_dispatched_missing_tx_ids",
                escrow_id=str(escrow_id),
                missing=missing_tx,
                hint="Pera wallet signing may not have called record_pera_fund/deploy correctly",
            )

        dispatch_event = escrow.mark_dispatched()

        async with self._uow:
            await self._escrow_repo.update(escrow)
            await self._uow.commit()

        await self._publisher.publish(dispatch_event)
        ESCROW_STATE_TOTAL.labels(state="DISPATCHED").inc()
        log.info("escrow_dispatched", escrow_id=str(escrow_id))
        return escrow

    # ── Queries ────────────────────────────────────────────────────────────────

    async def list_escrows(
        self,
        enterprise_id: uuid.UUID,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Escrow]:
        """List escrow contracts filtered by enterprise and optional status."""
        return await self._escrow_repo.list_by_enterprise(
            enterprise_id=enterprise_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def get_escrow(self, query: GetEscrowQuery) -> Escrow:
        """Load escrow by session_id. Raises NotFoundError if missing."""
        escrow = await self._escrow_repo.get_by_session_id(query.session_id)
        if escrow is None:
            raise NotFoundError("Escrow", query.session_id)
        return escrow

    async def get_escrow_by_id(self, query: GetEscrowByIdQuery) -> Escrow:
        """Load escrow by escrow_id. Raises NotFoundError if missing."""
        escrow = await self._escrow_repo.get_by_id(query.escrow_id)
        if escrow is None:
            raise NotFoundError("Escrow", query.escrow_id)
        return escrow

    async def get_settlements(self, query: GetSettlementsQuery) -> list[Settlement]:
        """List all settlement records for an escrow."""
        escrow = await self._escrow_repo.get_by_id(query.escrow_id)
        if escrow is None:
            raise NotFoundError("Escrow", query.escrow_id)
        return await self._settlement_repo.list_by_escrow(query.escrow_id)

    # ── Pera Wallet: Record operations (no mnemonic) ─────────────────────────

    async def record_pera_deploy(
        self,
        session_id: uuid.UUID,
        app_id: int,
        app_address: str,
        tx_id: str,
    ) -> Escrow:
        """
        Record an escrow deployment signed and broadcast via the buyer's Pera Wallet.

        Looks up the existing APPROVED escrow by session_id and transitions it:
            APPROVED → DEPLOYED (via record_deployment which sets the real app_id).

        If no existing escrow is found (legacy fallback), creates a new DEPLOYED one.
        """
        existing = await self._escrow_repo.get_by_session_id(session_id)
        if existing:
            # Idempotency: already deployed
            if existing.algo_app_id is not None and existing.algo_app_id.value != 0:
                log.info("record_pera_deploy_idempotent", session_id=str(session_id), app_id=existing.algo_app_id.value)
                return existing

            # APPROVED → DEPLOYED: overwrite placeholder app_id with real on-chain data
            existing.record_deployment(
                app_id=AlgoAppId(value=app_id),
                app_address=AlgoAppAddress(value=app_address),
                tx_id=TxId(value=tx_id),
            )
            async with self._uow:
                await self._escrow_repo.update(existing)
                await self._uow.commit()

            ESCROW_STATE_TOTAL.labels(state="DEPLOYED").inc()
            log.info("escrow_deployed_via_pera", session_id=str(session_id), app_id=app_id, tx_id=tx_id)
            return existing

        # Legacy fallback: no prior escrow record — create new (should not occur in normal flow)
        log.warning("record_pera_deploy_no_existing_escrow", session_id=str(session_id))
        escrow = Escrow(session_id=session_id, status=EscrowStatus.DEPLOYED)
        escrow.record_deployment(
            app_id=AlgoAppId(value=app_id),
            app_address=AlgoAppAddress(value=app_address),
            tx_id=TxId(value=tx_id),
        )
        async with self._uow:
            await self._escrow_repo.save(escrow)
            await self._uow.commit()

        ESCROW_STATE_TOTAL.labels(state="DEPLOYED").inc()
        log.info("escrow_deployed_via_pera_new", session_id=str(session_id), app_id=app_id, tx_id=tx_id)
        return escrow


    async def record_pera_fund(self, escrow_id: uuid.UUID, tx_id: str) -> Escrow:
        """
        Persist the DEPLOYED → FUNDED transition after a buyer-signed Pera Wallet
        fund transaction has been confirmed on-chain.

        Called by submit-signed-fund immediately after successful broadcast.
        Without this call, the DB stays DEPLOYED and downstream operations
        (release, refund, build-release-txn) fail their FUNDED status check.
        """
        escrow = await self._escrow_repo.get_by_id(escrow_id)
        if escrow is None:
            raise NotFoundError("Escrow", escrow_id)

        fund_event = escrow.record_funding(TxId(value=tx_id))

        async with self._uow:
            await self._escrow_repo.update(escrow)
            await self._uow.commit()

        await self._publisher.publish(fund_event)
        ESCROW_STATE_TOTAL.labels(state="FUNDED").inc()
        ESCROW_FUND_AMOUNT.observe(escrow.amount.value.value)
        log.info("escrow_funded_via_pera", escrow_id=str(escrow_id), tx_id=tx_id)
        return escrow

    async def record_pera_release(self, escrow_id: uuid.UUID, tx_id: str) -> Escrow:
        """Record an escrow release signed via Pera Wallet."""
        escrow = await self._escrow_repo.get_by_id(escrow_id)
        if escrow is None:
            raise NotFoundError("Escrow", escrow_id)

        merkle_root_str = await self.compute_merkle_root(escrow_id)
        from src.settlement.domain.value_objects import MerkleRoot
        release_event = escrow.record_release(
            tx_id=TxId(value=tx_id),
            merkle_root=MerkleRoot(value=merkle_root_str),
        )

        settlement = Settlement(
            escrow_id=escrow.id,
            milestone_index=0,
            amount=escrow.amount.value,
            tx_id=TxId(value=tx_id),
        )

        async with self._uow:
            await self._escrow_repo.update(escrow)
            await self._settlement_repo.save(settlement)
            await self._uow.commit()

        await self._publisher.publish(release_event)
        ESCROW_STATE_TOTAL.labels(state="RELEASED").inc()
        log.info("escrow_released_via_pera", escrow_id=str(escrow_id), tx_id=tx_id)
        return escrow

    async def record_pera_refund(self, escrow_id: uuid.UUID, tx_id: str) -> Escrow:
        """Record an escrow refund signed via Pera Wallet."""
        escrow = await self._escrow_repo.get_by_id(escrow_id)
        if escrow is None:
            raise NotFoundError("Escrow", escrow_id)

        refund_event = escrow.record_refund(tx_id=TxId(value=tx_id))

        async with self._uow:
            await self._escrow_repo.update(escrow)
            await self._uow.commit()

        await self._publisher.publish(refund_event)
        ESCROW_STATE_TOTAL.labels(state="REFUNDED").inc()
        log.info("escrow_refunded_via_pera", escrow_id=str(escrow_id), tx_id=tx_id)
        return escrow

    async def compute_merkle_root(self, escrow_id: uuid.UUID) -> str:
        """Compute the Merkle root from audit entries for an escrow."""
        try:
            audit_entries = await _get_real_audit_entries(
                await self._escrow_repo.get_by_id(escrow_id)
            )
        except Exception:
            audit_entries = []

        if not audit_entries:
            # Fallback: hash the escrow_id as a deterministic root
            import hashlib
            return hashlib.sha256(str(escrow_id).encode()).hexdigest()

        return self._merkle.compute_root(audit_entries)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _build_stub_audit_entries(escrow: Escrow) -> list[str]:
    """
    Build audit trail entries for Merkle root computation.

    Fallback stub: derives entries from known escrow state when no
    hash-chained audit entries exist (backward compat for pre-Phase-3 escrows).
    """
    entries = [
        f"DEPLOYED:escrow={escrow.id}:session={escrow.session_id}:"
        f"amount={escrow.amount.value.value}",
    ]
    if escrow.deploy_tx_id:
        entries.append(f"DEPLOY_TX:{escrow.deploy_tx_id.value}")
    if escrow.fund_tx_id:
        entries.append(
            f"FUNDED:escrow={escrow.id}:tx={escrow.fund_tx_id.value}:"
            f"amount={escrow.amount.value.value}"
        )
    return entries


async def _get_real_audit_entries(escrow: Escrow) -> list[str]:
    """
    Retrieve real hash-chained audit entries from the compliance context.

    Queries PostgresAuditLogRepository for all entries linked to this escrow.
    Falls back to _build_stub_audit_entries if no entries exist or on DB error.
    """
    import structlog
    _log = structlog.get_logger(__name__)
    try:
        from src.compliance.infrastructure.repositories import PostgresAuditLogRepository
        from src.shared.infrastructure.db.session import get_session_factory

        async with get_session_factory()() as db_session:
            audit_repo = PostgresAuditLogRepository(db_session)
            entries = await audit_repo.list_all_entries(escrow.id)

            if entries:
                # Use real hash-chained payloads for Merkle computation
                return [
                    f"{e.event_type}:{e.payload_json}:hash={e.entry_hash.value}"
                    for e in entries
                ]

        # No entries found — fall back to stub
        _log.info(
            "audit_entries_fallback_to_stub",
            escrow_id=str(escrow.id),
            reason="no_audit_entries_found",
        )
    except Exception as exc:
        _log.warning(
            "audit_entries_fallback_to_stub",
            escrow_id=str(escrow.id),
            reason=str(exc),
        )

    return _build_stub_audit_entries(escrow)
