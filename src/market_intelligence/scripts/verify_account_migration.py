"""The additive security journal is a permanent migration floor."""
import asyncio
import subprocess
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from app.config import get_settings
from app.database import engine

TABLES = ("admin_users", "assistant_workspaces", "assistant_members", "sources", "topics", "publications",
          "security_events", "news_chat_generations")


def packaged_head():
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()

async def snapshot():
    async with engine.connect() as connection:
        return {table: tuple((await connection.execute(text(f"SELECT id FROM market_intelligence.{table} ORDER BY id"))).scalars()) for table in TABLES}

async def main():
    cfg = get_settings()
    if cfg.environment != "test" or cfg.postgres_db != "assistant_test" or cfg.google_login_ready or cfg.openai_ready or cfg.telegram_ready or cfg.scheduler_enabled:
        raise RuntimeError("Migration test refuses live databases and configured providers")
    before = await snapshot()
    subprocess.run(["alembic", "upgrade", "head"], check=True, capture_output=True)
    refused = subprocess.run(["alembic", "downgrade", "0042_research_context"], capture_output=True)
    assert refused.returncode != 0, "Automatic rollback must never drop security history"
    async with engine.connect() as connection:
        assert await connection.scalar(text("SELECT version_num FROM market_intelligence.alembic_version")) == packaged_head()
        assert await connection.scalar(text("SELECT to_regclass('market_intelligence.security_events')"))
        assert await connection.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_schema='market_intelligence' AND table_name='admin_sessions' AND column_name='portal'")) == 1
    assert await snapshot() == before
    await engine.dispose()
    print("Migration floor passed: exact packaged head retained, destructive downgrade refused, journal/chat consumption and portal isolation retained, account/project/content IDs preserved. Image rollback uses the separate release command.")

if __name__ == "__main__":
    asyncio.run(main())
