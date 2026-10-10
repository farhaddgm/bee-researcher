"""Synthetic persisted rows for the isolated browser pagination gate."""
import asyncio
import uuid

from sqlalchemy import func, select

from app.config import get_settings
from app.database import SessionLocal, engine
from app.login_history import ACTION, record_login_attempt
from app.models import SecurityEvent


async def run():
    cfg = get_settings()
    if cfg.environment != "test" or cfg.postgres_db != "assistant_test":
        raise RuntimeError("Refusing to seed a non-test database")
    suffix = uuid.uuid4().hex
    for index in range(12):
        await record_login_attempt(method="google", portal="admin" if index % 2 else "user",
            successful=index % 3 == 0, email=f"history{suffix}{index}@gmail.com",
            reason="not_allowed" if index % 3 else None)
    async with SessionLocal() as session:
        count = await session.scalar(select(func.count()).select_from(SecurityEvent).where(
            SecurityEvent.action == ACTION, SecurityEvent.details["email"].astext.startswith("history" + suffix)))
    await engine.dispose()
    assert count == 12, "Synthetic login history was not persisted"
    print("Twelve synthetic sign-in outcomes persisted for browser pagination.")


if __name__ == "__main__":
    asyncio.run(run())
