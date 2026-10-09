"""Real SQL/lease proof, refusing any production database or scheduler."""
import asyncio
from datetime import datetime, timedelta, timezone
import uuid
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from app.config import get_settings
from app.database import SessionLocal, engine
from app.deployment_drain import engine as lease_engine, work_lease
from app.models import JobRun
from app.pipeline_service import reconcile_jobs_before_startup


async def main():
    cfg = get_settings()
    if cfg.environment != 'test' or cfg.postgres_db != 'news_chat_test' or cfg.scheduler_enabled:
        raise RuntimeError('Isolated synthetic database required')
    cutoff = datetime.now(timezone.utc)
    old, new = uuid.uuid4(), uuid.uuid4()
    retained = {'input_chars': 37, 'paid_reservation': 'synthetic'}
    async with SessionLocal() as session:
        for jid, start in ((old, cutoff-timedelta(hours=2)), (new, cutoff+timedelta(minutes=1))):
            session.add(JobRun(id=jid, assistant_id=uuid.UUID('10000000-0000-4000-8000-000000000001'),
                job_type='recovery_test', status='running', started_at=start, scheduled_for=start,
                idempotency_key='recovery-test:'+str(jid), attempt=3, result=retained))
        await session.commit()
    async with work_lease(enabled=True):
        try:
            await reconcile_jobs_before_startup(started_before=cutoff)
        except TimeoutError:
            pass
        else:
            raise AssertionError('A live work lease was stolen')
        async with SessionLocal() as session:
            assert (await session.get(JobRun, old)).status == 'running'
    assert await reconcile_jobs_before_startup(started_before=cutoff) >= 1
    async with SessionLocal() as session:
        rows = (await session.scalars(select(JobRun).where(JobRun.id.in_([old, new])))).all()
        by_id = {row.id:row for row in rows}
        assert by_id[old].status == 'failed' and by_id[old].finished_at is not None
        assert by_id[old].error_message == 'execution_interrupted_before_boot'
        assert by_id[old].result == retained and by_id[old].attempt == 3
        assert by_id[new].status == 'running' and by_id[new].finished_at is None
    print('Job recovery SQL passed: live lease protected; orphan terminal; new work preserved; spend/attempt ledger retained.')


async def run():
    try:
        await main()
    finally:
        await engine.dispose()
        await lease_engine.dispose()


if __name__ == '__main__':
    asyncio.run(run())
