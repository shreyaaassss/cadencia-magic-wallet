"""Lightweight asyncio-based background scheduler.

Replaces the need for Celery/APScheduler. Registers periodic coroutines
that run at fixed intervals. Started in FastAPI lifespan, stopped on shutdown.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

import structlog

log = structlog.get_logger(__name__)

PeriodicJob = Callable[[], Awaitable[None]]


class BackgroundScheduler:
    """Runs registered async jobs at fixed intervals using asyncio tasks."""

    def __init__(self) -> None:
        self._jobs: list[tuple[str, PeriodicJob, float]] = []
        self._tasks: list[asyncio.Task] = []
        self._running = False

    def register_periodic(
        self, name: str, coro_fn: PeriodicJob, interval_seconds: float
    ) -> None:
        """Register a periodic job. Must be called before start()."""
        self._jobs.append((name, coro_fn, interval_seconds))
        log.info("scheduler_job_registered", name=name, interval=interval_seconds)

    async def start(self) -> None:
        """Start all registered periodic jobs as background tasks."""
        if self._running:
            return
        self._running = True
        for name, coro_fn, interval in self._jobs:
            task = asyncio.create_task(self._run_loop(name, coro_fn, interval))
            self._tasks.append(task)
        log.info("scheduler_started", jobs=len(self._jobs))

    async def stop(self) -> None:
        """Cancel all running jobs."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        log.info("scheduler_stopped")

    async def _run_loop(
        self, name: str, coro_fn: PeriodicJob, interval: float
    ) -> None:
        """Run a single job in a loop with error isolation."""
        # Initial delay to stagger jobs on startup
        await asyncio.sleep(5.0)
        while self._running:
            try:
                await coro_fn()
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("scheduler_job_failed", name=name)
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
