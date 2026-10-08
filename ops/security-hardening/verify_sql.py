"""Runs only in the isolated restored database, never against production."""
import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app import admin
from app.config import get_settings
from app.database import engine, SessionLocal
from app.models import AdminUser, AdminSession, SecurityEvent
from app.security_controls import login_attempts_exceeded, login_attempt_key
from app.security_events import record_security_event

settings = get_settings()
assert settings.environment == 'test' and settings.postgres_db == 'assistant_test'
assert not settings.scheduler_enabled and not settings.telegram_ready and not settings.openai_ready


async def checks():
    async with engine.connect() as c:
        role = (await c.execute(text('SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user'))).one()
        assert not any(role)
        assert not await c.scalar(text("SELECT has_schema_privilege(current_user,'market_intelligence','CREATE')"))
        assert await c.scalar(text("SELECT has_table_privilege(current_user,'market_intelligence.admin_users','UPDATE')"))
        assert not await c.scalar(text("SELECT has_table_privilege(current_user,'market_intelligence.security_events','DELETE')"))
    for statement in ('CREATE TABLE market_intelligence.forbidden(id int)',
                      'UPDATE market_intelligence.security_events SET action=action',
                      'DELETE FROM market_intelligence.security_events',
                      'TRUNCATE market_intelligence.security_events',
                      "UPDATE market_intelligence.alembic_version SET version_num='fake'",
                      'SET ROLE bee_researcher_migrator'):
        try:
            async with engine.begin() as c:
                await c.execute(text(statement))
        except DBAPIError:
            pass
        else:
            raise AssertionError('runtime unexpectedly allowed a privileged statement')
    uid = uuid.uuid4()
    async with SessionLocal() as s:
        from sqlalchemy import delete
        await s.execute(delete(AdminUser).where(AdminUser.email == settings.owner_email))
        s.add(AdminUser(id=uid, username='security-fixture-owner', email=settings.owner_email,
            password_hash=await admin.hash_password_async('violet herons cross mountain lakes'),
            role='admin', active=True, login_method='both', preferences={'user_portal_access': {'enabled': True, 'feedback_enabled': True}}))
        await s.commit()
    assert await admin.canonical_login_identity('security-fixture-owner') == await admin.canonical_login_identity(settings.owner_email)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    assert await redis.ping()
    key = 'market-intelligence:security:integration:allowed'
    await redis.set(key, 'yes', ex=60)
    assert await redis.get(key) == 'yes'
    for command in [('GET', 'another-service:secret'), ('SET','another-service:secret','no'), ('CONFIG','GET','*'),
                    ('ACL','LIST'), ('FLUSHDB',), ('SCAN','0')]:
        try:
            await redis.execute_command(*command)
        except ResponseError:
            pass
        else:
            raise AssertionError('Redis ACL unexpectedly allowed a forbidden command/key')
    assert login_attempt_key(settings, 'account:fixture', 'client-a') == login_attempt_key(settings, 'account:fixture', 'client-b')
    admitted = await asyncio.gather(*(login_attempts_exceeded(settings, 'account:concurrency:'+str(uid), f'client-{uid}-{i}') for i in range(100)))
    assert admitted.count(False) == settings.login_max_attempts
    assert admitted.count(True) == 100-settings.login_max_attempts
    # Corrupt counters and connection errors both fail closed.
    await redis.set(login_attempt_key(settings,'account:corrupt','x'), 'corrupt', ex=60)
    assert await login_attempts_exceeded(settings,'account:corrupt','x')
    await record_security_event('integration.append_only', actor_id=uid, severity='warning', details={'reason': 'fixture', 'password': 'must-not-persist'})
    async with SessionLocal() as s:
        event = await s.scalar(select(SecurityEvent).where(SecurityEvent.action == 'integration.append_only'))
        assert event and 'password' not in event.details
    await redis.aclose()
    await engine.dispose()
    print('PASS: runtime privileges, schema/role/migration denial, immutable journal, Redis ACL, canonical aliases, 100 concurrent logins and corrupt-counter denial')


asyncio.run(checks())

from app.main import app
with TestClient(app, base_url='https://testserver') as client:
    login = client.post('/admin/api/login', json={'username': 'security-fixture-owner', 'password': 'violet herons cross mountain lakes'})
    assert login.status_code == 200, login.status_code
    assert client.get('/admin/api/me').status_code == 200
    csrf = client.cookies['research_bee_admin_csrf']
    assert client.put('/admin/api/account/preferences', json={'theme':'dark'}).status_code == 403
    assert client.put('/admin/api/account/preferences', json={'theme':'dark'}, headers={'X-CSRF-Token':csrf}).status_code == 200
    reader = client.post('/user/api/login', json={'username': settings.owner_email, 'password': 'violet herons cross mountain lakes'})
    assert reader.status_code == 200
    reader_csrf = client.cookies['research_bee_user_csrf']
    assert client.patch('/user/api/preferences', json={}).status_code == 403
    assert client.patch('/user/api/preferences', json={}, headers={'X-CSRF-Token': reader_csrf}).status_code == 200
    assert client.post('/user/api/logout', headers={'X-CSRF-Token': reader_csrf}).status_code == 200
    raw = client.cookies['research_bee_admin_session']

    async def expire():
        async with SessionLocal() as s:
            row = await s.scalar(select(AdminSession).where(AdminSession.token_hash==hashlib.sha256(raw.encode()).hexdigest()))
            row.created_at = datetime.now(timezone.utc)-timedelta(hours=13)
            row.expires_at = datetime.now(timezone.utc)+timedelta(days=30)
            await s.commit()
        await engine.dispose()
    client.portal.call(expire)
    assert client.get('/admin/api/me', headers={'X-User-Activity':'1'}).status_code == 401
print('PASS: actual password login in both portals, admin/User CSRF with missing Origin, preferences, logout and absolute expiration despite activity')
