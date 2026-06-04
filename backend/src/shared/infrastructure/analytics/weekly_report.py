# Weekly operational report — runs as ECS scheduled task Monday 08:00 IST.
# Queries PostgreSQL for trade + performance metrics, publishes to Slack + S3.

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.shared.infrastructure.logging import get_logger

log = get_logger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


class WeeklyOperationalReport:
    """Generate weekly operational metrics report."""

    def __init__(self, db_session, redis_client=None) -> None:
        self._session = db_session
        self._redis = redis_client

    async def generate(self) -> dict:
        """Generate a structured JSON report for the last 7 days."""
        now = datetime.now(IST)
        week_ago = now - timedelta(days=7)

        report = {
            "generated_at": now.isoformat(),
            "period_start": week_ago.isoformat(),
            "period_end": now.isoformat(),
            "trade_metrics": await self._trade_metrics(week_ago),
            "performance_metrics": await self._performance_metrics(),
            "llm_metrics": await self._llm_metrics(week_ago),
        }

        log.info("weekly_report_generated", period=report["period_start"])
        return report

    async def _trade_metrics(self, since: datetime) -> dict:
        """Query trade-related metrics from PostgreSQL."""
        from sqlalchemy import text

        queries = {
            "rfqs_uploaded": "SELECT COUNT(*) FROM rfqs WHERE created_at >= :since",
            "rfqs_matched": "SELECT COUNT(*) FROM rfqs WHERE status IN ('MATCHED','CONFIRMED','SETTLED') AND created_at >= :since",
            "rfqs_confirmed": "SELECT COUNT(*) FROM rfqs WHERE status IN ('CONFIRMED','SETTLED') AND created_at >= :since",
            "sessions_created": "SELECT COUNT(*) FROM negotiation_sessions WHERE created_at >= :since",
            "sessions_agreed": "SELECT COUNT(*) FROM negotiation_sessions WHERE status = 'AGREED' AND created_at >= :since",
            "escrows_deployed": "SELECT COUNT(*) FROM escrows WHERE created_at >= :since",
            "escrows_released": "SELECT COUNT(*) FROM escrows WHERE status = 'RELEASED' AND created_at >= :since",
        }

        results = {}
        for key, sql in queries.items():
            try:
                result = await self._session.execute(
                    text(sql), {"since": since}
                )
                results[key] = result.scalar() or 0
            except Exception:
                log.warning("weekly_report_query_failed", query=key)
                results[key] = -1  # Signal query failure

        # Derived metrics
        sessions_created = results.get("sessions_created", 0)
        sessions_agreed = results.get("sessions_agreed", 0)
        results["agreement_rate_pct"] = (
            round(sessions_agreed / sessions_created * 100, 1)
            if sessions_created > 0
            else 0.0
        )

        return results

    async def _performance_metrics(self) -> dict:
        """Query real performance metrics from PostgreSQL."""
        from sqlalchemy import text

        metrics: dict = {}
        try:
            # Avg settlement time: time between escrow deploy and release
            result = await self._session.execute(text(
                "SELECT AVG(EXTRACT(EPOCH FROM (updated_at - created_at))) "
                "FROM escrows WHERE status = 'RELEASED'"
            ))
            avg_settlement_secs = result.scalar()
            metrics["avg_settlement_time_secs"] = (
                round(avg_settlement_secs, 1) if avg_settlement_secs else None
            )
        except Exception:
            metrics["avg_settlement_time_secs"] = None

        try:
            # Avg rounds per negotiation session
            result = await self._session.execute(text(
                "SELECT AVG(current_round) FROM negotiation_sessions "
                "WHERE status IN ('AGREED', 'WALK_AWAY', 'TIMEOUT')"
            ))
            avg_rounds = result.scalar()
            metrics["avg_negotiation_rounds"] = (
                round(float(avg_rounds), 1) if avg_rounds else None
            )
        except Exception:
            metrics["avg_negotiation_rounds"] = None

        try:
            # Total active enterprises
            result = await self._session.execute(text(
                "SELECT COUNT(*) FROM enterprises WHERE kyc_status = 'ACTIVE'"
            ))
            metrics["active_enterprises"] = result.scalar() or 0
        except Exception:
            metrics["active_enterprises"] = None

        return metrics

    async def _llm_metrics(self, since: datetime) -> dict:
        """Query LLM usage metrics from the negotiation_offers table."""
        from sqlalchemy import text

        metrics: dict = {}
        try:
            # Total LLM-generated offers (non-human-override)
            result = await self._session.execute(text(
                "SELECT COUNT(*) FROM negotiation_offers "
                "WHERE is_human_override = false AND created_at >= :since"
            ), {"since": since})
            metrics["total_llm_calls"] = result.scalar() or 0
        except Exception:
            metrics["total_llm_calls"] = None

        try:
            # Human override count and rate
            result = await self._session.execute(text(
                "SELECT "
                "  COUNT(*) FILTER (WHERE is_human_override = true) as overrides, "
                "  COUNT(*) as total "
                "FROM negotiation_offers WHERE created_at >= :since"
            ), {"since": since})
            row = result.one_or_none()
            if row and row.total > 0:
                metrics["human_overrides"] = row.overrides
                metrics["human_override_rate_pct"] = round(
                    row.overrides / row.total * 100, 1
                )
            else:
                metrics["human_overrides"] = 0
                metrics["human_override_rate_pct"] = 0.0
        except Exception:
            metrics["human_overrides"] = None
            metrics["human_override_rate_pct"] = None

        try:
            # Avg confidence of LLM-generated offers
            result = await self._session.execute(text(
                "SELECT AVG(confidence) FROM negotiation_offers "
                "WHERE is_human_override = false AND confidence IS NOT NULL "
                "AND created_at >= :since"
            ), {"since": since})
            avg_conf = result.scalar()
            metrics["avg_llm_confidence"] = (
                round(float(avg_conf), 3) if avg_conf else None
            )
        except Exception:
            metrics["avg_llm_confidence"] = None

        return metrics
