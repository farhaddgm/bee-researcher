"""Real SQL/HTTP acceptance, isolated test environment only; no business data."""
import asyncio

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.deployment_drain import engine, maintenance_barrier
from app.main import deployment_admission


async def main():
    settings = get_settings()
    assert settings.environment == "test" and settings.deployment_drain_enabled
    application = FastAPI()
    application.middleware("http")(deployment_admission)
    started, finish, drained, release = [asyncio.Event() for _ in range(4)]

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
        release.set()
        await asyncio.wait_for(barrier, 3)
        assert (await client.post("/write")).status_code == 200
    await engine.dispose()
    print("PASS: actual HTTP middleware, existing request completion, write rejection, read availability and recovery")


asyncio.run(main())
