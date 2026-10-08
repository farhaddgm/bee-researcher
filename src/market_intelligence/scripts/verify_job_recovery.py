"""Orphaned job reconciliation against real isolated SQL, never production."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.config import get_settings
from app.database import SessionLocal, engine
from app.models import AssistantWorkspace, JobRun
from app.pipeline_service import expire_abandoned_job_runs


async def main():
    cfg = get_settings()
    if cfg.environment != "test" or cfg.postgres_db != "assistant_test" or cfg.openai_ready or cfg.telegram_ready or cfg.scheduler_enabled:
        raise RuntimeError("Refusing non-isolated environment or configured external providers")
    aid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    rows = [("old", "running", now - timedelta(days=2), None),
            ("fresh", "running", now - timedelta(minutes=5), None),
            ("boundary", "running", now - timedelta(days=1), None),
            ("finished", "succeeded", now - timedelta(days=2), now - timedelta(days=1))]
    try:
        async with SessionLocal() as session:
            session.add(AssistantWorkspace(id=aid, slug="recovery-" + aid.hex, name="Synthetic recovery", business_name="", status="draft", config={}))
            await session.flush()
            for name, status, started, finished in rows:
                session.add(JobRun(assistant_id=aid, job_type="relevance_model", status=status,
                    idempotency_key=f"recovery:{aid}:{name}", scheduled_for=started, started_at=started,
                    created_at=started, finished_at=finished, attempt=1, result={"input_chars": 123, "fixture": name}))
            await session.commit()
        await expire_abandoned_job_runs(now=now)
        async with SessionLocal() as session:
            results = (await session.scalars(select(JobRun).where(JobRun.assistant_id == aid))).all()
            jobs = {row.result["fixture"]: row for row in results}
            assert jobs["old"].status == "failed" and jobs["old"].finished_at == now
            assert jobs["old"].error_message == "abandoned_execution_expired"
            assert jobs["fresh"].status == jobs["boundary"].status == "running"
            assert jobs["finished"].status == "succeeded"
            assert all(row.result["input_chars"] == 123 and row.attempt == 1 for row in results), "Budget accounting or attempt history was reset"
        assert await expire_abandoned_job_runs(now=now) == 0, "Reconciliation was not idempotent"
        print("Job recovery SQL passed: old/fresh/boundary/finished states, preserved budget ledger, idempotency; no rescheduling or delivery")
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(AssistantWorkspace).where(AssistantWorkspace.id == aid))
            await session.commit()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
