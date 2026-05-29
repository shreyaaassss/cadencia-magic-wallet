# context.md §4 — DIP: IdentityService receives ports, never concrete implementations.
# context.md §4 — SRP: orchestrates use cases only — no I/O, no formatting.

from __future__ import annotations

import secrets
import uuid

from src.shared.domain.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PolicyViolation,
    ValidationError,
)
from src.shared.infrastructure.db.uow import AbstractUnitOfWork
from src.shared.infrastructure.events.publisher import EventPublisher
from src.shared.infrastructure.logging import get_logger

from src.identity.domain.enterprise import Enterprise, TradeRole
from src.identity.domain.events import APIKeyCreated, APIKeyRevoked, EnterpriseRegistered
from src.identity.domain.ports import (
    IAPIKeyRepository,
    IEnterpriseRepository,
    IJWTService,
    IKYCAdapter,
    IUserRepository,
)
from src.identity.domain.user import User, UserRole
from src.identity.domain.value_objects import (
    Email,
    GSTIN,
    HashedAPIKey,
    HashedPassword,
    PAN,
)

from src.identity.application.commands import (
    CreateAPIKeyCommand,
    LoginCommand,
    RefreshTokenCommand,
    RegisterEnterpriseCommand,
    RevokeAPIKeyCommand,
    SubmitKYCCommand,
    UpdateAgentConfigCommand,
    VerifyKYCCommand,
)
from src.identity.application.queries import GetEnterpriseQuery, ListAPIKeysQuery

import os

log = get_logger(__name__)


