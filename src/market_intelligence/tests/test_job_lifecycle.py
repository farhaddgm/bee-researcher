import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from app import pipeline_service as pipeline
from app import runtime
from app.config import Settings


class JobLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_deferred_cleanup_does_not_starve_scheduler(self):
        stop = asyncio.Event()
        async def tick(_):
            stop.set()
            return {}
        with patch.object(runtime, "expire_abandoned_job_runs", AsyncMock(side_effect=HTTPException(503, 'busy'))), \
             patch('app.freshness_notifications.deliver_freshness_notifications', AsyncMock(return_value=0)), \
             patch.object(runtime, "STATUS", MagicMock()), \
             patch.object(runtime, "scheduler_tick", AsyncMock(side_effect=tick)) as scheduled:
            await runtime.scheduler_loop(MagicMock(scheduler_poll_seconds=1), stop)
        scheduled.assert_awaited_once()

    async def test_age_only_cleanup_without_barrier_is_deferred(self):
        with patch.object(pipeline, "get_settings", return_value=MagicMock(deployment_drain_enabled=False)), \
             patch.object(pipeline, "SessionLocal") as db:
            self.assertEqual(0, await pipeline.expire_abandoned_job_runs())
            db.assert_not_called()

    async def test_age_only_cleanup_cannot_steal_admitted_work(self):
        @asynccontextmanager
        async def blocked(**_):
            raise TimeoutError
            yield
        with patch.object(pipeline, "get_settings", return_value=MagicMock(deployment_drain_enabled=True)), \
             patch.object(pipeline, "maintenance_barrier", blocked), \
             patch.object(pipeline, "SessionLocal") as db:
            with self.assertRaises(HTTPException) as error:
                await pipeline.expire_abandoned_job_runs()
            self.assertEqual(503, error.exception.status_code)
            db.assert_not_called()

    async def test_cancelled_pipeline_records_terminal_state_and_releases_lock(self):
        cfg = Settings(environment="test", postgres_db="assistant_test", postgres_user="synthetic",
                       postgres_password="synthetic", redis_password="synthetic")
        job = uuid.uuid4()
        redis = AsyncMock()
        redis.set.return_value = True
        with patch.object(pipeline, "get_settings", return_value=cfg), \
             patch.object(pipeline, "settings_for_assistant", AsyncMock(return_value=cfg)), \
             patch.object(pipeline, "_daily_processing_count", AsyncMock(return_value=0)), \
             patch.object(pipeline, "_claim_job", AsyncMock(return_value=(job, "claimed"))), \
             patch.object(pipeline.Redis, "from_url", return_value=redis), \
             patch.object(pipeline, "run_ingestion", AsyncMock(side_effect=asyncio.CancelledError)), \
             patch.object(pipeline, "_finish_job", AsyncMock()) as finish:
            with self.assertRaises(asyncio.CancelledError):
                await pipeline.run_pipeline.__wrapped__(publish=False)
        finish.assert_awaited_once_with(job, status="cancelled", result={}, error="execution_cancelled")
        redis.eval.assert_awaited_once()
        redis.aclose.assert_awaited_once()

    async def test_recovery_requires_exclusive_barrier_before_business_query(self):
        cfg = MagicMock(deployment_drain_enabled=True)
        held = False
        @asynccontextmanager
        async def barrier(**_):
            nonlocal held
            held = True
            try:
                yield
            finally:
                held = False
        session = AsyncMock()
        session.execute.return_value = MagicMock(rowcount=1)
        @asynccontextmanager
        async def database():
            self.assertTrue(held)
            yield session
        with patch.object(pipeline, "get_settings", return_value=cfg), \
             patch.object(pipeline, "maintenance_barrier", barrier), \
             patch.object(pipeline, "SessionLocal", database):
            self.assertEqual(1, await pipeline.reconcile_jobs_before_startup(started_before=datetime.now(timezone.utc)))
        statement = str(session.execute.call_args.args[0])
        self.assertIn("finished_at IS NULL", statement)
        self.assertNotIn("result=", statement)
        self.assertNotIn("attempt=", statement)
        session.commit.assert_awaited_once()

    async def test_failed_barrier_never_marks_real_work_failed(self):
        @asynccontextmanager
        async def blocked(**_):
            raise TimeoutError
            yield
        with patch.object(pipeline, "get_settings", return_value=MagicMock(deployment_drain_enabled=True)), \
             patch.object(pipeline, "maintenance_barrier", blocked), \
             patch.object(pipeline, "SessionLocal") as db:
            with self.assertRaises(TimeoutError):
                await pipeline.reconcile_jobs_before_startup(started_before=datetime.now(timezone.utc))
            db.assert_not_called()
