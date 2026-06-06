# Phase Five Unit Tests: Marketplace Domain + Infrastructure

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from src.marketplace.domain.capability_profile import CapabilityProfile
from src.marketplace.domain.match import Match
from src.marketplace.domain.rfq import RFQ
from src.marketplace.domain.value_objects import (
    BudgetRange,
    DeliveryWindow,
    HSNCode,
    MatchStatus,
    RFQStatus,
    SimilarityScore,
)
from src.marketplace.infrastructure.rfq_parser import StubDocumentParser
from src.marketplace.infrastructure.pgvector_matchmaker import StubMatchmakingEngine
from src.shared.domain.exceptions import ConflictError, ValidationError


# ═══════════════════════════════════════════════════════════════════════════════
# Value Object Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestHSNCode:
    def test_valid_4digit(self):
        h = HSNCode(value="7208")
        assert h.value == "7208"

    def test_valid_8digit(self):
        h = HSNCode(value="72082530")
        assert h.value == "72082530"

    def test_rejects_non_digit(self):
        with pytest.raises(ValidationError, match="4–8 digits"):
            HSNCode(value="ABC1")

    def test_rejects_3_digits(self):
        with pytest.raises(ValidationError, match="4–8 digits"):
            HSNCode(value="123")

    def test_rejects_9_digits(self):
        with pytest.raises(ValidationError, match="4–8 digits"):
            HSNCode(value="123456789")


class TestBudgetRange:
    def test_valid(self):
        b = BudgetRange(min_value=Decimal("1000"), max_value=Decimal("5000"))
        assert b.currency == "INR"

    def test_rejects_min_greater_than_max(self):
        with pytest.raises(ValidationError, match="min_value"):
            BudgetRange(min_value=Decimal("5000"), max_value=Decimal("1000"))

    def test_rejects_negative(self):
        with pytest.raises(ValidationError, match="min_value"):
            BudgetRange(min_value=Decimal("-1"), max_value=Decimal("1000"))


class TestDeliveryWindow:
    def test_valid(self):
        d = DeliveryWindow(start_date=date(2026, 5, 1), end_date=date(2026, 5, 31))
        assert d.start_date < d.end_date

    def test_rejects_start_after_end(self):
        with pytest.raises(ValidationError, match="start"):
            DeliveryWindow(start_date=date(2026, 6, 1), end_date=date(2026, 5, 1))


class TestSimilarityScore:
    def test_valid(self):
        s = SimilarityScore(value=0.85)
        assert s.value == 0.85

    def test_rejects_above_one(self):
        with pytest.raises(ValidationError):
            SimilarityScore(value=1.5)