class IdentityService:
    """
    Application service orchestrating all identity use cases.

    context.md §4 DIP: receives all port interfaces via constructor.
    FastAPI Depends() wires concrete adapters at request time.
    """

    def __init__(
        self,
        enterprise_repo: IEnterpriseRepository,
        user_repo: IUserRepository,
        api_key_repo: IAPIKeyRepository,
        jwt_service: IJWTService,
        kyc_adapter: IKYCAdapter,
        event_publisher: EventPublisher,
        uow: AbstractUnitOfWork,
    ) -> None:
        self._enterprises = enterprise_repo
        self._users = user_repo
        self._api_keys = api_key_repo
        self._jwt = jwt_service
        self._kyc = kyc_adapter
        self._publisher = event_publisher
        self._uow = uow

    # ── Registration ──────────────────────────────────────────────────────────

    async def register_enterprise(self, cmd: RegisterEnterpriseCommand) -> dict:
        """
        Create enterprise + admin user in a single UoW transaction.

        Returns access_token immediately on successful registration.
        Raises ConflictError on duplicate PAN or GSTIN.
        Raises ValidationError if PAN/GSTIN/Email format invalid.
        """
        # 1. Uniqueness checks
        existing_pan = await self._enterprises.get_by_pan(cmd.pan)
        if existing_pan is not None:
            raise ConflictError("An enterprise with this PAN is already registered.")

        existing_gstin = await self._enterprises.get_by_gstin(cmd.gstin)
        if existing_gstin is not None:
            raise ConflictError("An enterprise with this GSTIN is already registered.")

        existing_email = await self._users.get_by_email(cmd.email.strip().lower())
        if existing_email is not None:
            raise ConflictError("A user with this email address is already registered.")

        # 2. Build domain aggregates (value objects validate format on construction)
        enterprise = Enterprise(
            legal_name=cmd.legal_name,
            pan=PAN(value=cmd.pan),
            gstin=GSTIN(value=cmd.gstin),
            trade_role=TradeRole(cmd.trade_role),
            industry_vertical=cmd.industry_vertical,
            geography=cmd.geography,
            products_services=list(cmd.products_services),
        )

        if cmd.min_order_value is not None:
            enterprise.min_order_value = cmd.min_order_value
        if cmd.max_order_value is not None:
            enterprise.max_order_value = cmd.max_order_value
        if enterprise.min_order_value and enterprise.max_order_value:
            if enterprise.min_order_value > enterprise.max_order_value:
                raise ValidationError(
                    "min_order_value must be <= max_order_value.", field="min_order_value"
                )

        # Enhanced onboarding: business details
        if cmd.facility_type:
            enterprise.facility_type = cmd.facility_type
        if cmd.payment_terms_accepted:
            enterprise.payment_terms_accepted = list(cmd.payment_terms_accepted)
        if cmd.credit_period_days is not None:
            enterprise.credit_period_days = cmd.credit_period_days
        if cmd.years_in_operation is not None:
            enterprise.years_in_operation = cmd.years_in_operation
        if cmd.annual_turnover_inr is not None:
            enterprise.annual_turnover_inr = cmd.annual_turnover_inr
        if cmd.quality_certifications:
            enterprise.quality_certifications = list(cmd.quality_certifications)
        enterprise.test_certificate_available = cmd.test_certificate_available
        enterprise.third_party_inspection_allowed = cmd.third_party_inspection_allowed

        # Force MEMBER role regardless of what the client sends.
        # ADMIN is reserved for the backdoor admin login only.
        user = User(
            enterprise_id=enterprise.id,
            email=Email(value=cmd.email),
            password=HashedPassword.from_plaintext(cmd.password),
            full_name=cmd.full_name,
            role=UserRole.MEMBER,
        )

        # 3. Persist in single transaction
        async with self._uow:
            await self._enterprises.save(enterprise)
            await self._users.save(user)
            await self._uow.commit()

        # 3.1 Create address if provided (separate session — non-blocking)
        if cmd.address:
            import asyncio
            asyncio.create_task(
                self._create_address(enterprise.id, cmd.address)
            )

        # 4. Publish domain event
        event = EnterpriseRegistered(
            aggregate_id=enterprise.id,
            event_type="EnterpriseRegistered",
            enterprise_id=enterprise.id,
            legal_name=enterprise.legal_name,
            trade_role=enterprise.trade_role.value,
        )
        await self._publisher.publish(event)

        # 5. Issue access token immediately
        access_token = self._jwt.create_access_token(
            subject=str(user.id),
            enterprise_id=enterprise.id,
            role=user.role.value,
            trade_role=enterprise.trade_role.value,
        )
        refresh_token = self._jwt.create_refresh_token(subject=str(user.id))

        log.info(
            "enterprise_registered",
            enterprise_id=str(enterprise.id),
            user_id=str(user.id),
        )

        return {
            "enterprise_id": enterprise.id,
            "user_id": user.id,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        }

    async def _create_address(self, enterprise_id, address_data: dict) -> None:
        """Background: persist address with its own DB session."""
        import asyncio
        await asyncio.sleep(0.3)  # Wait for parent transaction commit
        from src.shared.infrastructure.db.session import get_session_factory
        from src.marketplace.infrastructure.models import AddressModel
        factory = get_session_factory()
        async with factory() as session:
            try:
                import uuid
                addr = AddressModel(
                    id=uuid.uuid4(),
                    enterprise_id=enterprise_id,
                    address_type=address_data.get("address_type", "FACILITY"),
                    address_line1=address_data["address_line1"],
                    address_line2=address_data.get("address_line2"),
                    city=address_data["city"],
                    state=address_data["state"],
                    pincode=address_data["pincode"],
                    latitude=address_data.get("latitude"),
                    longitude=address_data.get("longitude"),
                    is_primary=True,
                )
                session.add(addr)
                await session.commit()
                log.info("address_created", enterprise_id=str(enterprise_id))
            except Exception:
                log.exception("address_create_failed", enterprise_id=str(enterprise_id))

    # ── Admin Backdoor Login ────────────────────────────────────────────────

    async def admin_login(self, email: str, password: str) -> dict:
        """
        Authenticate using hardcoded admin credentials from environment variables.
        Returns a JWT with role=ADMIN and a platform-level enterprise_id.
        """
        admin_email = os.environ.get("CADENCIA_ADMIN_EMAIL", "")
        admin_password = os.environ.get("CADENCIA_ADMIN_PASSWORD", "")

        if not admin_email or not admin_password:
            raise PolicyViolation("Admin backdoor is not configured.")

        if email != admin_email or password != admin_password:
            raise AuthenticationError("Invalid admin credentials.")

        # Use a deterministic UUID for the platform admin enterprise
        import hashlib
        platform_enterprise_id = uuid.UUID(
            hashlib.md5(b"cadencia-platform-admin").hexdigest()
        )
        platform_user_id = uuid.UUID(
            hashlib.md5(b"cadencia-admin-user").hexdigest()
        )

        access_token = self._jwt.create_access_token(
            subject=str(platform_user_id),
            enterprise_id=platform_enterprise_id,
            role="ADMIN",
            trade_role="BOTH",
        )
        refresh_token = self._jwt.create_refresh_token(subject=str(platform_user_id))

        log.info("admin_backdoor_login")

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        }

    # ── Authentication ────────────────────────────────────────────────────────

    async def login(self, cmd: LoginCommand) -> dict:
        """
        Authenticate user by email/password.

        Returns both access and refresh tokens.
        Raises AuthenticationError if email not registered or password wrong.
        """
        user = await self._users.get_by_email(cmd.email.strip().lower())
        if user is None:
            raise AuthenticationError("Invalid email or password.")

        authenticated = user.authenticate(cmd.password)
        if not authenticated:
            raise AuthenticationError("Invalid email or password.")

        login_event = user.record_login()

        async with self._uow:
            await self._users.update(user)
            await self._uow.commit()

        await self._publisher.publish(login_event)

        # Retrieve enterprise for token claims
        enterprise = await self._enterprises.get_by_id(user.enterprise_id)
        enterprise_id = enterprise.id if enterprise else user.enterprise_id

        # Include trade_role in JWT claims for role-based route guards
        trade_role_value = None
        if enterprise:
            trade_role_value = enterprise.trade_role.value if hasattr(enterprise.trade_role, 'value') else str(enterprise.trade_role)

        access_token = self._jwt.create_access_token(
            subject=str(user.id),
            enterprise_id=enterprise_id,
            role=user.role.value,
            trade_role=trade_role_value,
        )
        refresh_token = self._jwt.create_refresh_token(subject=str(user.id))

        log.info("user_logged_in", user_id=str(user.id), enterprise_id=str(enterprise_id))

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        }

    async def refresh_token(self, cmd: RefreshTokenCommand) -> dict:
        """
        Issue a new access token from a valid refresh token.

        Raises ValidationError if refresh token is expired or invalid.
        """
        try:
            claims = self._jwt.decode_refresh_token(cmd.refresh_token)
        except Exception as exc:
            raise ValidationError(f"Invalid or expired refresh token: {exc}") from exc

        user_id = uuid.UUID(claims["sub"])
        user = await self._users.get_by_id(user_id)
        if user is None or not user.is_active:
            raise PolicyViolation("User account not found or inactive.")

        # Fetch enterprise to include trade_role in refreshed token
        enterprise = await self._enterprises.get_by_id(user.enterprise_id)
        trade_role_value = None
        if enterprise:
            trade_role_value = enterprise.trade_role.value if hasattr(enterprise.trade_role, 'value') else str(enterprise.trade_role)

        access_token = self._jwt.create_access_token(
            subject=str(user.id),
            enterprise_id=user.enterprise_id,
            role=user.role.value,
            trade_role=trade_role_value,
        )

        return {"access_token": access_token, "token_type": "bearer"}

    # ── KYC ───────────────────────────────────────────────────────────────────

    async def submit_kyc(self, cmd: SubmitKYCCommand) -> dict:
        """
        Submit KYC documents and advance enterprise to KYC_SUBMITTED.

        Only ADMIN users of the enterprise may call this.
        """
        enterprise = await self._enterprises.get_by_id(cmd.enterprise_id)
        if enterprise is None:
            raise NotFoundError("Enterprise", str(cmd.enterprise_id))

        user = await self._users.get_by_id(cmd.requesting_user_id)
        if user is None or user.enterprise_id != enterprise.id:
            raise PolicyViolation("Only ADMIN users of this enterprise can submit KYC.")
        if user.role not in (UserRole.ADMIN, UserRole.MEMBER):
            raise PolicyViolation("Only enterprise users can submit KYC.")

        # Call KYC adapter (mock in Phase One)
        kyc_result = await self._kyc.submit(enterprise.id, cmd.documents)

        kyc_event = enterprise.submit_kyc({**cmd.documents, **kyc_result})

        async with self._uow:
            await self._enterprises.update(enterprise)
            await self._uow.commit()

        await self._publisher.publish(kyc_event)

        log.info("kyc_submitted", enterprise_id=str(enterprise.id))

        return {
            "kyc_status": enterprise.kyc_status.value,
            "enterprise_id": str(enterprise.id),
        }

    async def verify_kyc(self, cmd: VerifyKYCCommand) -> dict:
        """
        Verify and activate enterprise KYC.

        Calls KYC adapter to confirm; advances VERIFIED → ACTIVE.
        """
        enterprise = await self._enterprises.get_by_id(cmd.enterprise_id)
        if enterprise is None:
            raise NotFoundError("Enterprise", str(cmd.enterprise_id))

        verified = await self._kyc.verify(enterprise.id)
        if not verified:
            raise PolicyViolation("KYC verification failed — provider returned not verified.")

        verified_event = enterprise.verify_kyc()
        activated_event = enterprise.activate()

        async with self._uow:
            await self._enterprises.update(enterprise)
            await self._uow.commit()

        await self._publisher.publish(verified_event)
        await self._publisher.publish(activated_event)

        log.info("kyc_verified_and_activated", enterprise_id=str(enterprise.id))

        return {"kyc_status": enterprise.kyc_status.value}

    # ── API Keys ──────────────────────────────────────────────────────────────

    async def create_api_key(self, cmd: CreateAPIKeyCommand) -> dict:
        """
        Generate, hash, and store a new API key.

        Returns raw_key ONCE — never retrievable again.
        context.md §14: plaintext never persisted or logged.
        """
        # Verify user belongs to this enterprise
        user = await self._users.get_by_id(cmd.requesting_user_id)
        if user is None or user.enterprise_id != cmd.enterprise_id:
            raise PolicyViolation("Cannot create API key for a different enterprise.")

        # Generate random raw key
        raw_key = secrets.token_urlsafe(32)
        key_id = uuid.uuid4()

        # Hash it — never store raw
        secret = os.environ.get("JWT_SECRET_KEY", "dev-secret-change-in-production")
        hashed = HashedAPIKey.from_raw(raw_key, secret)

        async with self._uow:
            await self._api_keys.save(
                key_hash=hashed.value,
                enterprise_id=cmd.enterprise_id,
                key_id=key_id,
                label=cmd.label,
            )
            await self._uow.commit()

        event = APIKeyCreated(
            aggregate_id=cmd.enterprise_id,
            event_type="APIKeyCreated",
            enterprise_id=cmd.enterprise_id,
            key_id=key_id,
        )
        await self._publisher.publish(event)

        log.info("api_key_created", enterprise_id=str(cmd.enterprise_id), key_id=str(key_id))

        return {
            "key_id": key_id,
            "raw_key": raw_key,   # Shown ONCE — caller must store it
            "label": cmd.label,
        }

    async def revoke_api_key(self, cmd: RevokeAPIKeyCommand) -> None:
        """Revoke an API key. Raises NotFoundError if key not found for enterprise."""
        user = await self._users.get_by_id(cmd.requesting_user_id)
        if user is None or user.enterprise_id != cmd.enterprise_id:
            raise PolicyViolation("Cannot revoke API key for a different enterprise.")

        async with self._uow:
            await self._api_keys.revoke(cmd.key_id, cmd.enterprise_id)
            await self._uow.commit()

        event = APIKeyRevoked(
            aggregate_id=cmd.enterprise_id,
            event_type="APIKeyRevoked",
            enterprise_id=cmd.enterprise_id,
            key_id=cmd.key_id,
        )
        await self._publisher.publish(event)

        log.info("api_key_revoked", key_id=str(cmd.key_id))

    # ── Enterprise ────────────────────────────────────────────────────────────

    async def magic_login(self, email: str, algo_address: str) -> dict:
        """
        Find an existing user by email and issue a Cadencia JWT.

        Called after the frontend has already verified the Magic DID token.
        Auto-links the Magic Algorand address to the enterprise if not yet linked.
        Raises AuthenticationError if the email is not registered.
        """
        from src.identity.domain.value_objects import AlgorandAddress

        user = await self._users.get_by_email(email.strip().lower())
        if user is None:
            raise AuthenticationError(
                "No account found for this email. Please complete registration first."
            )

        enterprise = await self._enterprises.get_by_id(user.enterprise_id)

        # Auto-link wallet if the enterprise has none yet
        if enterprise and not enterprise.algorand_wallet and algo_address:
            try:
                enterprise.link_algorand_wallet(AlgorandAddress(value=algo_address))
                async with self._uow:
                    await self._enterprises.update(enterprise)
                    await self._uow.commit()
                log.info(
                    "magic_wallet_auto_linked",
                    enterprise_id=str(enterprise.id),
                    address=algo_address[:8],
                )
            except Exception as exc:
                log.warning("magic_wallet_auto_link_failed", error=str(exc))

        enterprise_id = enterprise.id if enterprise else user.enterprise_id
        trade_role_value = None
        if enterprise:
            trade_role_value = (
                enterprise.trade_role.value
                if hasattr(enterprise.trade_role, "value")
                else str(enterprise.trade_role)
            )

        access_token = self._jwt.create_access_token(
            subject=str(user.id),
            enterprise_id=enterprise_id,
            role=user.role.value,
            trade_role=trade_role_value,
        )
        refresh_token = self._jwt.create_refresh_token(subject=str(user.id))

        log.info("magic_login_success", user_id=str(user.id), email=email)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user_id": user.id,
            "enterprise_id": enterprise_id,
        }

    async def web3_login(self, wallet_address: str) -> dict:
        """
        Find an existing user by their linked wallet address and issue a JWT.
        Used for Web3 login (Pera/Defly/Lute) after challenge-response verification.
        """
        enterprise = await self._enterprises.get_by_wallet_address(wallet_address)
        if enterprise is None:
            raise NotFoundError(
                "Enterprise", f"wallet:{wallet_address[:8]}..."
            )

        # Find any active user belonging to this enterprise
        users = await self._users.list_by_enterprise(enterprise.id)
        user = next((u for u in users if u.is_active), None)
        if user is None:
            raise AuthenticationError("No active user found for this enterprise.")

        trade_role_value = None
        if enterprise.trade_role:
            trade_role_value = (
                enterprise.trade_role.value
                if hasattr(enterprise.trade_role, "value")
                else str(enterprise.trade_role)
            )

        access_token = self._jwt.create_access_token(
            subject=str(user.id),
            enterprise_id=enterprise.id,
            role=user.role.value,
            trade_role=trade_role_value,
        )
        refresh_token = self._jwt.create_refresh_token(subject=str(user.id))

        log.info("web3_login_success", user_id=str(user.id), address=wallet_address[:8])

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user_id": user.id,
            "enterprise_id": enterprise.id,
        }

    async def get_enterprise(self, query: GetEnterpriseQuery) -> Enterprise:
        """
        Return enterprise profile.

        Blocks cross-enterprise access: user must belong to requested enterprise.
        """
        user = await self._users.get_by_id(query.requesting_user_id)
        if user is None:
            raise NotFoundError("User", str(query.requesting_user_id))

        if user.enterprise_id != query.enterprise_id:
            raise PolicyViolation(
                "Access denied: cannot read another enterprise's profile."
            )

        enterprise = await self._enterprises.get_by_id(query.enterprise_id)
        if enterprise is None:
            raise NotFoundError("Enterprise", str(query.enterprise_id))

        return enterprise

    async def update_agent_config(self, cmd: UpdateAgentConfigCommand) -> Enterprise:
        """
        Update agent configuration. ADMIN only.

        Two modes:
        - If cmd.config contains "__agent_config__", it stores the AI negotiation
          config (negotiation_style, max_rounds, etc.) in the agent_config JSONB column.
        - Otherwise, it updates enterprise-level fields (legacy flow).
        """
        enterprise = await self._enterprises.get_by_id(cmd.enterprise_id)
        if enterprise is None:
            raise NotFoundError("Enterprise", str(cmd.enterprise_id))

        user = await self._users.get_by_id(cmd.requesting_user_id)
        if user is None or user.enterprise_id != enterprise.id:
            raise PolicyViolation("Cannot update config for a different enterprise.")
        if user.role not in (UserRole.ADMIN, UserRole.MEMBER):
            raise PolicyViolation("Only enterprise users can update agent config.")

        if "__agent_config__" in cmd.config:
            # New flow: store AI agent config in dedicated JSONB column
            enterprise.agent_config = cmd.config["__agent_config__"]
            enterprise.touch()
        else:
            # Legacy flow: update enterprise-level fields
            config = {k: v for k, v in cmd.config.items() if k != "algorand_wallet"}
            enterprise.update_agent_config(config)

        async with self._uow:
            await self._enterprises.update(enterprise)
            await self._uow.commit()

        return enterprise

    async def link_wallet(self, cmd: "LinkWalletCommand") -> Enterprise:
        """
        Link an Algorand wallet address to an enterprise.

        Uses the domain method Enterprise.link_algorand_wallet() which raises
        ConflictError if a wallet is already linked.
        """
        from src.identity.application.commands import LinkWalletCommand
        from src.identity.domain.value_objects import AlgorandAddress

        enterprise = await self._enterprises.get_by_id(cmd.enterprise_id)
        if enterprise is None:
            raise NotFoundError("Enterprise", str(cmd.enterprise_id))

        user = await self._users.get_by_id(cmd.requesting_user_id)
        if user is None or user.enterprise_id != enterprise.id:
            raise PolicyViolation("Cannot link wallet for a different enterprise.")
        if user.role not in (UserRole.ADMIN, UserRole.MEMBER, UserRole.BUYER, UserRole.SELLER):
            raise PolicyViolation("Only enterprise users can link wallets.")

        # Domain method validates and raises ConflictError if already linked
        enterprise.link_algorand_wallet(AlgorandAddress(value=cmd.algorand_address))

        async with self._uow:
            await self._enterprises.update(enterprise)
            await self._uow.commit()

        log.info(
            "wallet_linked",
            enterprise_id=str(enterprise.id),
            # Never log the full address — only prefix for debugging
            address_prefix=cmd.algorand_address[:8] + "...",
        )
        return enterprise

    async def unlink_wallet(self, cmd: "UnlinkWalletCommand") -> Enterprise:
        """
        Unlink the Algorand wallet from an enterprise.

        Uses Enterprise.unlink_algorand_wallet() which clears the address.
        """
        from src.identity.application.commands import UnlinkWalletCommand

        enterprise = await self._enterprises.get_by_id(cmd.enterprise_id)
        if enterprise is None:
            raise NotFoundError("Enterprise", str(cmd.enterprise_id))

        user = await self._users.get_by_id(cmd.requesting_user_id)
        if user is None or user.enterprise_id != enterprise.id:
            raise PolicyViolation("Cannot unlink wallet for a different enterprise.")
        if user.role not in (UserRole.ADMIN, UserRole.MEMBER, UserRole.BUYER, UserRole.SELLER):
            raise PolicyViolation("Only enterprise users can unlink wallets.")

        if not enterprise.algorand_wallet:
            raise ConflictError("No wallet is currently linked.")

        enterprise.unlink_algorand_wallet()

        async with self._uow:
            await self._enterprises.update(enterprise)
            await self._uow.commit()

        log.info("wallet_unlinked", enterprise_id=str(enterprise.id))
        return enterprise

    async def list_api_keys(self, query: ListAPIKeysQuery) -> list[dict]:
        """List API keys for an enterprise (metadata only — no hashes returned)."""
        user = await self._users.get_by_id(query.requesting_user_id)
        if user is None or user.enterprise_id != query.enterprise_id:
            raise PolicyViolation("Cannot list API keys for a different enterprise.")

        return await self._api_keys.list_by_enterprise(query.enterprise_id)
