import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.deployment_drain import maintenance_barrier, work_lease


class DeploymentDrainTest(unittest.IsolatedAsyncioTestCase):
    async def test_work_is_reentrant_only_within_its_own_task(self):
        connection = AsyncMock()
        connection.scalar.return_value = True
        connect = AsyncMock(return_value=connection)
        with patch("app.deployment_drain._connect", connect):
            async with work_lease(enabled=True):
                async with work_lease(enabled=True):
                    self.assertEqual(1, connect.await_count)
                async def child():
                    async with work_lease(enabled=True):
                        pass
                await asyncio.create_task(child())
                self.assertEqual(2, connect.await_count)
        self.assertEqual(0, connection.invalidate.await_count)
        self.assertEqual(2, connection.close.await_count)

    async def test_closed_admission_rejects_before_work_and_cleans_connection(self):
        connection = AsyncMock()
        connection.scalar.return_value = False
        with patch("app.deployment_drain._connect", AsyncMock(return_value=connection)):
            with self.assertRaises(HTTPException) as error:
                async with work_lease(enabled=True):
                    self.fail("closed gate admitted work")
        self.assertEqual(503, error.exception.status_code)
        self.assertEqual(1, connection.scalar.await_count)
        connection.invalidate.assert_not_awaited()
        connection.close.assert_awaited_once()

    async def test_work_exception_and_drain_exception_release_session_locks(self):
        for context in (work_lease(enabled=True), maintenance_barrier(timeout=1)):
            connection = AsyncMock()
            connection.scalar.return_value = True
            with patch("app.deployment_drain._connect", AsyncMock(return_value=connection)):
                with self.assertRaises(ValueError):
                    async with context:
                        raise ValueError("synthetic operation failure")
            connection.invalidate.assert_not_awaited()
            connection.close.assert_awaited_once()

    async def test_synthetic_tests_can_run_without_database(self):
        with patch("app.deployment_drain._connect", AsyncMock()) as connect:
            async with work_lease(enabled=False):
                pass
            connect.assert_not_awaited()
