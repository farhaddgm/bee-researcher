"""Exercise real PostgreSQL barriers without touching business data or APIs."""
import asyncio

from fastapi import HTTPException

from app.config import get_settings
from app.deployment_drain import engine, maintenance_barrier, work_lease


async def main():
    settings = get_settings()
    assert settings.environment == "test", "isolated test database required"
    drained, release = asyncio.Event(), asyncio.Event()

    async def deploy():
        async with maintenance_barrier(timeout=5):
            drained.set()
            await release.wait()

    async with work_lease(enabled=True):
        task = asyncio.create_task(deploy())
        blocked = False
        async with work_lease(enabled=True):
            pass
        # Nested work in this same task is admitted intentionally; use a fresh
        # task to test the process-wide admission boundary, not reentrancy.
        async def newcomer():
            async with work_lease(enabled=True):
                return "admitted"
        for _ in range(100):
            try:
                await asyncio.create_task(newcomer())
            except HTTPException as exc:
                assert exc.status_code == 503
                blocked = True
                break
            await asyncio.sleep(0.01)
        assert blocked and not drained.is_set(), "drain must wait for admitted work"
    await asyncio.wait_for(drained.wait(), 5)
    try:
        async with work_lease(enabled=True):
            raise AssertionError("work was admitted during maintenance")
    except HTTPException as exc:
        assert exc.status_code == 503
    release.set()
    await asyncio.wait_for(task, 5)
    async with work_lease(enabled=True):
        pass
    # Cancellation must release session locks rather than poison a pooled
    # connection and block every subsequent deployment.
    started = asyncio.Event()
    async def cancelled_work():
        async with work_lease(enabled=True):
            started.set()
            await asyncio.Event().wait()
    running = asyncio.create_task(cancelled_work())
    await started.wait()
    running.cancel()
    await asyncio.gather(running, return_exceptions=True)
    async with maintenance_barrier(timeout=2):
        pass
    await engine.dispose()
    print("PASS: atomic admission, existing-work drain, reentrancy, child-task isolation, resume and cancellation cleanup")


asyncio.run(main())
