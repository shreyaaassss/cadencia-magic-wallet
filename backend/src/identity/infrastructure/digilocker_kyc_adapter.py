# context.md §6: KYC Provider — HTTP REST integration.
# context.md §4 OCP: New KYC provider = new adapter file. Zero modification to IdentityService.
# SRS §14.3: DigiLocker eKYC flow with Aadhaar-based verification.
#
# This adapter integrates with the DigiLocker Partner API (v2) for
# government-backed identity verification using Aadhaar + PAN documents.

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from enum import Enum

import httpx

from src.shared.domain.exceptions import DomainError
from src.shared.infrastructure.logging import get_logger

log = get_logger(__name__)

# DigiLocker API base URLs
_SANDBOX_BASE = "https://api.sandbox.digitallocker.gov.in/public/oauth2/1"
_PRODUCTION_BASE = "https://api.digitallocker.gov.in/public/oauth2/1"

# Retry configuration
_MAX_RETRIES = 3
_RETRY_DELAYS = [1.0, 2.0, 4.0]

# Verification polling
_POLL_INTERVAL_SECONDS = 5
_POLL_MAX_ATTEMPTS = 24  # 2 minutes max polling


class KYCProviderError(DomainError):
    """Raised when the external KYC provider returns an error or is unreachable."""
    error_code = "KYC_PROVIDER_ERROR"


class DigilockerStatus(str, Enum):
    SUBMITTED = "submitted"
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    FAILED = "failed"


