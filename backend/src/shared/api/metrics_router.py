"""
Prometheus /metrics endpoint router.

context.md §10: GET /metrics — internal only.
Caddyfile blocks /metrics from external access (respond /metrics 403).

Uses prometheus_client.generate_latest() to return all registered
metrics in Prometheus text exposition format.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["observability"])


@router.get(
    "/metrics",
    summary="Prometheus metrics endpoint (internal only)",
    response_class=Response,
)
async def prometheus_metrics() -> Response:
    """
    Return all registered Prometheus metrics.

    This endpoint is blocked from external access by Caddy
    (Caddyfile: respond /metrics 403). Only internal monitoring
    tools (e.g., Prometheus scraper on Docker network) can reach it.
    """
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
