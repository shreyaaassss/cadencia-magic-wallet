"""
backfill_negotiation_records.py — One-time data migration.

Converts all completed NegotiationSessions into canonical NegotiationRecords
and computes NegotiationInsights for all affected enterprises.

Usage:
    python -m scripts.backfill_negotiation_records
    python -m scripts.backfill_negotiation_records --dry-run
    python -m scripts.backfill_negotiation_records --batch-size 50

Idempotent: skips sessions that already have a linked NegotiationRecord.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure backend/ is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import structlog

log = structlog.get_logger(__name__)

TERMINAL_STATUSES = [
    "AGREED",
    "WALK_AWAY",
    "FAILED",
    "EXPIRED",
    "TIMEOUT",
    "POLICY_BREACH",
    "STALLED",
]


async def backfill(dry_run: bool = False, batch_size: int = 100) -> None:
    """Main backfill routine."""
    from src.shared.infrastructure.db.session import get_session_factory
    from src.negotiation.infrastructure.repositories import (
        PostgresNegotiationRecordRepository,
        PostgresNegotiationInsightRepository,
        PostgresSessionRepository,
    )
    from src.negotiation.infrastructure.models import NegotiationSessionModel
    from src.negotiation.application.normalization_service import NormalizationService
    from src.negotiation.application.insight_engine import InsightEngine
    from sqlalchemy import select

    # Load all models so SQLAlchemy metadata resolves cross-context FK references
    # (enterprises table is in identity context; negotiation_records has FK to it)
    import src.identity.infrastructure.models  # noqa: F401
    import src.settlement.infrastructure.models  # noqa: F401 - pulls in more FK targets
    import src.marketplace.infrastructure.models  # noqa: F401

    log.info(
        "backfill_started",
        dry_run=dry_run,
        batch_size=batch_size,
        terminal_statuses=TERMINAL_STATUSES,
    )

    normalization_svc = NormalizationService(embedding_service=None)

    total_processed = 0
    total_skipped = 0
    total_errors = 0
    affected_enterprises: set = set()

    offset = 0
    while True:
        async with get_session_factory()() as db_session:
            # Fetch a batch of completed sessions
            stmt = (
                select(NegotiationSessionModel)
                .where(NegotiationSessionModel.status.in_(TERMINAL_STATUSES))
                .order_by(NegotiationSessionModel.created_at.asc())
                .limit(batch_size)
                .offset(offset)
            )
            result = await db_session.execute(stmt)
            session_models = result.scalars().all()

            if not session_models:
                break

            session_repo = PostgresSessionRepository(db_session)
            record_repo = PostgresNegotiationRecordRepository(db_session)

            for sm in session_models:
                try:
                    # Idempotency check
                    existing = await record_repo.get_by_session_id(sm.id)
                    if existing:
                        log.debug(
                            "backfill_skip_already_normalized",
                            session_id=str(sm.id),
                        )
                        total_skipped += 1
                        continue

                    session = await session_repo.get_by_id(sm.id)
                    if session is None:
                        total_errors += 1
                        continue

                    if dry_run:
                        log.info(
                            "backfill_dry_run_would_normalize",
                            session_id=str(sm.id),
                            status=sm.status,
                            buyer_enterprise_id=str(sm.buyer_enterprise_id),
                            seller_enterprise_id=str(sm.seller_enterprise_id),
                        )
                        total_processed += 1
                        continue

                    # Normalize for buyer
                    import uuid as _uuid
                    buyer_record = await normalization_svc.normalize_platform_session(
                        session=session,
                        enterprise_id=sm.buyer_enterprise_id,
                        enterprise_role="buyer",
                    )
                    await record_repo.save(buyer_record)

                    # Normalize for seller
                    seller_record = await normalization_svc.normalize_platform_session(
                        session=session,
                        enterprise_id=sm.seller_enterprise_id,
                        enterprise_role="seller",
                    )
                    seller_record.id = _uuid.uuid4()
                    await record_repo.save(seller_record)

                    affected_enterprises.add(sm.buyer_enterprise_id)
                    affected_enterprises.add(sm.seller_enterprise_id)
                    total_processed += 1

                    log.info(
                        "backfill_session_normalized",
                        session_id=str(sm.id),
                        status=sm.status,
                    )

                except Exception as exc:
                    log.error(
                        "backfill_session_failed",
                        session_id=str(sm.id),
                        error=str(exc),
                    )
                    total_errors += 1

            if not dry_run:
                await db_session.commit()

        offset += batch_size
        log.info(
            "backfill_batch_complete",
            offset=offset,
            total_processed=total_processed,
            total_skipped=total_skipped,
            total_errors=total_errors,
        )

    if not dry_run and affected_enterprises:
        log.info(
            "backfill_computing_insights",
            enterprise_count=len(affected_enterprises),
        )
        async with get_session_factory()() as db_session:
            record_repo = PostgresNegotiationRecordRepository(db_session)
            insight_repo = PostgresNegotiationInsightRepository(db_session)
            engine = InsightEngine(record_repo=record_repo, insight_repo=insight_repo)

            for eid in affected_enterprises:
                try:
                    await engine.compute_enterprise_insights(eid)
                    log.info("backfill_insights_computed", enterprise_id=str(eid))
                except Exception as exc:
                    log.error(
                        "backfill_insights_failed",
                        enterprise_id=str(eid),
                        error=str(exc),
                    )
            await db_session.commit()

    log.info(
        "backfill_complete",
        total_processed=total_processed,
        total_skipped=total_skipped,
        total_errors=total_errors,
        affected_enterprises=len(affected_enterprises),
        dry_run=dry_run,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill NegotiationRecords from existing sessions")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be done without writing to DB",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of sessions to process per DB transaction (default: 100)",
    )
    args = parser.parse_args()

    from src.shared.infrastructure.logging import configure_logging
    configure_logging()

    asyncio.run(backfill(dry_run=args.dry_run, batch_size=args.batch_size))


if __name__ == "__main__":
    main()