class DigilockerKYCAdapter:
    """
    DigiLocker eKYC adapter — implements IKYCAdapter Protocol.

    Uses DigiLocker Partner API for Aadhaar-based document verification.
    Supports both sandbox and production modes via APP_ENV.

    Required Environment Variables:
        KYC_PROVIDER_API_KEY:     DigiLocker partner client ID
        KYC_PROVIDER_API_SECRET:  DigiLocker partner client secret
        APP_ENV:                  'production' or 'development' (default)

    Flow:
        1. submit() → Initiates eKYC request with PAN + Aadhaar docs
        2. verify() → Polls DigiLocker for verification result
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str | None = None,
        sandbox: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret or os.environ.get("KYC_PROVIDER_API_SECRET", "")
        self._base_url = _SANDBOX_BASE if sandbox else _PRODUCTION_BASE
        self._timeout = timeout
        # In-memory cache of submission references (enterprise_id → reference_id)
        # In production, these would be persisted to the database.
        self._submissions: dict[str, dict] = {}
        self._circuit_open = False
        self._consecutive_failures = 0
        self._circuit_threshold = 5

    async def submit(
        self,
        enterprise_id: uuid.UUID,
        documents: dict,
    ) -> dict:
        """
        Submit KYC documents to DigiLocker for verification.

        Args:
            enterprise_id: UUID of the enterprise being verified.
            documents: Dict containing KYC document payload.
                Expected keys: 'pan', 'aadhaar_reference', 'full_name', 'dob'

        Returns:
            dict with 'status', 'reference_id', 'provider' keys.

        Raises:
            KYCProviderError: On API failure after retries.
        """
        if self._circuit_open:
            log.warning(
                "kyc_circuit_breaker_open",
                enterprise_id=str(enterprise_id),
            )
            raise KYCProviderError(
                "KYC provider circuit breaker is open — service temporarily unavailable"
            )

        pan = documents.get("pan", "")
        aadhaar_ref = documents.get("aadhaar_reference", "")
        full_name = documents.get("full_name", "")
        dob = documents.get("dob", "")

        if not pan:
            raise KYCProviderError("PAN number is required for KYC submission")

        # Build verification request payload
        payload = {
            "client_id": self._api_key,
            "doc_type": "PANCR",
            "id_number": pan,
            "full_name": full_name,
            "dob": dob,
            "consent": "Y",
            "consent_text": (
                "I hereby declare that I am voluntarily sharing my Aadhaar Number / "
                "Virtual ID and Demographic information with Cadencia for the sole "
                "purpose of identity verification as per KYC regulations."
            ),
        }

        if aadhaar_ref:
            payload["aadhaar_reference"] = aadhaar_ref

        last_error: Exception | None = None
        for attempt, delay in enumerate([0.0] + list(_RETRY_DELAYS)):
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        f"{self._base_url}/verify/ekycsubmit",
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                    )

                if response.status_code == 200:
                    data = response.json()
                    reference_id = data.get("reference_id", str(uuid.uuid4()))

                    # Cache submission
                    self._submissions[str(enterprise_id)] = {
                        "reference_id": reference_id,
                        "status": DigilockerStatus.SUBMITTED,
                        "submitted_at": datetime.now(tz=timezone.utc).isoformat(),
                        "pan": pan[:5] + "****" + pan[-1:],  # Masked PAN for logging
                    }

                    self._consecutive_failures = 0
                    log.info(
                        "kyc_digilocker_submitted",
                        enterprise_id=str(enterprise_id),
                        reference_id=reference_id,
                        masked_pan=pan[:5] + "****" + pan[-1:],
                    )
                    return {
                        "status": DigilockerStatus.SUBMITTED.value,
                        "reference_id": reference_id,
                        "provider": "digilocker",
                    }

                elif response.status_code == 429:
                    log.warning(
                        "kyc_digilocker_rate_limited",
                        enterprise_id=str(enterprise_id),
                        attempt=attempt,
                    )
                    last_error = KYCProviderError(
                        f"DigiLocker rate limit hit (attempt {attempt + 1})"
                    )
                else:
                    last_error = KYCProviderError(
                        f"DigiLocker API error: HTTP {response.status_code} — "
                        f"{response.text[:200]}"
                    )
                    log.error(
                        "kyc_digilocker_submit_error",
                        enterprise_id=str(enterprise_id),
                        status_code=response.status_code,
                        attempt=attempt,
                    )

            except httpx.TimeoutException as e:
                last_error = e
                log.warning(
                    "kyc_digilocker_timeout",
                    enterprise_id=str(enterprise_id),
                    attempt=attempt,
                )
            except httpx.ConnectError as e:
                last_error = e
                log.error(
                    "kyc_digilocker_connection_error",
                    enterprise_id=str(enterprise_id),
                    attempt=attempt,
                )
            except Exception as e:
                last_error = e
                log.error(
                    "kyc_digilocker_unexpected_error",
                    enterprise_id=str(enterprise_id),
                    error=str(e),
                    attempt=attempt,
                )

        # All retries exhausted
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._circuit_threshold:
            self._circuit_open = True
            log.error("kyc_circuit_breaker_tripped", failures=self._consecutive_failures)

        raise KYCProviderError(
            f"DigiLocker KYC submission failed after {_MAX_RETRIES + 1} attempts: {last_error}"
        ) from last_error

    async def verify(self, enterprise_id: uuid.UUID) -> bool:
        """
        Check DigiLocker verification status for an enterprise.

        Polls the DigiLocker status endpoint for the most recent submission.
        Returns True only if verification is explicitly VERIFIED.

        Returns:
            True if KYC is verified, False otherwise.
        """
        if self._circuit_open:
            log.warning(
                "kyc_circuit_breaker_open_verify",
                enterprise_id=str(enterprise_id),
            )
            return False

        submission = self._submissions.get(str(enterprise_id))
        if not submission:
            log.info(
                "kyc_no_submission_found",
                enterprise_id=str(enterprise_id),
            )
            return False

        reference_id = submission["reference_id"]

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{self._base_url}/verify/ekycstatus",
                    params={
                        "client_id": self._api_key,
                        "reference_id": reference_id,
                    },
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                    },
                )

            if response.status_code == 200:
                data = response.json()
                status_str = data.get("verification_status", "pending").lower()

                if status_str == "verified":
                    self._submissions[str(enterprise_id)]["status"] = (
                        DigilockerStatus.VERIFIED
                    )
                    log.info(
                        "kyc_digilocker_verified",
                        enterprise_id=str(enterprise_id),
                        reference_id=reference_id,
                    )
                    return True

                elif status_str == "rejected":
                    self._submissions[str(enterprise_id)]["status"] = (
                        DigilockerStatus.REJECTED
                    )
                    log.info(
                        "kyc_digilocker_rejected",
                        enterprise_id=str(enterprise_id),
                        reference_id=reference_id,
                        reason=data.get("rejection_reason", "unknown"),
                    )
                    return False

                else:
                    # Still pending
                    log.info(
                        "kyc_digilocker_pending",
                        enterprise_id=str(enterprise_id),
                        reference_id=reference_id,
                        status=status_str,
                    )
                    return False

            else:
                log.error(
                    "kyc_digilocker_verify_error",
                    enterprise_id=str(enterprise_id),
                    status_code=response.status_code,
                )
                return False

        except Exception as e:
            log.error(
                "kyc_digilocker_verify_exception",
                enterprise_id=str(enterprise_id),
                error=str(e),
            )
            return False

    def reset_circuit_breaker(self) -> None:
        """Manually reset the circuit breaker (admin action)."""
        self._circuit_open = False
        self._consecutive_failures = 0
        log.info("kyc_circuit_breaker_reset")
