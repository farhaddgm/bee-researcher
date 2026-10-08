"""Cross-process deployment barrier; admitted work completes before cutover.

The short admission gate and the long-lived work lock are separate. A drain
holds the gate exclusively BEFORE waiting for existing shared work leases,
so a busy scheduler cannot starve deployment. Closing/invalidation releases
session locks even after cancellation or process failure. No Redis TTL can
silently expire while an operation is still running.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from contextlib import asynccontextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any, Callable, Coroutine, ParamSpec, TypeVar

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

ADMISSION_KEY = 4231785201
WORK_KEY = 4231785202
_owner: ContextVar[asyncio.Task | None] = ContextVar("researcher_work_lease", default=None)
P = ParamSpec("P")
T = TypeVar("T")
_settings = get_settings()
# Leases must never use the business-query pool: otherwise concurrent HTTP
# leases could occupy every connection while their handlers wait for a query.
engine = create_async_engine(
    _settings.database_url,
    pool_pre_ping=True,
    pool_size=2,
    max_overflow=8,
    pool_timeout=_settings.database_pool_timeout_seconds,
    connect_args={"server_settings": {"application_name": "researcher-deployment-leases"}},
)


async def _connect():
    """Open a database connection through a patchable seam for unit tests."""
    return await engine.connect()


async def _cleanup(connection, locks: list[tuple[int, bool]]) -> None:
    try:
        await connection.rollback()
        for key, shared in reversed(locks):
            function = "pg_advisory_unlock_shared" if shared else "pg_advisory_unlock"
            await connection.scalar(text(f"SELECT {function}(:key)"), {"key": key})
        await connection.commit()
    except BaseException:
        # A failed unlock must not put a session lock back into the pool.
        await connection.invalidate()
        raise
    finally:
        await connection.close()


async def _release(connection, locks: list[tuple[int, bool]]) -> None:
    cleanup = asyncio.create_task(_cleanup(connection, locks))
    try:
        await asyncio.shield(cleanup)
    except asyncio.CancelledError:
        await cleanup
        raise


def unavailable() -> HTTPException:
    return HTTPException(503, "service is draining for deployment", headers={"Retry-After": "30"})


@asynccontextmanager
async def work_lease(*, enabled: bool | None = None):
    if enabled is None:
        enabled = get_settings().deployment_drain_enabled
    task = asyncio.current_task()
    # A child task inherits ContextVars but must own its own lease: it may
    # outlive its parent (for example an HTTP-created background operation).
    if not enabled or (_owner.get() is task and task is not None):
        yield
        return
    connection = await _connect()
    token = None
    locks: list[tuple[int, bool]] = []
    try:
        gate = await connection.scalar(text("SELECT pg_try_advisory_xact_lock_shared(:key)"), {"key": ADMISSION_KEY})
        if gate is not True:
            raise unavailable()
        admitted = await connection.scalar(text("SELECT pg_try_advisory_lock_shared(:key)"), {"key": WORK_KEY})
        if admitted is not True:
            raise unavailable()
        locks.append((WORK_KEY, True))
        await connection.commit()  # release the short transaction-level gate
        token = _owner.set(task)
        yield
    finally:
        if token is not None:
            _owner.reset(token)
        await _release(connection, locks)


def protected_work(function: Callable[P, Coroutine[Any, Any, T]]) -> Callable[P, Coroutine[Any, Any, T]]:
    @wraps(function)
    async def guarded(*args: P.args, **kwargs: P.kwargs) -> T:
        async with work_lease():
            return await function(*args, **kwargs)
    return guarded


@asynccontextmanager
async def maintenance_barrier(*, timeout: float = 300):
    connection = await _connect()
    locks: list[tuple[int, bool]] = []
    try:
        deadline = asyncio.get_running_loop().time() + timeout
        while not await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": ADMISSION_KEY}):
            await connection.rollback()
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("another deployment owns the admission gate")
            await asyncio.sleep(0.05)
        locks.append((ADMISSION_KEY, False))
        await connection.commit()
        remaining = max(0.01, deadline - asyncio.get_running_loop().time())
        await asyncio.wait_for(connection.scalar(text("SELECT pg_advisory_lock(:key)"), {"key": WORK_KEY}), remaining)
        locks.append((WORK_KEY, False))
        await connection.commit()
        yield
    finally:
        # If timeout/cancellation interrupted lock acquisition, discard the
        # session rather than risk an untracked server-side lock.
        if len(locks) != 2:
            try:
                await connection.invalidate()
            finally:
                await connection.close()
        else:
            await _release(connection, locks)


async def _hold(timeout: int, hold_seconds: int) -> None:
    if not get_settings().deployment_drain_enabled:
        raise RuntimeError("deployment drain must be enabled in the application runtime")
    try:
        async with maintenance_barrier(timeout=timeout):
            print("RESEARCHER_DRAINED", flush=True)
            command = await asyncio.wait_for(asyncio.to_thread(sys.stdin.readline), hold_seconds)
            if command.strip() != "release":
                raise RuntimeError("deployment controller disconnected without confirming cutover")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, choices=range(1, 3601), default=300)
    parser.add_argument("--hold-seconds", type=int, choices=range(1, 3601), default=600)
    args = parser.parse_args()
    asyncio.run(_hold(args.timeout, args.hold_seconds))


if __name__ == "__main__":
    main()
