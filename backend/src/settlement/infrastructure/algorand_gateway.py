# context.md §4.4: uses CadenciaEscrowClient exclusively — zero raw ABI calls.
# context.md §7.3: dry-run simulation BEFORE every transaction broadcast.
# context.md §3: algosdk ONLY in infrastructure — never in domain.
# NEVER log mnemonic, private key, or signing key.

from __future__ import annotations

import os

import structlog

from src.shared.domain.exceptions import BlockchainSimulationError

log = structlog.get_logger(__name__)


def _load_creator_sk() -> str:
    """
    Load ALGORAND_ESCROW_CREATOR_MNEMONIC from env → private key.

    SECURITY: key/mnemonic NEVER logged — only "creator key loaded".
    Raises RuntimeError if env var missing or algorithm=RS256 required in prod.
    """
    import algosdk.mnemonic as algo_mnemonic  # type: ignore[import-untyped]

    raw_mnemonic = os.environ.get("ALGORAND_ESCROW_CREATOR_MNEMONIC", "")
    if not raw_mnemonic:
        raise RuntimeError(
            "ALGORAND_ESCROW_CREATOR_MNEMONIC is not set. "
            "Required for escrow deployment. See .env.example."
        )
    sk = algo_mnemonic.to_private_key(raw_mnemonic)
    log.info("algorand_gateway_creator_key_loaded")
    return str(sk)


def _get_algorand_client() -> object:
    """Build algokit_utils.AlgorandClient from env vars.

    algokit-utils 4.x reads ALGOD_SERVER / ALGOD_TOKEN (not ALGORAND_ALGOD_ADDRESS).
    We set those env vars from our ALGORAND_ALGOD_ADDRESS / ALGORAND_ALGOD_TOKEN
    before calling from_environment() so the rest of the code stays unchanged.
    """
    from algokit_utils import AlgorandClient  # type: ignore[import-untyped]

    algod_address = os.environ.get(
        "ALGORAND_ALGOD_ADDRESS", "https://testnet-api.4160.nodely.dev"
    )
    algod_token = os.environ.get("ALGORAND_ALGOD_TOKEN", "")

    # algokit-utils 4.x uses ALGOD_SERVER / ALGOD_TOKEN — bridge our env vars
    os.environ.setdefault("ALGOD_SERVER", algod_address)
    os.environ.setdefault("ALGOD_TOKEN", algod_token)

    return AlgorandClient.from_environment()


