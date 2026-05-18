"""
Alembic migration environment for Cadencia.

Configured for async SQLAlchemy with asyncpg.
DATABASE_URL is read from the environment variable — never hardcoded.
context.md §15: migrations must be idempotent; scripts/migrate.py safe at startup.
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

# Ensure the project root is on sys.path so `src.*` imports work
# regardless of how Alembic is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# Import shared Base — all ORM models must be registered on it.
from src.shared.infrastructure.db.base import Base

# Import all ORM models so their tables are registered on Base.metadata.
# Alembic reads Base.metadata to detect schema changes.
# noqa: F401 — imports are for side effects (model registration).
import src.identity.infrastructure.models  # noqa: F401
import src.marketplace.infrastructure.models  # noqa: F401
import src.negotiation.infrastructure.models  # noqa: F401
import src.settlement.infrastructure.models  # noqa: F401
import src.compliance.infrastructure.models  # noqa: F401
import src.treasury.infrastructure.models  # noqa: F401
import src.admin.models  # noqa: F401
import src.wallet.models  # noqa: F401

# Alembic Config object — provides access to alembic.ini values.
config = context.config

# Setup Python logging from alembic.ini [loggers] section.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate support.
target_metadata = Base.metadata


def get_url() -> str:
    """Read DATABASE_URL from environment — prefer direct connection for migrations.

    Supabase: use DATABASE_DIRECT_URL (port 5432) to bypass PgBouncer.
    Local dev: DATABASE_URL works fine.
    """
    url = os.environ.get("DATABASE_DIRECT_URL") or os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "DATABASE_URL or DATABASE_DIRECT_URL environment variable is required for migrations."
        )
    return url


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode (generate SQL without a DB connection).
    Useful for generating migration scripts for review.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        # Include schemas for pgvector types
        include_schemas=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode (execute against a live DB connection).
    Used by scripts/migrate.py at container startup.
    """
    url = get_url()
    connectable = create_async_engine(url, echo=False)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
