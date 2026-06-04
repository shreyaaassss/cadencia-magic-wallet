"""
NormalizationService — three pipelines converging heterogeneous data into NegotiationRecord.

Pipeline 1: Platform Session → NegotiationRecord (pure math + light LLM summary)
Pipeline 2: Historical Documents → NegotiationRecord(s) (full LLM extraction)
Pipeline 3: Agent Conversations → NegotiationRecord (structured capture)

LLM used for normalization: llama-3.3-70b-versatile via Groq
  - Isolated AsyncOpenAI client on GROQ_API_KEY_MEMORY (fallback to GROQ_API_KEY)
  - Runs as background task — never competes with live negotiation turns

context.md §3: application layer — orchestration only, no domain logic.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog

from src.negotiation.domain.negotiation_record import (
    SESSION_STATUS_TO_OUTCOME,
    NegotiationOutcome,
    NegotiationRecord,
    RecordType,
)

if TYPE_CHECKING:
    from src.negotiation.domain.session import NegotiationSession

log = structlog.get_logger(__name__)

_THREE_YEARS = timedelta(days=3 * 365)

# ── LLM Client (isolated budget for normalization) ────────────────────────────


def _get_normalization_client():
    """
    Returns a Groq-backed AsyncOpenAI client for normalization.

    Uses GROQ_API_KEY_MEMORY if available; falls back to GROQ_API_KEY.
    Isolated from the live negotiation driver's rate-limit budget.
    """
    try:
        from openai import AsyncOpenAI

        api_key = (
            os.environ.get("GROQ_API_KEY_MEMORY", "").strip()
            or os.environ.get("GROQ_API_KEY", "").strip()
        )
        if not api_key:
            return None
        return AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
    except Exception:
        return None


_NORMALIZATION_MODEL = "llama-3.3-70b-versatile"


async def _llm_call(prompt: str, system: str = "", max_tokens: int = 1024) -> str | None:
    """Single LLM call for normalization tasks. Returns raw text or None on failure."""
    client = _get_normalization_client()
    if client is None:
        return None
    try:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = await client.chat.completions.create(
            model=_NORMALIZATION_MODEL,
            messages=messages,  # type: ignore[arg-type]
            temperature=0.0,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content
    except Exception as exc:
        log.warning("normalization_llm_call_failed", error=str(exc))
        return None


# ── Retention Policy ──────────────────────────────────────────────────────────


def _compute_retention(outcome: NegotiationOutcome, record_type: RecordType) -> datetime | None:
    """
    Tiered retention:
    - AGREED platform records → None (never auto-expires)
    - HISTORICAL_IMPORT → None (user-provided, user must purge)
    - Non-agreed platform records → NOW() + 3 years
    """
    if record_type == RecordType.HISTORICAL_IMPORT:
        return None
    if outcome == NegotiationOutcome.AGREED:
        return None
    return datetime.now(tz=timezone.utc) + _THREE_YEARS


# ── Pipeline 1: Platform Session → NegotiationRecord ─────────────────────────


class NormalizationService:
    """
    Three normalization pipelines converging into NegotiationRecord.

    Instantiated with an optional embedding service for vector generation.
    """

    def __init__(self, embedding_service=None) -> None:
        self._embedding_service = embedding_service

    async def normalize_platform_session(
        self,
        session: "NegotiationSession",
        enterprise_id: uuid.UUID,
        enterprise_role: str,
        rfq_parsed_fields: dict | None = None,
        outcome_override: str | None = None,
    ) -> NegotiationRecord:
        """
        Convert a completed platform NegotiationSession into a canonical NegotiationRecord.

        Pure math extraction — no LLM needed for behavioral metrics.
        LLM used only for generating the conversation_summary (optional, non-fatal).

        outcome_override: pass explicit outcome string when session may not yet be
        committed to DB (event fires before uow.commit() — race condition avoidance).
        """
        transcript = getattr(session, "conversation_transcript", None) or {}
        rfq = rfq_parsed_fields or {}

        # ── Outcome mapping ──
        # Prefer explicit override (avoids race condition where event fires before commit)
        if outcome_override:
            outcome = SESSION_STATUS_TO_OUTCOME.get(outcome_override, NegotiationOutcome.UNKNOWN)
        else:
            status_val = session.status.value if hasattr(session.status, "value") else str(session.status)
            outcome = SESSION_STATUS_TO_OUTCOME.get(status_val, NegotiationOutcome.UNKNOWN)

        # ── Price extraction ──
        agreed_price = None
        if session.agreed_price is not None:
            agreed_price = Decimal(str(session.agreed_price.amount))

        # ── Offer sequence from transcript ──
        rounds_data = transcript.get("rounds", [])
        offer_sequence = [
            {
                "round": r.get("round"),
                "role": r.get("role"),
                "price": r.get("price"),
                "reasoning": r.get("reasoning", "")[:500],
                "confidence": r.get("confidence"),
                "is_human": r.get("is_human", False),
            }
            for r in rounds_data
        ]

        # ── Behavioral metrics (from intelligence service logic) ──
        buyer_prices = [r["price"] for r in rounds_data if r.get("role") == "buyer" and r.get("price")]
        seller_prices = [r["price"] for r in rounds_data if r.get("role") == "seller" and r.get("price")]

        buyer_avg_concession_pct = _avg_concession(buyer_prices)
        seller_avg_concession_pct = _avg_concession(seller_prices)

        buyer_style = _classify_style(buyer_prices, ascending=True)
        seller_style = _classify_style(seller_prices, ascending=False)

        initial_bid = Decimal(str(buyer_prices[0])) if buyer_prices else None
        initial_ask = Decimal(str(seller_prices[0])) if seller_prices else None

        final_discount_pct = None
        if initial_ask and agreed_price and initial_ask > 0:
            final_discount_pct = ((initial_ask - agreed_price) / initial_ask * 100).quantize(
                Decimal("0.01")
            )

        # ── Duration ──
        duration_hours = None
        try:
            if hasattr(session, "created_at") and session.created_at and session.completed_at:
                from datetime import datetime as _dt

                created = session.created_at
                completed = session.completed_at
                if isinstance(created, str):
                    created = _dt.fromisoformat(created.replace("Z", "+00:00"))
                if isinstance(completed, str):
                    completed = _dt.fromisoformat(completed.replace("Z", "+00:00"))
                delta = completed - created
                duration_hours = Decimal(str(round(delta.total_seconds() / 3600, 2)))
        except Exception:
            pass

        # ── Deal quality ──
        deal_quality_score = None
        dq = getattr(session, "deal_quality_score", None) or {}
        if isinstance(dq, dict):
            score = dq.get("score")
            if score is not None:
                deal_quality_score = Decimal(str(round(float(score), 4)))
        elif isinstance(dq, (int, float)):
            deal_quality_score = Decimal(str(round(float(dq), 4)))

        # ── Product context from RFQ ──
        product_name = rfq.get("product_name") or rfq.get("item_name")
        product_category = rfq.get("product_category")
        hsn_code = rfq.get("hsn_code")
        industry_vertical = rfq.get("industry_vertical")
        quantity = Decimal(str(rfq["quantity"])) if rfq.get("quantity") else None
        quantity_unit = rfq.get("unit") or rfq.get("quantity_unit")

        # ── Agreed terms ──
        agreed_terms = getattr(session, "agreed_terms", None) or {}
        payment_terms = agreed_terms.get("payment_terms") if isinstance(agreed_terms, dict) else None
        delivery_window_days = agreed_terms.get("delivery_window_days") if isinstance(agreed_terms, dict) else None

        # ── Counterparty ──
        if enterprise_role == "buyer":
            counterparty_id = session.seller_enterprise_id
        else:
            counterparty_id = session.buyer_enterprise_id

        # ── LLM Summary (non-fatal if fails) ──
        conversation_summary = await _generate_session_summary(
            session_id=str(session.id),
            outcome=outcome,
            product_name=product_name,
            agreed_price=agreed_price,
            total_rounds=session.round_count.value if hasattr(session.round_count, "value") else None,
            buyer_style=buyer_style,
            seller_style=seller_style,
        )

        # ── Embedding ──
        embedding = await self._generate_embedding(conversation_summary or _fallback_summary(
            product_name, outcome, agreed_price, session.round_count.value if hasattr(session.round_count, "value") else 0
        ))

        # ── Retention policy ──
        retention_expires_at = _compute_retention(outcome, RecordType.PLATFORM_SESSION)

        now = datetime.now(tz=timezone.utc)

        return NegotiationRecord(
            id=uuid.uuid4(),
            enterprise_id=enterprise_id,
            record_type=RecordType.PLATFORM_SESSION,
            source_session_id=session.id,
            counterparty_enterprise_id=counterparty_id,
            enterprise_role=enterprise_role,
            product_name=product_name,
            product_category=product_category,
            hsn_code=hsn_code,
            industry_vertical=industry_vertical,
            quantity=quantity,
            quantity_unit=quantity_unit,
            outcome=outcome,
            agreed_price_inr=agreed_price,
            initial_ask_price_inr=initial_ask,
            initial_bid_price_inr=initial_bid,
            final_discount_pct=final_discount_pct,
            total_rounds=session.round_count.value if hasattr(session.round_count, "value") else len(rounds_data),
            duration_hours=duration_hours,
            buyer_avg_concession_pct=buyer_avg_concession_pct,
            seller_avg_concession_pct=seller_avg_concession_pct,
            buyer_style=buyer_style,
            seller_style=seller_style,
            deal_quality_score=deal_quality_score,
            agreed_terms=agreed_terms if isinstance(agreed_terms, dict) else None,
            payment_terms=payment_terms,
            delivery_window_days=delivery_window_days,
            offer_sequence=offer_sequence,
            conversation_summary=conversation_summary,
            schema_version=1,
            confidence_score=Decimal("0.9"),
            normalized_at=now,
            retention_expires_at=retention_expires_at,
            embedding=embedding,
            created_at=now,
            updated_at=now,
        )

    async def normalize_historical_document(
        self,
        content: str,
        enterprise_id: uuid.UUID,
        filename: str,
        enterprise_role: str = "buyer",
    ) -> list[NegotiationRecord]:
        """
        LLM-extract negotiation records from unstructured historical documents.

        Two-stage:
          1. Classification: is this document a negotiation record?
          2. Extraction: if yes, extract structured records.

        Returns empty list if document has no negotiation data or LLM unavailable.
        """
        # Stage 1: Classification (cheap)
        classification_prompt = (
            "Analyze this document and determine if it contains negotiation records "
            "(purchase orders, price negotiations, B2B trade discussions, contracts, etc.).\n\n"
            f"Document excerpt (first 2000 chars):\n{content[:2000]}\n\n"
            'Return JSON: {"is_negotiation": true/false, "count_estimate": <number>}'
        )
        class_raw = await _llm_call(
            classification_prompt,
            system="You are a document classifier. Respond only with valid JSON.",
            max_tokens=100,
        )

        is_negotiation = False
        if class_raw:
            try:
                cleaned = class_raw.strip().strip("```json").strip("```").strip()
                class_result = json.loads(cleaned)
                is_negotiation = bool(class_result.get("is_negotiation", False))
            except Exception:
                # If JSON parse fails, check for keyword hints
                is_negotiation = any(
                    kw in content.lower()
                    for kw in ["negotiat", "price", "discount", "purchase order", "quotation", "rfq"]
                )

        if not is_negotiation:
            log.info(
                "historical_doc_not_negotiation",
                filename=filename,
                enterprise_id=str(enterprise_id),
            )
            return []

        # Stage 2: Extraction
        extraction_prompt = (
            "Extract ALL negotiation events from this document. "
            "For each negotiation found, return a JSON object with these fields "
            "(use null for unknown fields):\n"
            "{\n"
            '  "product_name": string or null,\n'
            '  "product_category": string or null,\n'
            '  "hsn_code": string or null,\n'
            '  "outcome": "AGREED" | "REJECTED" | "STALLED" | "EXPIRED" | "UNKNOWN",\n'
            '  "agreed_price_inr": number or null,\n'
            '  "initial_ask_price_inr": number or null,\n'
            '  "initial_bid_price_inr": number or null,\n'
            '  "total_rounds": integer or null,\n'
            '  "buyer_style": string or null,\n'
            '  "seller_style": string or null,\n'
            '  "payment_terms": string or null,\n'
            '  "delivery_window_days": integer or null,\n'
            '  "summary": string\n'
            "}\n\n"
            "Return a JSON array of negotiation objects. Return [] if none found.\n\n"
            f"Document:\n{content[:6000]}"
        )
        extraction_raw = await _llm_call(
            extraction_prompt,
            system="You are a data extraction specialist. Respond only with a valid JSON array.",
            max_tokens=2048,
        )

        if not extraction_raw:
            return []

        try:
            cleaned = extraction_raw.strip().strip("```json").strip("```").strip()
            extractions = json.loads(cleaned)
            if not isinstance(extractions, list):
                extractions = [extractions]
        except Exception as exc:
            log.warning(
                "historical_doc_extraction_parse_failed",
                filename=filename,
                error=str(exc),
            )
            return []

        records: list[NegotiationRecord] = []
        now = datetime.now(tz=timezone.utc)

        for extraction in extractions:
            if not isinstance(extraction, dict):
                continue

            outcome_str = extraction.get("outcome", "UNKNOWN")
            try:
                outcome = NegotiationOutcome(outcome_str)
            except ValueError:
                outcome = NegotiationOutcome.UNKNOWN

            # Confidence: fraction of required fields populated
            required_fields = ["product_name", "outcome", "agreed_price_inr"]
            populated = sum(1 for f in required_fields if extraction.get(f) is not None)
            confidence = Decimal(str(round(populated / len(required_fields), 2)))

            summary = extraction.get("summary") or _fallback_summary(
                extraction.get("product_name"),
                outcome,
                Decimal(str(extraction["agreed_price_inr"])) if extraction.get("agreed_price_inr") else None,
                extraction.get("total_rounds"),
            )

            embedding = await self._generate_embedding(summary)

            records.append(
                NegotiationRecord(
                    id=uuid.uuid4(),
                    enterprise_id=enterprise_id,
                    record_type=RecordType.HISTORICAL_IMPORT,
                    source_session_id=None,
                    enterprise_role=enterprise_role,
                    product_name=extraction.get("product_name"),
                    product_category=extraction.get("product_category"),
                    hsn_code=extraction.get("hsn_code"),
                    outcome=outcome,
                    agreed_price_inr=Decimal(str(extraction["agreed_price_inr"])) if extraction.get("agreed_price_inr") else None,
                    initial_ask_price_inr=Decimal(str(extraction["initial_ask_price_inr"])) if extraction.get("initial_ask_price_inr") else None,
                    initial_bid_price_inr=Decimal(str(extraction["initial_bid_price_inr"])) if extraction.get("initial_bid_price_inr") else None,
                    total_rounds=extraction.get("total_rounds"),
                    buyer_style=extraction.get("buyer_style"),
                    seller_style=extraction.get("seller_style"),
                    payment_terms=extraction.get("payment_terms"),
                    delivery_window_days=extraction.get("delivery_window_days"),
                    conversation_summary=summary,
                    raw_source_text=content[:10000],
                    schema_version=1,
                    confidence_score=confidence,
                    source_filename=filename,
                    normalized_at=now,
                    retention_expires_at=None,  # Historical imports never auto-expire
                    embedding=embedding,
                    created_at=now,
                    updated_at=now,
                )
            )

        log.info(
            "historical_doc_normalized",
            filename=filename,
            enterprise_id=str(enterprise_id),
            records_extracted=len(records),
        )
        return records

    async def normalize_agent_conversation(
        self,
        session: "NegotiationSession",
        enterprise_id: uuid.UUID,
        enterprise_role: str,
        llm_interactions: list[dict],
    ) -> NegotiationRecord:
        """
        Capture the full LLM prompt/response chain from NeutralEngine as a record.

        Stores the raw agent reasoning chain for debugging and agent learning.
        outcome and pricing are the same as the platform record — this is the
        "how the agent thought" complement to the "what happened" platform record.
        """
        _transcript = getattr(session, "conversation_transcript", None) or {}
        status_val = session.status.value if hasattr(session.status, "value") else str(session.status)
        outcome = SESSION_STATUS_TO_OUTCOME.get(status_val, NegotiationOutcome.UNKNOWN)

        agreed_price = None
        if session.agreed_price is not None:
            agreed_price = Decimal(str(session.agreed_price.amount))

        now = datetime.now(tz=timezone.utc)

        # Store LLM interactions as offer_sequence for traceability
        interaction_sequence = [
            {
                "turn": i + 1,
                "system_prompt_preview": str(ix.get("system_prompt", ""))[:300],
                "user_message_preview": str(ix.get("user_message", ""))[:300],
                "response_preview": str(ix.get("response", ""))[:300],
            }
            for i, ix in enumerate(llm_interactions[:50])  # Cap at 50 turns
        ]

        summary = (
            f"Agent conversation transcript for session {session.id}. "
            f"Outcome: {outcome.value}. "
            f"Rounds: {session.round_count.value if hasattr(session.round_count, 'value') else 'N/A'}. "
            f"Agreed price: {agreed_price if agreed_price else 'N/A'}."
        )

        return NegotiationRecord(
            id=uuid.uuid4(),
            enterprise_id=enterprise_id,
            record_type=RecordType.AGENT_CONVERSATION,
            source_session_id=session.id,
            enterprise_role=enterprise_role,
            outcome=outcome,
            agreed_price_inr=agreed_price,
            total_rounds=session.round_count.value if hasattr(session.round_count, "value") else None,
            offer_sequence=interaction_sequence,
            conversation_summary=summary,
            schema_version=1,
            confidence_score=Decimal("1.0"),
            normalized_at=now,
            retention_expires_at=_compute_retention(outcome, RecordType.AGENT_CONVERSATION),
            created_at=now,
            updated_at=now,
        )

    async def _generate_embedding(self, text: str | None) -> list[float] | None:
        """Generate 1536-dim embedding for semantic search. Returns None if unavailable."""
        if not text or not self._embedding_service:
            return None
        try:
            return await self._embedding_service.embed_query(text)
        except Exception as exc:
            log.warning("normalization_embedding_failed", error=str(exc))
            return None


# ── LLM Summary Helper ────────────────────────────────────────────────────────


async def _generate_session_summary(
    session_id: str,
    outcome: NegotiationOutcome,
    product_name: str | None,
    agreed_price: Decimal | None,
    total_rounds: int | None,
    buyer_style: str | None,
    seller_style: str | None,
) -> str | None:
    """Generate a 2-sentence LLM summary of a completed session for RAG indexing."""
    price_line = (
        f"- Agreed price: \u20b9{agreed_price:,.0f}" if agreed_price else "- Agreed price: N/A"
    )
    prompt = (
        "Summarize this B2B negotiation in 2 sentences for a memory system:\n"
        f"- Product: {product_name or 'unknown'}\n"
        f"- Outcome: {outcome.value}\n"
        f"{price_line}\n"
        f"- Rounds: {total_rounds or 'N/A'}\n"
        f"- Buyer style: {buyer_style or 'unknown'}, Seller style: {seller_style or 'unknown'}\n\n"
        "Write a factual 2-sentence summary."
    )
    return await _llm_call(prompt, max_tokens=150)


def _fallback_summary(
    product_name: str | None,
    outcome: NegotiationOutcome,
    agreed_price: Decimal | None,
    total_rounds: int | None,
) -> str:
    parts = [f"Negotiation for {product_name or 'unknown product'}", f"Outcome: {outcome.value}"]
    if agreed_price:
        parts.append(f"Agreed price: ₹{agreed_price:,.0f}")
    if total_rounds:
        parts.append(f"Rounds: {total_rounds}")
    return ". ".join(parts) + "."


# ── Concession Math Helpers ───────────────────────────────────────────────────


def _avg_concession(prices: list[float]) -> Decimal | None:
    if len(prices) < 2:
        return None
    deltas = [
        abs(prices[i] - prices[i - 1]) / max(abs(prices[i - 1]), 1)
        for i in range(1, len(prices))
    ]
    return Decimal(str(round(sum(deltas) / len(deltas) * 100, 4)))


def _classify_style(prices: list[float], ascending: bool) -> str | None:
    """Classify concession style from price trajectory."""
    if len(prices) < 3:
        return None
    deltas = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
    if not deltas:
        return None
    first_half = sum(deltas[: len(deltas) // 2]) / max(len(deltas) // 2, 1)
    second_half = sum(deltas[len(deltas) // 2 :]) / max(len(deltas) - len(deltas) // 2, 1)
    if first_half < second_half * 0.5:
        return "assertive"   # Boulware-like: small early concessions
    if first_half > second_half * 1.5:
        return "collaborative"  # Conceder-like: large early concessions
    return "analytical"     # Linear: consistent concessions
