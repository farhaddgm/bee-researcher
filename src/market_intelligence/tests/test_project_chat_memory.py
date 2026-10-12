import unittest
import uuid
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.news_chat import api


class ProjectMemoryHttpTests(unittest.TestCase):
    def test_saved_memory_mutations_keep_session_bound_csrf(self):
        client = TestClient(app)
        client.cookies.set("research_bee_user_session", "synthetic-token")
        for method in (client.put, client.delete):
            response = method(f"/user/api/conversations/{uuid.uuid4()}/memory")
            self.assertEqual(403, response.status_code)

    def test_microphone_permission_is_scoped_to_the_reader(self):
        client = TestClient(app)
        for path in ("/user", "/user/login-up", f"/user/news/{uuid.uuid4()}"):
            self.assertIn("microphone=(self)", client.get(path).headers["Permissions-Policy"])
        for path in ("/admin", "/health", "/report"):
            self.assertIn("microphone=()", client.get(path).headers["Permissions-Policy"])


class ProjectMemoryAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_memory_list_refuses_a_project_outside_reader_membership(self):
        with patch.object(api.admin, "current_reader", new=AsyncMock(return_value=object())), \
             patch.object(api.svc, "require"), \
             patch.object(api.admin, "reader_assistants", new=AsyncMock(return_value={"assistants": [{"id": str(uuid.uuid4())}]})), \
             patch.object(api, "SessionLocal") as database:
            with self.assertRaises(HTTPException) as raised:
                await api.project_memory(uuid.uuid4(), token="synthetic-token")
            self.assertEqual(404, raised.exception.status_code)
            database.assert_not_called()

    async def test_memory_save_and_remove_use_conversation_owner_authorization(self):
        for action in (api.save_memory, api.unsave_memory):
            with self.subTest(action=action.__name__), \
                 patch.object(api.admin, "current_reader", new=AsyncMock(return_value=object())), \
                 patch.object(api.svc, "conversation", new=AsyncMock(side_effect=HTTPException(404, "news_unavailable"))), \
                 patch.object(api, "SessionLocal"):
                with self.assertRaises(HTTPException) as raised:
                    await action(uuid.uuid4(), token="synthetic-token")
                self.assertEqual(404, raised.exception.status_code)