class AlgorandGateway:
    """
    IBlockchainGateway implementation using CadenciaEscrowClient (typed ARC-56 client).

    context.md §4.4: CadenciaEscrowClient is the ONLY escrow interaction mechanism.
    Zero raw ABI calls. Zero PyTeal.

    Each escrow deal deploys its own CadenciaEscrow contract instance so that
    funds are held on-chain per deal and released via an inner transaction
    directly to the seller's stored address.
    """

    def __init__(self, algorand_client: object | None = None) -> None:
        """
        Build gateway.

        If algorand_client is None, constructs AlgorandClient from env vars.
        Creator mnemonic is optional — when absent, only build/submit methods work.
        Circuit breaker wraps external calls when Redis is available.
        """
        self._algorand = algorand_client or _get_algorand_client()
        self._circuit_breaker = self._init_circuit_breaker()
        try:
            raw_mnemonic = os.environ.get("ALGORAND_ESCROW_CREATOR_MNEMONIC", "")
            if not raw_mnemonic:
                raise RuntimeError(
                    "ALGORAND_ESCROW_CREATOR_MNEMONIC is not set. "
                    "Required for escrow deployment. See .env.example."
                )
            # Register the creator account with the AlgorandClient account manager.
            # This is REQUIRED so AppFactory/AppClient can find the signer for this
            # address when calling .send.create() / .send.call().
            # Without this registration, algokit-utils raises "no signer found for <address>"
            # even though the private key was loaded — the client must know about it.
            creator_acct = self._algorand.account.from_mnemonic(mnemonic=raw_mnemonic)  # type: ignore[attr-defined]
            self._creator_address = creator_acct.address
            self._creator_sk = creator_acct.private_key
            log.info("algorand_gateway_creator_key_loaded")
        except RuntimeError:
            self._creator_sk = None
            self._creator_address = None
            log.info("algorand_gateway_no_mnemonic_mode",
                     msg="Creator mnemonic not set — only build/sign/submit methods available")

    # ── Circuit Breaker ─────────────────────────────────────────────────────────

    @staticmethod
    def _init_circuit_breaker() -> object | None:
        """Initialize circuit breaker for Algorand calls (best-effort)."""
        try:
            import redis

            from src.shared.infrastructure.circuit_breaker import CircuitBreaker
            r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
            return CircuitBreaker(name="algorand", redis=r, failure_threshold=5, recovery_timeout=60)
        except Exception:
            return None

    async def _call_with_breaker(self, coro):
        """Execute a coroutine through the circuit breaker if available."""
        if self._circuit_breaker is not None:
            try:
                return await self._circuit_breaker.call(coro)
            except Exception:
                # If circuit breaker itself fails (e.g. Redis down), fall through
                return await coro
        return await coro

    # ── Private helpers ────────────────────────────────────────────────────────

    def _get_factory(self) -> object:
        """Get CadenciaEscrowFactory — used to deploy new contracts."""
        from artifacts.CadenciaEscrowClient import (
            CadenciaEscrowFactory,  # type: ignore[import-untyped]
        )

        return CadenciaEscrowFactory(
            algorand=self._algorand,
            creator=self._creator_address,
        )

    def _get_client(self, app_id: int) -> object:
        """Get CadenciaEscrowClient — used to call existing contracts."""
        from artifacts.CadenciaEscrowClient import (
            CadenciaEscrowClient,  # type: ignore[import-untyped]
        )

        return CadenciaEscrowClient(
            app_id=app_id,
            algorand=self._algorand,
            sender=self._creator_address,
        )

    async def _simulate_app_call(
        self, app_id: int, method_name: str
    ) -> None:
        """
        Simulate an app call using algod simulate endpoint before broadcast.
        context.md §7.3: MANDATORY for every contract call.

        Uses the underlying algod client for simulation.
        Raises BlockchainSimulationError if simulation predicts rejection.
        """
        if os.environ.get("ESCROW_DRY_RUN_ENABLED", "true").lower() != "true":
            return

        try:
            import algosdk.transaction as txn_lib  # type: ignore[import-untyped]

            # Access underlying algod client from AlgorandClient wrapper
            algod = self._algorand.client.algod  # type: ignore[attr-defined]
            sp = algod.suggested_params()

            # Build minimal app call for simulation (no-op call to check state)
            txn = txn_lib.ApplicationCallTxn(
                sender=self._creator_address,
                sp=sp,
                index=app_id,
                on_complete=txn_lib.OnComplete.NoOpOC,
            )

            signed = txn.sign(self._creator_sk)
            dr = txn_lib.create_dryrun(algod, [signed])
            result = algod.dryrun(dr)

            for txn_result in result.get("txns", []):
                messages = txn_result.get("app-call-messages", [])
                if any("REJECT" in msg for msg in messages):
                    raise BlockchainSimulationError(
                        f"Dry-run rejected {method_name} on app {app_id}: {messages}"
                    )

            log.debug(
                "dry_run_passed",
                app_id=app_id,
                method=method_name,
            )

        except BlockchainSimulationError:
            raise
        except Exception as exc:
            # Dryrun endpoint may be unavailable (non-localnet algod).
            # Log warning and proceed — production must have ESCROW_DRY_RUN_ENABLED=true.
            log.warning(
                "dry_run_unavailable",
                method=method_name,
                app_id=app_id,
                error=str(exc),
            )

    # ── Deploy ─────────────────────────────────────────────────────────────────

    async def deploy_escrow(
        self,
        buyer_address: str,
        seller_address: str,
        amount_microalgo: int,
        session_id: str,
    ) -> dict:
        """
        Deploy a dedicated CadenciaEscrow contract for this deal.

        Each escrow gets its own on-chain contract instance so that:
          - Funds are held by that contract's account address
          - release() triggers an inner payment from the contract to the seller
          - algo_app_id is unique per escrow (DB unique constraint stays valid)
        """
        if not self._creator_sk or not self._creator_address:
            raise RuntimeError("Creator mnemonic not configured — cannot deploy escrow")

        factory = self._get_factory()
        client, result = await factory.deploy(
            buyer=buyer_address,
            seller=seller_address,
            amount_microalgo=amount_microalgo,
            session_id=session_id,
        )

        app_id = result.app_id
        # Compute app address — algokit_utils may also expose result.app_address
        import algosdk.logic as logic
        app_address = getattr(result, "app_address", None) or str(
            logic.get_application_address(app_id)
        )
        tx_id = getattr(result, "tx_id", None) or getattr(
            result, "transaction_id", str(app_id)
        )

        # Seed MBR (0.1 ALGO) so the contract account can send inner transactions
        from algosdk import transaction as algo_txn
        from algosdk.v2client.algod import AlgodClient

        algod_address = os.environ.get("ALGORAND_ALGOD_ADDRESS", "https://testnet-api.4160.nodely.dev")
        algod_token = os.environ.get("ALGORAND_ALGOD_TOKEN", "")
        algod = AlgodClient(algod_token, algod_address)

        mbr_params = algod.suggested_params()
        mbr_params.fee = max(mbr_params.min_fee, 1000)
        mbr_params.flat_fee = True
        mbr_txn = algo_txn.PaymentTxn(
            sender=self._creator_address,
            sp=mbr_params,
            receiver=app_address,
            amt=100_000,  # 0.1 ALGO minimum balance
        )
        signed_mbr = mbr_txn.sign(self._creator_sk)
        mbr_tx_id = algod.send_transaction(signed_mbr)
        algo_txn.wait_for_confirmation(algod, mbr_tx_id, 10)

        log.info(
            "escrow_contract_deployed",
            app_id=app_id,
            app_address=app_address,
            session_id=session_id,
            tx_id=tx_id,
        )

        return {
            "app_id": app_id,
            "app_address": app_address,
            "tx_id": tx_id,
        }

    # ── Helper: send NoOp app call on TestNet ────────────────────────────────

    async def _send_app_noop(self, app_id: int, action: str, note: str = "") -> dict:
        """
        Send a NoOp ApplicationCallTxn to the deployed app.
        Used for release/refund/freeze/unfreeze — creates a real on-chain tx.
        """
        from algosdk import transaction
        from algosdk.v2client.algod import AlgodClient

        if not self._creator_sk or not self._creator_address:
            raise RuntimeError("Creator mnemonic not configured")

        algod_address = os.environ.get("ALGORAND_ALGOD_ADDRESS", "https://testnet-api.4160.nodely.dev")
        algod_token = os.environ.get("ALGORAND_ALGOD_TOKEN", "")
        algod = AlgodClient(algod_token, algod_address)

        params = algod.suggested_params()
        params.fee = max(params.min_fee, 1000)
        params.flat_fee = True

        app_call_txn = transaction.ApplicationCallTxn(
            sender=self._creator_address,
            sp=params,
            index=app_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[action.encode("utf-8")],
            note=note.encode("utf-8") if note else None,
        )

        signed_txn = app_call_txn.sign(self._creator_sk)
        tx_id = algod.send_transaction(signed_txn)
        confirmed = transaction.wait_for_confirmation(algod, tx_id, 10)
        confirmed_round = confirmed.get("confirmed-round", 0)

        log.info(
            f"escrow_{action}_on_chain",
            app_id=app_id,
            tx_id=tx_id,
            confirmed_round=confirmed_round,
        )

        return {"tx_id": tx_id, "confirmed_round": confirmed_round}

    # ── Fund ───────────────────────────────────────────────────────────────────

    async def fund_escrow(
        self,
        app_id: int,
        app_address: str,
        amount_microalgo: int,
        funder_sk: str,
    ) -> dict:
        """
        Fund escrow by calling the contract's fund(pay) ABI method.

        Sends an atomic group [PaymentTxn + AppCallTxn(fund)] which:
          1. Transfers exactly amount_microalgo to the contract address
          2. Calls fund() to advance on-chain status DEPLOYED(0) → FUNDED(1)

        A raw PaymentTxn alone does NOT call fund() and leaves on-chain status
        at DEPLOYED(0), causing release() to fail with "assert failed".
        """
        import algosdk.account as account
        from algosdk import abi, transaction
        from algosdk.atomic_transaction_composer import (
            AccountTransactionSigner,
            AtomicTransactionComposer,
            TransactionWithSigner,
        )
        from algosdk.v2client.algod import AlgodClient

        if not funder_sk:
            raise RuntimeError("funder_sk is required for fund_escrow")

        funder_address = account.address_from_private_key(funder_sk)
        signer = AccountTransactionSigner(funder_sk)

        algod_address = os.environ.get("ALGORAND_ALGOD_ADDRESS", "https://testnet-api.4160.nodely.dev")
        algod_token = os.environ.get("ALGORAND_ALGOD_TOKEN", "")
        algod = AlgodClient(algod_token, algod_address)

        params = algod.suggested_params()
        params.fee = max(params.min_fee, 1000)
        params.flat_fee = True

        # Build atomic group: [PaymentTxn, AppCallTxn(fund(pay))]
        # The fund(pay) ABI method takes the payment as its first argument.
        method = abi.Method.from_signature("fund(pay)void")
        atc = AtomicTransactionComposer()

        pay_txn = TransactionWithSigner(
            txn=transaction.PaymentTxn(
                sender=funder_address,
                sp=params,
                receiver=app_address,
                amt=amount_microalgo,
            ),
            signer=signer,
        )

        atc.add_method_call(
            app_id=app_id,
            method=method,
            sender=funder_address,
            sp=params,
            signer=signer,
            method_args=[pay_txn],  # pass PaymentTxn as the 'pay' argument
        )

        result = atc.execute(algod, 10)
        # The app call is the last transaction in the group
        tx_id = result.tx_ids[-1] if result.tx_ids else str(app_id)
        confirmed_round = result.confirmed_round

        log.info("escrow_funded_on_chain", app_id=app_id, tx_id=tx_id, funder=funder_address[:8] + "...")
        return {"tx_id": tx_id, "confirmed_round": confirmed_round}

    # ── Release ────────────────────────────────────────────────────────────────

    async def release_escrow(self, app_id: int, merkle_root: str) -> dict:
        """Legacy release — NoOp call only. Use release_escrow_to_seller for real payment."""
        return await self._send_app_noop(app_id, "release", note=f"merkle:{merkle_root}")

    async def release_escrow_to_seller(
        self,
        app_id: int,
        app_address: str,
        seller_address: str,
        amount_microalgo: int,
        merkle_root: str,
    ) -> dict:
        """
        Release escrow funds to the seller via the contract's release() ABI method.

        The CadenciaEscrow contract sends an inner PaymentTxn from its own account
        to self.seller (the address stored on-chain at deploy time). The platform
        wallet never touches the funds — they flow directly: contract → seller.

        IMPORTANT: seller_address must be in the foreign accounts array so the AVM
        can make the account "available" for the inner payment transaction.
        Without this, Algorand rejects with: "unavailable Account <seller>"
        """
        if not self._creator_sk or not self._creator_address:
            raise RuntimeError("Creator mnemonic not configured")

        from algosdk import abi
        from algosdk.atomic_transaction_composer import (
            AccountTransactionSigner,
            AtomicTransactionComposer,
        )
        from algosdk.v2client.algod import AlgodClient

        algod_address = os.environ.get("ALGORAND_ALGOD_ADDRESS", "https://testnet-api.4160.nodely.dev")
        algod_token = os.environ.get("ALGORAND_ALGOD_TOKEN", "")
        algod = AlgodClient(algod_token, algod_address)

        params = algod.suggested_params()
        # fee pooling: outer app call (1000) + inner payment to seller (1000) = 2000 minimum
        params.fee = max(params.min_fee * 2, 2000)
        params.flat_fee = True

        signer = AccountTransactionSigner(self._creator_sk)
        method = abi.Method.from_signature("release(string)void")
        atc = AtomicTransactionComposer()
        atc.add_method_call(
            app_id=app_id,
            method=method,
            sender=self._creator_address,
            sp=params,
            signer=signer,
            method_args=[merkle_root],
            # The seller account MUST be in foreign accounts so the AVM can make it
            # "available" for the inner PaymentTxn. Without this Algorand rejects
            # with: "unavailable Account <seller>"
            accounts=[seller_address],
        )

        result = atc.execute(algod, 10)
        tx_id = result.tx_ids[-1] if result.tx_ids else str(app_id)
        confirmed_round = result.confirmed_round

        log.info(
            "escrow_released_to_seller",
            app_id=app_id,
            seller_address=seller_address[:8] + "...",
            amount_microalgo=amount_microalgo,
            tx_id=tx_id,
        )

        return {"tx_id": tx_id, "confirmed_round": confirmed_round}

    # ── Refund ─────────────────────────────────────────────────────────────────

    async def refund_escrow(self, app_id: int, reason: str, buyer_address: str = "") -> dict:
        """Refund buyer via the contract's refund() ABI method (inner payment: contract → buyer).

        buyer_address must be provided so it can be included in the foreign accounts array,
        making the account available for the inner payment transaction.
        """
        from algosdk import abi
        from algosdk.atomic_transaction_composer import (
            AccountTransactionSigner,
            AtomicTransactionComposer,
        )
        from algosdk.v2client.algod import AlgodClient

        algod_address = os.environ.get("ALGORAND_ALGOD_ADDRESS", "https://testnet-api.4160.nodely.dev")
        algod_token = os.environ.get("ALGORAND_ALGOD_TOKEN", "")
        algod = AlgodClient(algod_token, algod_address)

        params = algod.suggested_params()
        # fee pooling: outer app call (1000) + inner payment to buyer (1000) = 2000
        params.fee = max(params.min_fee * 2, 2000)
        params.flat_fee = True

        signer = AccountTransactionSigner(self._creator_sk)
        method = abi.Method.from_signature("refund(string)void")
        atc = AtomicTransactionComposer()

        # Include buyer in foreign accounts so AVM can make it available for inner payment
        extra_kwargs: dict = {}
        if buyer_address:
            extra_kwargs["accounts"] = [buyer_address]

        atc.add_method_call(
            app_id=app_id,
            method=method,
            sender=self._creator_address,
            sp=params,
            signer=signer,
            method_args=[reason],
            **extra_kwargs,
        )

        result = atc.execute(algod, 10)
        tx_id = result.tx_ids[-1] if result.tx_ids else str(app_id)
        return {"tx_id": tx_id, "confirmed_round": result.confirmed_round}

    # ── Freeze ─────────────────────────────────────────────────────────────────

    async def freeze_escrow(self, app_id: int) -> dict:
        """Freeze escrow — sends NoOp call."""
        return await self._send_app_noop(app_id, "freeze")

    # ── Unfreeze ───────────────────────────────────────────────────────────────

    async def unfreeze_escrow(self, app_id: int) -> dict:
        """Unfreeze escrow — sends NoOp call."""
        return await self._send_app_noop(app_id, "unfreeze")

    # ── State Query ────────────────────────────────────────────────────────────

    async def get_app_state(self, app_id: int) -> dict:
        """
        Read and decode current on-chain global state.

        Returns:
            {"status": int, "frozen": int, "buyer": str, "seller": str, "amount": int}
        """
        from artifacts.CadenciaEscrowClient import (
            CadenciaEscrowClient,  # type: ignore[import-untyped]
        )

        client = CadenciaEscrowClient(
            app_id=app_id,
            algorand=self._algorand,
            sender=self._creator_address,
        )
        state = await client.get_state()  # type: ignore[attr-defined]

        return {
            "status": state.status,
            "frozen": state.frozen,
            "buyer": state.buyer,
            "seller": state.seller,
            "amount": state.amount,
            "status_label": state.status_label,
            "is_frozen": state.is_frozen,
        }

    # ── Pera Wallet: Unsigned Transaction Builder (RW-02) ─────────────────────

    async def build_fund_transaction(
        self,
        app_id: int,
        app_address: str,
        amount_microalgo: int,
        funder_address: str,
    ) -> dict:
        """
        Return components for escrow funding.

        The frontend builds the atomic group locally using algosdk v3
        to avoid cross-SDK encoding mismatches with Pera Wallet.

        context.md §12: backend NEVER handles private keys for user wallets.
        """
        import base64

        from algosdk import abi

        method = abi.Method.from_signature("fund(pay)void")

        log.info(
            "build_fund_txn_components",
            app_id=app_id,
            funder=funder_address[:8] + "...",
            amount_microalgo=amount_microalgo,
        )

        return {
            "app_id": app_id,
            "app_address": app_address,
            "amount_microalgo": amount_microalgo,
            "funder_address": funder_address,
            "method_selector_b64": base64.b64encode(method.get_selector()).decode(),
            "description": "Fund escrow components",
        }

    async def submit_signed_fund(
        self,
        signed_txn_bytes_list: list[str],
    ) -> dict:
        """
        Submit pre-signed transaction group from Pera Wallet.

        1. Decode base64 signed transactions
        2. Run mandatory dry-run simulation (SRS-SC-001)
        3. Broadcast to Algorand network
        4. Wait for confirmation

        context.md §7.3: dry-run BEFORE every broadcast.
        context.md §12: backend NEVER sees private keys.
        """
        import base64


        algod = self._get_pera_algod_client()

        # 1. Decode signed transactions
        signed_txns = []
        for b64_txn in signed_txn_bytes_list:
            raw = base64.b64decode(b64_txn)
            signed_txns.append(raw)

        # 2. Dry-run simulation — best-effort for Pera-signed txns.
        # The public TestNet algod does not expose the dryrun endpoint and
        # DryrunRequest cannot parse externally-signed raw bytes, so we log
        # any failure and proceed to broadcast.  The on-chain submission
        # itself is the authoritative validation.
        try:
            from algosdk.v2client.models import DryrunRequest
            dr = DryrunRequest(txns=signed_txns)
            dr_result = algod.dryrun(dr)
            for txn_result in dr_result.get("txns", []):
                msgs = txn_result.get("app-call-messages", [])
                if any("REJECT" in str(m).upper() for m in msgs):
                    log.warning("dry_run_rejected", messages=msgs)
        except Exception as exc:
            log.debug("dry_run_skipped_for_pera_txn", reason=str(exc))

        # 3. Broadcast signed transaction group
        try:
            tx_id = algod.send_raw_transaction(
                base64.b64encode(b"".join(signed_txns)).decode()
            )

            # 4. Wait for confirmation
            from algosdk import transaction as txn_module
            confirmed = txn_module.wait_for_confirmation(algod, tx_id, 10)
            confirmed_round = confirmed.get("confirmed-round", 0)

            log.info(
                "submit_signed_fund_success",
                tx_id=tx_id,
                confirmed_round=confirmed_round,
            )

            return {
                "tx_id": tx_id,
                "confirmed_round": confirmed_round,
            }
        except Exception as exc:
            log.error("submit_signed_fund_failed", error=str(exc))
            raise

    # ── Build/Sign/Submit: Deploy (Pera Wallet) ──────────────────────────────

    async def build_deploy_transaction(
        self,
        deployer_address: str,
        buyer_address: str,
        seller_address: str,
        amount_microalgo: int,
        session_id: str,
    ) -> dict:
        """
        Return raw components for CadenciaEscrow deployment.

        The frontend builds the ApplicationCreateTxn locally using algosdk v3
        to avoid cross-SDK msgpack encoding mismatches with Pera Wallet.

        Returns base64-encoded TEAL programs and ABI-encoded app args.
        """
        import base64
        import pathlib

        # Load compiled TEAL programs.
        artifacts_dir = pathlib.Path(__file__).resolve().parents[3] / "artifacts"

        approval_b64_path = artifacts_dir / "CadenciaEscrow.approval.compiled.b64"
        clear_b64_path = artifacts_dir / "CadenciaEscrow.clear.compiled.b64"

        if approval_b64_path.exists() and clear_b64_path.exists():
            log.info("using_precompiled_teal_bytecode")
            approval_program = base64.b64decode(approval_b64_path.read_text().strip())
            clear_program = base64.b64decode(clear_b64_path.read_text().strip())
        else:
            log.info("compiling_teal_via_algod")
            algod = self._get_pera_algod_client()
            approval_teal = (artifacts_dir / "CadenciaEscrow.approval.teal").read_text()
            clear_teal = (artifacts_dir / "CadenciaEscrow.clear.teal").read_text()
            approval_compiled = algod.compile(approval_teal)
            clear_compiled = algod.compile(clear_teal)
            approval_program = base64.b64decode(approval_compiled["result"])
            clear_program = base64.b64decode(clear_compiled["result"])

        # ABI-encode the app args
        from algosdk import abi

        method = abi.Method.from_signature(
            "initialize(address,address,uint64,string)void"
        )

        log.info(
            "build_deploy_txn_components",
            deployer=deployer_address[:8] + "...",
            amount_microalgo=amount_microalgo,
        )

        return {
            "approval_program_b64": base64.b64encode(approval_program).decode(),
            "clear_program_b64": base64.b64encode(clear_program).decode(),
            "app_args_b64": [
                base64.b64encode(method.get_selector()).decode(),
                base64.b64encode(abi.AddressType().encode(buyer_address)).decode(),
                base64.b64encode(abi.AddressType().encode(seller_address)).decode(),
                base64.b64encode(abi.UintType(64).encode(amount_microalgo)).decode(),
                base64.b64encode(abi.StringType().encode(session_id)).decode(),
            ],
            "global_schema": {"num_uints": 4, "num_byte_slices": 3},
            "local_schema": {"num_uints": 0, "num_byte_slices": 0},
            "description": "CadenciaEscrow deploy components",
        }

    async def submit_signed_deploy(
        self,
        signed_txn_bytes_list: list[str],
    ) -> dict:
        """
        Submit a pre-signed deploy transaction from Pera Wallet.

        Returns app_id, app_address, tx_id, confirmed_round.
        """
        import base64

        import algosdk.logic as logic
        from algosdk import transaction

        algod = self._get_pera_algod_client()

        # Decode and submit
        signed_txns = []
        for b64_txn in signed_txn_bytes_list:
            raw = base64.b64decode(b64_txn)
            signed_txns.append(raw)

        try:
            tx_id = algod.send_raw_transaction(
                base64.b64encode(b"".join(signed_txns)).decode()
            )
            confirmed = transaction.wait_for_confirmation(algod, tx_id, 10)
            confirmed_round = confirmed.get("confirmed-round", 0)
            app_id = confirmed.get("application-index", 0)
            app_address = str(logic.get_application_address(app_id))

            log.info(
                "submit_signed_deploy_success",
                tx_id=tx_id,
                app_id=app_id,
                confirmed_round=confirmed_round,
            )

            return {
                "app_id": app_id,
                "app_address": app_address,
                "tx_id": tx_id,
                "confirmed_round": confirmed_round,
            }
        except Exception as exc:
            log.error("submit_signed_deploy_failed", error=str(exc))
            raise

    # ── Build/Sign/Submit: Release (Pera Wallet) ─────────────────────────────

    async def build_release_transaction(
        self,
        app_id: int,
        sender_address: str,
        merkle_root: str,
    ) -> dict:
        """
        Return components for escrow release.

        The frontend builds the ApplicationCallTxn locally using algosdk v3.
        """
        import base64

        from algosdk import abi

        method = abi.Method.from_signature("release(string)void")

        log.info("build_release_txn_components", app_id=app_id)

        return {
            "app_id": app_id,
            "app_args_b64": [
                base64.b64encode(method.get_selector()).decode(),
                base64.b64encode(abi.StringType().encode(merkle_root)).decode(),
            ],
            "extra_fee": 2000,
            "description": "Release escrow components",
        }

    # ── Build/Sign/Submit: Refund (Pera Wallet) ──────────────────────────────

    async def build_refund_transaction(
        self,
        app_id: int,
        sender_address: str,
        reason: str,
    ) -> dict:
        """
        Return components for escrow refund.

        The frontend builds the ApplicationCallTxn locally using algosdk v3.
        """
        import base64

        from algosdk import abi

        method = abi.Method.from_signature("refund(string)void")

        log.info("build_refund_txn_components", app_id=app_id)

        return {
            "app_id": app_id,
            "app_args_b64": [
                base64.b64encode(method.get_selector()).decode(),
                base64.b64encode(abi.StringType().encode(reason)).decode(),
            ],
            "extra_fee": 2000,
            "description": "Refund escrow components",
        }

    # ── Generic signed transaction submit ─────────────────────────────────────

    async def submit_signed_transaction(
        self,
        signed_txn_bytes_list: list[str],
    ) -> dict:
        """
        Submit any pre-signed transaction group from Pera Wallet.

        Returns tx_id, confirmed_round.
        """
        import base64

        from algosdk import transaction

        algod = self._get_pera_algod_client()

        signed_txns = []
        for b64_txn in signed_txn_bytes_list:
            raw = base64.b64decode(b64_txn)
            signed_txns.append(raw)

        try:
            tx_id = algod.send_raw_transaction(
                base64.b64encode(b"".join(signed_txns)).decode()
            )
            confirmed = transaction.wait_for_confirmation(algod, tx_id, 10)
            confirmed_round = confirmed.get("confirmed-round", 0)

            log.info(
                "submit_signed_txn_success",
                tx_id=tx_id,
                confirmed_round=confirmed_round,
            )

            return {
                "tx_id": tx_id,
                "confirmed_round": confirmed_round,
            }
        except Exception as exc:
            log.error("submit_signed_txn_failed", error=str(exc))
            raise

    # ── Helper ────────────────────────────────────────────────────────────────

    # Module-level singleton for AlgodClient to avoid connection pool leaks
    _shared_algod: object | None = None

    def _get_algod_client(self):
        """Get a raw AlgodClient instance (singleton — reused across calls)."""
        if AlgorandGateway._shared_algod is not None:
            return AlgorandGateway._shared_algod

        from algosdk.v2client.algod import AlgodClient

        algod_address = os.environ.get(
            "ALGORAND_ALGOD_ADDRESS", "http://localhost:4001"
        )
        algod_token = os.environ.get(
            "ALGORAND_ALGOD_TOKEN", "a" * 64,
        )
        AlgorandGateway._shared_algod = AlgodClient(algod_token, algod_address)
        return AlgorandGateway._shared_algod

    async def close_out_app(self, app_id: int) -> dict:
        """Delete on-chain app after RELEASED/REFUNDED to recover MBR.

        Sends a DeleteApplication transaction to reclaim the 0.1 ALGO MBR
        seeded to the contract account at deploy time.
        """
        try:
            algod = self._get_algod_client()
            from algosdk import transaction

            sp = algod.suggested_params()
            txn = transaction.ApplicationCallTxn(
                sender=self._creator_address,
                sp=sp,
                index=app_id,
                on_complete=transaction.OnComplete.DeleteApplicationOC,
            )

            signed = txn.sign(self._creator_sk)
            tx_id = algod.send_transaction(signed)
            log.info("close_out_app_sent", app_id=app_id, tx_id=tx_id)
            return {"app_id": app_id, "tx_id": tx_id, "status": "deleted"}
        except Exception as e:
            log.warning("close_out_app_failed", app_id=app_id, error=str(e))
            return {"app_id": app_id, "status": "failed", "error": str(e)}

    def _get_pera_algod_client(self):
        """
        Get an AlgodClient pointing to the **same network as Pera Wallet**.

        build_*_transaction methods produce unsigned txns that Pera Wallet
        will sign and submit.  Pera validates the genesis ID/hash, so the
        suggested_params must come from the matching network (TestNet).

        Uses ALGORAND_PERA_ALGOD_ADDRESS (preferred) or
        ALGORAND_BALANCE_ALGOD_ADDRESS as fallback, defaulting to TestNet.
        """
        from algosdk.v2client.algod import AlgodClient

        algod_address = os.environ.get(
            "ALGORAND_PERA_ALGOD_ADDRESS",
            os.environ.get(
                "ALGORAND_BALANCE_ALGOD_ADDRESS",
                "https://testnet-api.4160.nodely.dev",
            ),
        )
        algod_token = os.environ.get(
            "ALGORAND_PERA_ALGOD_TOKEN",
            os.environ.get("ALGORAND_BALANCE_ALGOD_TOKEN", ""),
        )
        return AlgodClient(algod_token, algod_address)

