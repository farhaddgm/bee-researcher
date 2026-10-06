"""Exercise 0043 upgrade/rollback on an isolated migrated test database only."""
import asyncio
import hashlib
import subprocess
import uuid

from sqlalchemy import text
from app.config import get_settings
from app.database import engine


TABLES = ("admin_users", "assistant_workspaces", "assistant_members", "sources", "topics", "publications")


async def snapshot():
    async with engine.connect() as c:
        return {table: tuple((await c.execute(text(f"SELECT id FROM market_intelligence.{table} ORDER BY id"))).scalars()) for table in TABLES}


def migrate(revision, *, downgrade=False):
    subprocess.run(["alembic", "downgrade" if downgrade else "upgrade", revision], check=True, capture_output=True)


async def main():
    cfg = get_settings()
    if cfg.environment != "test" or cfg.postgres_db != "assistant_test" or cfg.google_login_ready or cfg.openai_ready or cfg.telegram_ready or cfg.scheduler_enabled:
        raise RuntimeError("Migration test refuses live databases and configured external providers")
    before = await snapshot()
    assert before["admin_users"], "Run account integration/login first to seed synthetic users"
    user_id = before["admin_users"][0]
    migrate("0042_research_context", downgrade=True)
    async with engine.begin() as c:
        # Legacy rows are indistinguishable: both must be revoked on upgrade.
        for n in range(2):
            await c.execute(text("INSERT INTO market_intelligence.admin_sessions (id,user_id,token_hash,expires_at,mfa_verified) VALUES (:id,:uid,:hash,now()+interval '30 days',true)"),
                {"id": uuid.uuid4(), "uid": user_id, "hash": hashlib.sha256(("synthetic-legacy-" + str(n)).encode()).hexdigest()})
    migrate("head")
    assert await snapshot() == before, "Migration changed accounts, project grants or product data"
    async with engine.begin() as c:
        assert await c.scalar(text("SELECT count(*) FROM market_intelligence.admin_sessions")) == 0
        for portal in ("admin", "user"):
            await c.execute(text("INSERT INTO market_intelligence.admin_sessions (id,user_id,token_hash,expires_at,mfa_verified,portal) VALUES (:id,:uid,:hash,now()+interval '30 days',true,:portal)"),
                {"id": uuid.uuid4(), "uid": user_id, "hash": hashlib.sha256(("synthetic-new-" + portal).encode()).hexdigest(), "portal": portal})
    migrate("0042_research_context", downgrade=True)
    async with engine.connect() as c:
        rows = tuple((await c.execute(text("SELECT token_hash FROM market_intelligence.admin_sessions"))).scalars())
        assert hashlib.sha256(b"synthetic-new-user").hexdigest() not in rows, "Rollback retained a User token as an Admin token"
        assert hashlib.sha256(b"synthetic-new-admin").hexdigest() in rows
    migrate("head")
    assert await snapshot() == before
    await engine.dispose()
    print("Migration 0043 passed: upgrade and rollback, old-token revocation, User-token removal on rollback; accounts, grants, projects, sources, topics and publications preserved.")


if __name__ == "__main__":
    asyncio.run(main())