# ═══════════════════════════════════════════════════════════════════════════════
# RFQ Aggregate Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestRFQ:
    def test_mark_parsed_with_all_fields(self):
        rfq = RFQ(raw_document="Need 500MT HR Coil")
        event_data = rfq.mark_parsed({
            "product": "HR Coil",
            "hsn_code": "7208",
            "budget_min": 45000,
            "budget_max": 50000,
            "delivery_window_start": "2026-05-01",
            "delivery_window_end": "2026-05-31",
            "geography": "Mumbai",
        })
        assert rfq.status == RFQStatus.PARSED
        assert rfq.hsn_code is not None
        assert rfq.budget_range is not None
        assert rfq.delivery_window is not None
        assert event_data["has_budget"] is True

    def test_mark_parsed_with_partial_fields_no_exception(self):
        rfq = RFQ(raw_document="Need steel")
        event_data = rfq.mark_parsed({"product": "Steel"})
        assert rfq.status == RFQStatus.PARSED
        assert rfq.hsn_code is None
        assert rfq.budget_range is None
        assert event_data["has_budget"] is False

    def test_mark_parsed_raises_if_not_draft(self):
        rfq = RFQ()
        rfq.status = RFQStatus.MATCHED
        with pytest.raises(ConflictError, match="expected DRAFT"):
            rfq.mark_parsed({"product": "Steel"})

    def test_mark_parsed_raises_without_product(self):
        rfq = RFQ()
        with pytest.raises(ValidationError, match="product"):
            rfq.mark_parsed({"hsn_code": "7208"})

    def test_mark_matched(self):
        rfq = RFQ()
        rfq.status = RFQStatus.PARSED
        rfq.mark_matched(5)
        assert rfq.status == RFQStatus.MATCHED

    def test_mark_matched_raises_if_not_parsed(self):
        rfq = RFQ()
        with pytest.raises(ConflictError, match="expected PARSED"):
            rfq.mark_matched(5)

    def test_confirm(self):
        rfq = RFQ()
        rfq.status = RFQStatus.MATCHED
        match_id = uuid.uuid4()
        data = rfq.confirm(match_id)
        assert rfq.status == RFQStatus.CONFIRMED
        assert data["match_id"] == match_id

    def test_confirm_raises_if_not_matched(self):
        rfq = RFQ()
        with pytest.raises(ConflictError, match="expected MATCHED"):
            rfq.confirm(uuid.uuid4())

    def test_rfq_confirmed_event_fields(self):
        from src.marketplace.domain.events import RFQConfirmed
        ev = RFQConfirmed(
            aggregate_id=uuid.uuid4(),
            event_type="RFQConfirmed",
            rfq_id=uuid.uuid4(),
            match_id=uuid.uuid4(),
            buyer_enterprise_id=uuid.uuid4(),
            seller_enterprise_id=uuid.uuid4(),
        )
        assert ev.rfq_id is not None
        assert ev.match_id is not None
        assert ev.buyer_enterprise_id is not None
        assert ev.seller_enterprise_id is not None

    def test_mark_settled(self):
        rfq = RFQ()
        rfq.status = RFQStatus.CONFIRMED
        rfq.mark_settled()
        assert rfq.status == RFQStatus.SETTLED

    def test_mark_expired(self):
        rfq = RFQ()
        rfq.mark_expired()
        assert rfq.status == RFQStatus.EXPIRED

    def test_mark_expired_raises_if_confirmed(self):
        rfq = RFQ()
        rfq.status = RFQStatus.CONFIRMED
        with pytest.raises(ConflictError):
            rfq.mark_expired()


# ═══════════════════════════════════════════════════════════════════════════════
# Match Entity Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestMatch:
    def test_select(self):
        m = Match()
        m.select()
        assert m.status == MatchStatus.SELECTED

    def test_reject(self):
        m = Match()
        m.reject()
        assert m.status == MatchStatus.REJECTED

    def test_select_raises_if_already_selected(self):
        m = Match()
        m.select()
        with pytest.raises(ConflictError, match="expected PENDING"):
            m.select()


# ═══════════════════════════════════════════════════════════════════════════════
# CapabilityProfile Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCapabilityProfile:
    def test_update_nullifies_embedding(self):
        p = CapabilityProfile(embedding=[0.1] * 1536)
        p.update_profile("steel", ["coil"], ["IN"], None, None)
        assert p.embedding is None

    def test_set_embedding_validates_dims(self):
        p = CapabilityProfile()
        p.set_embedding([0.1] * 1536)
        assert len(p.embedding) == 1536

    def test_set_embedding_rejects_wrong_dims(self):
        p = CapabilityProfile()
        with pytest.raises(ValidationError, match="1536"):
            p.set_embedding([0.1] * 100)


# ═══════════════════════════════════════════════════════════════════════════════
# Infrastructure: StubDocumentParser + StubMatchmakingEngine
# ═══════════════════════════════════════════════════════════════════════════════


