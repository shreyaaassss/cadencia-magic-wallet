"""
Shared Algorand utility — lightweight algod client for x402 payment broadcasts.

context.md §3: algosdk usage ONLY in infrastructure layer.
This module provides a minimal algod client and broadcast_and_confirm() utility
used by the x402 payment middleware to submit and confirm Algorand transactions.

Separate from the settlement AlgorandGateway, which uses algokit-utils for escrow
contract interactions. This module uses py-algorand-sdk directly for simple
payment broadcasts.
"""

from __future__ import annotations

import asyncio
import base64
import os
from typing import Any

from src.shared.infrastructure.logging import get_logger

log = get_logger(__name__)


# ── algod client factory ──────────────────────────────────────────────────────


def _get_algod_address() -> str:
    return os.environ.get(
        "ALGORAND_ALGOD_ADDRESS", "https://testnet-api.algonode.cloud"
    )


def _get_algod_token() -> str:
    return os.environ.get(
        "ALGORAND_ALGOD_TOKEN",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )


def _build_algod_client() -> object:
    """Build a synchronous algod.AlgodClient from environment variables."""
    from algosdk.v2client import algod  # type: ignore[import-untyped]

    address = _get_algod_address()
    token = _get_algod_token()
    # AlgoNode public endpoints require an empty token, not the dev "aaa..." token
    headers = {"X-Algo-API-Token": token} if token and "a" * 5 not in token else {}
    return algod.AlgodClient(token, address, headers)


# ── broadcast_and_confirm ─────────────────────────────────────────────────────


async def broadcast_and_confirm(signed_txn_b64: str) -> dict[str, Any]:
    """
    Decode, submit, and confirm a base64-encoded signed Algorand transaction.

    The signed transaction must be msgpack-encoded (standard algosdk format).
    Waits up to 10 rounds (~40 seconds) for confirmation.

    Returns:
        dict with at minimum: "tx_id" (str), "confirmed_round" (int).
        Full pending transaction info dict from algod is also included.

    Raises:
        RuntimeError if broadcast fails, confirmation times out, or
        the transaction is rejected by the network.
    """
    from algosdk import transaction as algo_transaction  # type: ignore[import-untyped]

    # Validate base64 encoding upfront
    try:
        base64.b64decode(signed_txn_b64)
    except Exception as exc:
        raise RuntimeError(f"Failed to base64-decode signed transaction: {exc}") from exc

    client = _build_algod_client()
    loop = asyncio.get_event_loop()

    # Submit transaction — send_raw_transaction expects a base64 string
    # (it calls base64.b64decode internally), so pass the original string.
    try:
        tx_id: str = await loop.run_in_executor(
            None, client.send_raw_transaction, signed_txn_b64
        )
    except Exception as exc:
        log.warning("algorand_broadcast_failed", error=str(exc))
        raise RuntimeError(f"Algorand transaction broadcast failed: {exc}") from exc

    log.info("algorand_txn_submitted", tx_id=tx_id[:12] + "...")

    # Wait for confirmation (blocking call, runs in executor to avoid blocking async loop)
    try:
        result: dict[str, Any] = await loop.run_in_executor(
            None,
            lambda: algo_transaction.wait_for_confirmation(client, tx_id, 10),
        )
    except Exception as exc:
        log.warning("algorand_confirmation_failed", tx_id=tx_id[:12], error=str(exc))
        raise RuntimeError(
            f"Algorand transaction not confirmed within 10 rounds: {exc}"
        ) from exc

    confirmed_round = result.get("confirmed-round", 0)
    log.info("algorand_txn_confirmed", tx_id=tx_id[:12] + "...", round=confirmed_round)

    return {
        "tx_id": tx_id,
        "confirmed_round": confirmed_round,
        **result,
    }
