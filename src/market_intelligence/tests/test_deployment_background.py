import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

from app.config import Settings
from app import contenter, pipeline_service, runtime


def settings():
    return Settings(environment="test", postgres_db="synthetic", postgres_user="synthetic",
                    postgres_password="synthetic-password", redis_password="synthetic-password",
                    telegram_bot_token="synthetic-telegram-token", telegram_channel_id="-1001234567890",
                    telegram_polling_enabled=True)


class BackgroundDeploymentTest(unittest.IsolatedAsyncioTestCase):
    async def test_closed_admission_never_polls_or_acknowledges_telegram_updates(self):
        stop = asyncio.Event()
        redis = AsyncMock()
        redis.get.return_value = None
        telegram = SimpleNamespace(get_updates=AsyncMock())

        @asynccontextmanager
        async def blocked():
            raise HTTPException(503, "maintenance")
            yield  # pragma: no cover

        async def backoff(_seconds):
            stop.set()

        with patch.object(runtime, "work_lease", blocked), patch.object(runtime, "TelegramClient", return_value=telegram), \
                patch.object(runtime.Redis, "from_url", return_value=redis), patch.object(runtime.asyncio, "sleep", side_effect=backoff):
            await runtime.telegram_feedback_loop(settings(), stop)
        telegram.get_updates.assert_not_awaited()
        redis.set.assert_not_awaited()
        redis.aclose.assert_awaited_once()

    async def test_admitted_telegram_cycle_holds_lease_until_offset_is_committed(self):
        stop = asyncio.Event()
        held = {"value": False}
        redis = AsyncMock()
        redis.get.return_value = None

        @asynccontextmanager
        async def lease():
            held["value"] = True
            try:
                yield
            finally:
                held["value"] = False

        async def updates(_offset):
            self.assertTrue(held["value"])
            return [{"update_id": 41}]

        async def commit_offset(_key, value):
            self.assertTrue(held["value"])
            self.assertEqual(value, "42")
            stop.set()

        telegram = SimpleNamespace(get_updates=AsyncMock(side_effect=updates))
        redis.set.side_effect = commit_offset
        with patch.object(runtime, "work_lease", lease), patch.object(runtime, "TelegramClient", return_value=telegram), \
                patch.object(runtime.Redis, "from_url", return_value=redis), patch.object(runtime.STATUS, "last_feedback_update_id", None):
            await runtime.telegram_feedback_loop(settings(), stop)
        self.assertFalse(held["value"])
        telegram.get_updates.assert_awaited_once_with(None)
        redis.set.assert_awaited_once()

    async def test_contenter_sync_and_job_recovery_reject_before_business_queries(self):
        connection = AsyncMock()
        connection.scalar.return_value = False
        cfg = settings().model_copy(update={"deployment_drain_enabled": True})
        with patch("app.deployment_drain.get_settings", return_value=cfg), \
                patch("app.deployment_drain._connect", AsyncMock(return_value=connection)), \
                patch.object(contenter, "SessionLocal", Mock()) as contenter_db, \
                patch.object(pipeline_service, "SessionLocal", Mock()) as jobs_db:
            for operation in (contenter.sync_link(uuid.uuid4(), cfg), pipeline_service.expire_abandoned_job_runs()):
                with self.assertRaises(HTTPException) as error:
                    await operation
                self.assertEqual(error.exception.status_code, 503)
            contenter_db.assert_not_called()
            jobs_db.assert_not_called()
