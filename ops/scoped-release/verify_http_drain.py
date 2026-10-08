"""Real SQL/HTTP acceptance, isolated test environment only; no business data."""
import asyncio
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.deployment_drain import engine, maintenance_barrier, work_lease
from app.main import deployment_admission
from app.runtime import STATUS, runtime_readiness


async def main():
    settings = get_settings()
    assert settings.environment == "test" and settings.deployment_drain_enabled
    application = FastAPI()
    application.middleware("http")(deployment_admission)
    started, finish, drained, release = [asyncio.Event() for _ in range(4)]
    scheduler_settings = settings.model_copy(update={"scheduler_enabled": True, "telegram_polling_enabled": False})

    @application.get("/ready")
    async def ready():
        payload = runtime_readiness(scheduler_settings)
        return JSONResponse(payload, status_code=200 if payload["ready"] else 503)

    @application.get("/read")
    async def read():
        return {"ok": True}

    @application.post("/write")
    async def write(slow: bool = False):
        if slow:
            started.set()
            await finish.wait()
        return {"ok": True}

    async def drain():
        async with maintenance_barrier(timeout=5):
            drained.set()
            await release.wait()

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://isolated.test") as client:
        assert (await client.post("/write")).status_code == 200
        running = asyncio.create_task(client.post("/write?slow=true"))
        await asyncio.wait_for(started.wait(), 3)
        barrier = asyncio.create_task(drain())
        for _ in range(100):
            response = await client.post("/write")
            if response.status_code == 503:
                assert response.headers["Retry-After"] == "30"
                break
            await asyncio.sleep(.01)
        else:
            raise AssertionError("HTTP admission did not close")
        assert not drained.is_set()
        assert (await client.get("/read")).status_code == 200
        finish.set()
        assert (await asyncio.wait_for(running, 3)).status_code == 200
        await asyncio.wait_for(drained.wait(), 3)
        assert (await client.post("/write")).status_code == 503
        # Reproduce a fresh scheduler under the cross-process barrier using
        # the production readiness calculation and actual PostgreSQL leases.
        # A deployment must not await this first heartbeat before admission
        # is released: that creates a circular wait, despite healthy reads.
        previous = STATUS.scheduler_running, STATUS.last_scheduler_tick
        STATUS.scheduler_running, STATUS.last_scheduler_tick = True, None
        async def first_tick():
            async with work_lease(enabled=True):
                STATUS.last_scheduler_tick = datetime.now(timezone.utc).isoformat()
        try:
            try:
                await asyncio.create_task(first_tick())
            except HTTPException as exc:
                assert exc.status_code == 503
            else:
                raise AssertionError("scheduler was admitted during maintenance")
            assert (await client.get("/read")).status_code == 200
            assert (await client.get("/ready")).status_code == 503
            release.set()
            await asyncio.wait_for(barrier, 3)
            await asyncio.create_task(first_tick())
            assert (await client.get("/ready")).status_code == 200
        finally:
            STATUS.scheduler_running, STATUS.last_scheduler_tick = previous
        assert (await client.post("/write")).status_code == 200
    await engine.dispose()
    print("PASS: actual HTTP/SQL admission, existing-work drain, write rejection, cold-scheduler readiness handshake and recovery")


asyncio.run(main())
