"""Wallet ledger application service.

Records all ALGO movements (escrow fund/release/refund, x402 payments)
into the wallet_ledger table for off-chain auditability.
"""

from __future__ import annotations

import uuid

import structlog

log = structlog.get_logger(__name__)


class WalletLedgerService:
    """Records wallet events and provides transaction history."""

    def __init__(self, session: object) -> None:
        self._session = session

    async def record_event(
        self,
        enterprise_id: uuid.UUID,
        algorand_address: str,
        event_type: str,
        direction: str,
        amount_microalgo: int,
        tx_id: str | None = None,
        reference_id: uuid.UUID | None = None,
        reference_type: str | None = None,
    ) -> uuid.UUID:
        """Record a wallet ledger entry."""
        from src.wallet.models import WalletLedgerModel

        entry = WalletLedgerModel(
            id=uuid.uuid4(),
            enterprise_id=enterprise_id,
            algorand_address=algorand_address,
            event_type=event_type,
            direction=direction,
            amount_microalgo=amount_microalgo,
            tx_id=tx_id,
            reference_id=reference_id,
            reference_type=reference_type,
        )
        self._session.add(entry)
        await self._session.flush()
        log.info(
            "wallet_ledger_entry",
            enterprise_id=str(enterprise_id),
            event_type=event_type,
            direction=direction,
            amount=amount_microalgo,
        )
        return entry.id

    async def get_history(
        self,
        enterprise_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        """Get wallet transaction history for an enterprise.

        Aggregates from wallet_ledger + escrow_contracts + x402_payments.
        """
        from sqlalchemy import literal_column, select, union_all

        from src.settlement.infrastructure.models import EscrowContractModel
        from src.wallet.models import WalletLedgerModel

        # Source 1: wallet_ledger entries
        ledger_q = (
            select(
                WalletLedgerModel.id.label("id"),
                WalletLedgerModel.event_type.label("event_type"),
                WalletLedgerModel.direction.label("direction"),
                WalletLedgerModel.amount_microalgo.label("amount_microalgo"),
                WalletLedgerModel.tx_id.label("tx_id"),
                WalletLedgerModel.created_at.label("created_at"),
                literal_column("'LEDGER'").label("source"),
            )
            .where(WalletLedgerModel.enterprise_id == enterprise_id)
        )

        # Source 2: escrow contracts (fund/release/refund tx_ids)
        escrow_fund_q = (
            select(
                EscrowContractModel.id.label("id"),
                literal_column("'ESCROW_FUNDED'").label("event_type"),
                literal_column("'DEBIT'").label("direction"),
                EscrowContractModel.amount_microalgo.label("amount_microalgo"),
                EscrowContractModel.fund_tx_id.label("tx_id"),
                EscrowContractModel.created_at.label("created_at"),
                literal_column("'ESCROW'").label("source"),
            )
            .where(
                EscrowContractModel.buyer_enterprise_id == enterprise_id,
                EscrowContractModel.fund_tx_id != None,  # noqa: E711
            )
        )

        escrow_release_q = (
            select(
                EscrowContractModel.id.label("id"),
                literal_column("'ESCROW_RELEASED'").label("event_type"),
                literal_column("'CREDIT'").label("direction"),
                EscrowContractModel.amount_microalgo.label("amount_microalgo"),
                EscrowContractModel.release_tx_id.label("tx_id"),
                EscrowContractModel.created_at.label("created_at"),
                literal_column("'ESCROW'").label("source"),
            )
            .where(
                EscrowContractModel.seller_enterprise_id == enterprise_id,
                EscrowContractModel.release_tx_id != None,  # noqa: E711
            )
        )

        combined = union_all(ledger_q, escrow_fund_q, escrow_release_q).subquery()
        from sqlalchemy import select as sa_select
        final = (
            sa_select(combined)
            .order_by(combined.c.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        result = await self._session.execute(final)
        rows = result.fetchall()
        return [
            {
                "id": str(row.id),
                "event_type": row.event_type,
                "direction": row.direction,
                "amount_microalgo": row.amount_microalgo,
                "amount_algo": f"{row.amount_microalgo / 1_000_000:.6f}",
                "tx_id": row.tx_id,
                "created_at": str(row.created_at),
                "source": row.source,
            }
            for row in rows
        ]