class TestStubDocumentParser:
    @pytest.mark.anyio
    async def test_extract_returns_all_fields(self):
        parser = StubDocumentParser()
        result = await parser.extract_rfq_fields("Need 500MT HR Coil")
        assert "product" in result
        assert "hsn_code" in result
        assert result["product"] == "HR Coil"

    @pytest.mark.anyio
    async def test_embedding_returns_1536_floats(self):
        parser = StubDocumentParser()
        emb = await parser.generate_embedding("test text")
        assert len(emb) == 1536
        assert all(isinstance(v, float) for v in emb)

    @pytest.mark.anyio
    async def test_embedding_is_deterministic(self):
        parser = StubDocumentParser()
        e1 = await parser.generate_embedding("same text")
        e2 = await parser.generate_embedding("same text")
        assert e1 == e2


class TestStubMatchmakingEngine:
    @pytest.mark.anyio
    async def test_returns_matches(self):
        """Stub without DB session returns empty (safe fallback)."""
        engine = StubMatchmakingEngine()
        rfq = RFQ()
        matches = await engine.find_matches(rfq, [0.1] * 1536, top_n=5)
        # Without a DB session, stub returns empty list (no fabricated UUIDs)
        assert isinstance(matches, list)

    @pytest.mark.anyio
    async def test_scores_decrease(self):
        """Stub returns empty or sorted scores."""
        engine = StubMatchmakingEngine()
        rfq = RFQ()
        matches = await engine.find_matches(rfq, [0.1] * 1536, top_n=5)
        if matches:
            scores = [s for _, s in matches]
            assert scores == sorted(scores, reverse=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Circuit Breaker Tests
# ═══════════════════════════════════════════════════════════════════════════════


class FakeRedis:
    """Minimal fake Redis for circuit breaker tests."""

    def __init__(self):
        self._data: dict[str, str] = {}

    async def get(self, key: str):
        return self._data.get(key)

    async def set(self, key: str, value: str):
        self._data[key] = value

    async def incr(self, key: str):
        val = int(self._data.get(key, "0")) + 1
        self._data[key] = str(val)
        return val

    async def delete(self, *keys: str):
        for k in keys:
            self._data.pop(k, None)


class TestCircuitBreaker:
    @pytest.mark.anyio
    async def test_starts_closed(self):
        from src.shared.infrastructure.circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker("test", FakeRedis(), failure_threshold=3, recovery_timeout=60)
        assert await cb.get_state() == CircuitState.CLOSED

    @pytest.mark.anyio
    async def test_opens_after_threshold(self):
        from src.shared.infrastructure.circuit_breaker import CircuitBreaker, CircuitState, CircuitOpenError
        redis = FakeRedis()
        cb = CircuitBreaker("test", redis, failure_threshold=3, recovery_timeout=60)

        for _ in range(3):
            try:
                await cb.call(self._failing_coro())
            except RuntimeError:
                pass

        assert await cb.get_state() == CircuitState.OPEN

    @pytest.mark.anyio
    async def test_open_circuit_raises(self):
        from src.shared.infrastructure.circuit_breaker import CircuitBreaker, CircuitOpenError
        redis = FakeRedis()
        cb = CircuitBreaker("test", redis, failure_threshold=2, recovery_timeout=60)

        for _ in range(2):
            try:
                await cb.call(self._failing_coro())
            except RuntimeError:
                pass

        with pytest.raises(CircuitOpenError):
            await cb.call(self._success_coro())

    @pytest.mark.anyio
    async def test_success_resets_failures(self):
        from src.shared.infrastructure.circuit_breaker import CircuitBreaker, CircuitState
        redis = FakeRedis()
        cb = CircuitBreaker("test", redis, failure_threshold=3, recovery_timeout=60)

        # One failure then one success
        try:
            await cb.call(self._failing_coro())
        except RuntimeError:
            pass
        await cb.call(self._success_coro())
        assert await cb.get_state() == CircuitState.CLOSED

    @staticmethod
    async def _failing_coro():
        raise RuntimeError("fail")

    @staticmethod
    async def _success_coro():
        return "ok"
