"""
Unit tests for shared/api/responses.py and shared/api/pagination.py.

Tests:
    test_success_response_structure
    test_error_response_structure
    test_cursor_page_serialization
    test_offset_page_serialization
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from src.shared.api.pagination import CursorPage, OffsetPage
from src.shared.api.responses import (
    ApiResponse,
    ErrorDetail,
    ResponseMeta,
    error_response,
    success_response,
)


# ── Success response ──────────────────────────────────────────────────────────

def test_success_response_structure() -> None:
    data = {"enterprise_id": str(uuid.uuid4()), "name": "Acme Ltd"}
    response = success_response(data)

    assert response["status"] == "success"
    assert response["data"] == data


def test_success_response_auto_request_id() -> None:
    """success_response returns a plain dict with status + data."""
    response = success_response({"key": "value"})
    assert response["status"] == "success"
    assert response["data"]["key"] == "value"


def test_success_response_serializes_to_dict() -> None:
    response = success_response({"x": 1})

    assert response["status"] == "success"
    assert response["data"] == {"x": 1}


# ── Error response ────────────────────────────────────────────────────────────

def test_error_response_structure() -> None:
    request_id = uuid.uuid4()
    response = error_response(
        code="NOT_FOUND",
        message="Enterprise not found",
        request_id=request_id,
        field="enterprise_id",
    )

    assert response.success is False
    assert response.data is None
    assert response.error is not None
    assert response.error.code == "NOT_FOUND"
    assert response.error.message == "Enterprise not found"
    assert response.error.field == "enterprise_id"
    assert response.meta.request_id == str(request_id)


def test_error_response_without_field() -> None:
    response = error_response(code="INTERNAL_ERROR", message="Unexpected failure")
    assert response.error is not None
    assert response.error.field is None


def test_error_response_serializes_to_dict() -> None:
    response = error_response("POLICY_VIOLATION", "Budget ceiling exceeded")
    data = response.model_dump(mode="json")

    assert data["success"] is False
    assert data["data"] is None
    assert data["error"]["code"] == "POLICY_VIOLATION"
    assert data["error"]["message"] == "Budget ceiling exceeded"


# ── CursorPage ────────────────────────────────────────────────────────────────

def test_cursor_page_serialization() -> None:
    items = [{"id": str(uuid.uuid4()), "name": f"Item {i}"} for i in range(3)]
    page: CursorPage[dict] = CursorPage(
        items=items,
        next_cursor="eyJpZCI6IjEyMyJ9",
        has_more=True,
        total_count=100,
    )

    assert len(page.items) == 3
    assert page.has_more is True
    assert page.next_cursor == "eyJpZCI6IjEyMyJ9"
    assert page.total_count == 100

    serialized = page.model_dump(mode="json")
    assert serialized["items"] == items
    assert serialized["has_more"] is True


def test_cursor_page_no_more() -> None:
    page: CursorPage[str] = CursorPage(items=["a", "b"], next_cursor=None, has_more=False)
    assert page.has_more is False
    assert page.next_cursor is None


def test_cursor_page_empty() -> None:
    page: CursorPage[dict] = CursorPage(items=[], next_cursor=None, has_more=False, total_count=0)
    assert len(page.items) == 0
    assert page.total_count == 0


# ── OffsetPage ────────────────────────────────────────────────────────────────

def test_offset_page_serialization() -> None:
    items = [{"id": str(uuid.uuid4())} for _ in range(10)]
    page: OffsetPage[dict] = OffsetPage(items=items, total=47, page=2, page_size=10)

    assert page.total == 47
    assert page.page == 2
    assert page.page_size == 10
    assert page.total_pages == 5
    assert page.has_next is True
    assert page.has_prev is True


def test_offset_page_first_page() -> None:
    page: OffsetPage[dict] = OffsetPage(items=[], total=20, page=1, page_size=10)
    assert page.has_prev is False
    assert page.has_next is True


def test_offset_page_last_page() -> None:
    page: OffsetPage[dict] = OffsetPage(items=[], total=20, page=2, page_size=10)
    assert page.has_next is False
    assert page.has_prev is True


def test_offset_page_exact_fit() -> None:
    """total=10, page_size=10 → 1 page, no next."""
    page: OffsetPage[dict] = OffsetPage(items=[], total=10, page=1, page_size=10)
    assert page.total_pages == 1
    assert page.has_next is False


def test_offset_page_serializes_to_dict() -> None:
    page: OffsetPage[int] = OffsetPage(items=[1, 2, 3], total=3, page=1, page_size=10)
    data = page.model_dump(mode="json")
    assert data["items"] == [1, 2, 3]
    assert data["total"] == 3
    assert data["page"] == 1
    assert data["page_size"] == 10
