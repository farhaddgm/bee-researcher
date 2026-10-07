"""The web process must never start with an administrative database role."""
import asyncio
from sqlalchemy import text
from app.database import engine
from app.config import get_settings


async def check_runtime_permissions():
    if get_settings().environment.strip().lower() != "production":
        return
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
        if revision != "0044_security_events":
            raise RuntimeError("run the separate migration job before starting this release")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check_runtime_permissions())
    print("Researcher runtime privilege preflight passed")
