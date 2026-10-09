"""The web process must never start with an administrative database role."""
import asyncio
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from app.database import engine
from app.config import get_settings


def packaged_schema_head() -> str:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if not head:
        raise RuntimeError("packaged schema head is missing")
    return head


async def check_runtime_permissions():
    if get_settings().environment.strip().lower() != "production":
        return
    try:
        async with engine.connect() as connection:
            role = (await connection.execute(text("""SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls
                FROM pg_catalog.pg_roles WHERE rolname = current_user"""))).one()
            if any(role):
                raise RuntimeError("web runtime database role has administrative privileges")
            if await connection.scalar(text("SELECT has_schema_privilege(current_user, 'market_intelligence', 'CREATE')")):
                raise RuntimeError("web runtime must not own or create schema objects")
            for permission in ("UPDATE", "DELETE", "TRUNCATE"):
                if await connection.scalar(text("SELECT has_table_privilege(current_user, 'market_intelligence.security_events', :permission)"), {"permission": permission}):
                    raise RuntimeError("web runtime must only append security events")
            revision = await connection.scalar(text("SELECT version_num FROM market_intelligence.alembic_version"))
            if revision != packaged_schema_head():
                raise RuntimeError("run the separate migration job before starting this release")
            for table in ("news_chat_policy", "news_chat_conversations", "news_chat_generations"):
                for permission in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    if not await connection.scalar(text("SELECT has_table_privilege(current_user, :table, :permission)"),
                            {"table": "market_intelligence." + table, "permission": permission}):
                        raise RuntimeError("web runtime is missing required chat table privileges")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check_runtime_permissions())
    print("Researcher runtime privilege preflight passed")
