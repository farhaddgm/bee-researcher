"""Seed least-privileged startup identities in an isolated test database only."""
import asyncio
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from app.config import get_settings
from app.database import engine

async def main():
    cfg=get_settings()
    if cfg.environment!='test' or cfg.postgres_db!='news_chat_test' or not cfg.postgres_host.startswith('bee-news-chat-pg-'):
        raise RuntimeError('isolated startup fixture database required')
    async with engine.begin() as connection:
        await connection.execute(text("CREATE ROLE startup_fixture LOGIN PASSWORD 'synthetic-startup-database-fixture' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"))
        await connection.execute(text('GRANT USAGE ON SCHEMA market_intelligence TO startup_fixture'))
        await connection.execute(text('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA market_intelligence TO startup_fixture'))
        await connection.execute(text('REVOKE UPDATE, DELETE ON market_intelligence.security_events FROM startup_fixture'))
        await connection.execute(text('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA market_intelligence TO startup_fixture'))
    await engine.dispose()
    print('Isolated least-privileged startup role seeded; no live database touched.')

if __name__=='__main__':asyncio.run(main())
