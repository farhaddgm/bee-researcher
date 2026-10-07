import asyncio
import hashlib
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException


# Keep unittest discovery reproducible outside CI too.  This module imports
# app.admin directly (before test_main can seed the settings environment), so
# provide the same harmless test-only defaults at module import time.
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_DB", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_USER", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_REDIS_PASSWORD", "test-password")

from pydantic import SecretStr, ValidationError

from app.admin import (
    DEFAULT_ASSISTANT_ID,
    AdminUserManageUpdate,
    AdminUserPasswordUpdate,
    AdminUserRequest,
    AssistantRuntimeSettingsUpdate,
    AssistantLimitsUpdate,
    AccountPreferencesUpdate,
    TelegramSettingsUpdate,
    _telegram_config,
    _dedupe_admin_rows,
    assistant_limits,
    _admin_session_idle_hours,
    _reader_nightly_expiry,
    can_view_admin_user,
    public_social_source_config,
    workspace_delete_allowed,
    workspace_write_allowed,
    user_portal_access_payload,
    user_portal_access_allowed,
    user_feedback_access_allowed,
    UserPortalAccessUpdate,
    current_reader,
    list_admin_incidents,
)


class AdminWorkspaceSecurityTest(unittest.TestCase):
    def test_public_social_source_config_is_server_built_and_credential_free(self):
        telegram = public_social_source_config("telegram", "https://t.me/s/example_channel")
        self.assertEqual("telegram_public", telegram["adapter"])
        self.assertEqual("https://t.me/s/example_channel", telegram["fetch_url"])
        self.assertIsNone(telegram["credential_ref"])
        instagram = public_social_source_config("instagram", "@public.profile")
        self.assertEqual("instagram_public", instagram["adapter"])
        self.assertIn("business_discovery.username(public.profile)", str(instagram["fetch_url"]))
        self.assertNotIn("access_token", str(instagram["fetch_url"]).lower())
        with self.assertRaises(ValueError):
            public_social_source_config("x", "https://x.com/user?access_token=leak")

    def test_account_theme_choices_include_new_palettes_and_remove_bee_blue(self):
        self.assertEqual("default", AccountPreferencesUpdate(theme="default").theme)
        self.assertEqual("red", AccountPreferencesUpdate(theme="red").theme)
        self.assertEqual("blackyellow", AccountPreferencesUpdate(theme="blackyellow").theme)
        with self.assertRaises(ValidationError):
            AccountPreferencesUpdate(theme="bee")

    def test_project_limits_have_safe_defaults_and_bounds(self):
        self.assertEqual(10, assistant_limits({})["max_sources"])
        self.assertEqual(7, assistant_limits({})["max_items_per_run"])
        payload = AssistantLimitsUpdate(
            max_sources=25,
            max_topics=40,
            max_freshness_window_days=7,
            max_items_per_run=5,
            max_business_profiles=8,
            max_projects_per_user=20,
        )
        self.assertEqual(25, payload.max_sources)
        with self.assertRaises(ValidationError):
            AssistantLimitsUpdate(max_sources=0, max_topics=1, max_freshness_window_days=1, max_items_per_run=1, max_business_profiles=1, max_projects_per_user=1)
    def test_admin_session_idle_timeout_is_hard_capped_at_six_hours(self):
        with patch("app.admin.get_settings", return_value=SimpleNamespace(admin_session_ttl_hours=12)):
            self.assertEqual(6, _admin_session_idle_hours())
        with patch("app.admin.get_settings", return_value=SimpleNamespace(admin_session_ttl_hours=4)):
            self.assertEqual(4, _admin_session_idle_hours())

    def test_reader_sessions_end_at_the_next_two_am_service_cutoff(self):
        with patch("app.admin.get_settings", return_value=SimpleNamespace(timezone="Europe/Berlin")):
            # 01:30 local on 30 August: the session ends at 02:00 local.
            created_before_cutoff = datetime(2026, 8, 29, 23, 30, tzinfo=timezone.utc)
            self.assertEqual(datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc), _reader_nightly_expiry(created_before_cutoff))
            # 02:30 local: it receives the following day's 02:00 boundary.
            created_after_cutoff = datetime(2026, 8, 30, 0, 30, tzinfo=timezone.utc)
            self.assertEqual(datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc), _reader_nightly_expiry(created_after_cutoff))

    def test_reader_cutoff_is_stable_across_daylight_saving_transitions(self):
        with patch("app.admin.get_settings", return_value=SimpleNamespace(timezone="Europe/Berlin")):
            # The spring transition skips 02:00; the zone-aware boundary
            # resolves to the first real instant after the gap (03:00 CEST).
            spring_before = datetime(2026, 3, 29, 0, 30, tzinfo=timezone.utc)
            self.assertEqual(datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc), _reader_nightly_expiry(spring_before))
            spring_after = datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc)
            self.assertEqual(datetime(2026, 3, 30, 0, 0, tzinfo=timezone.utc), _reader_nightly_expiry(spring_after))

            # During the fall overlap, 02:00 resolves to its first occurrence;
            # sessions created during the second occurrence go to tomorrow.
            fall_before = datetime(2026, 10, 24, 23, 30, tzinfo=timezone.utc)
            self.assertEqual(datetime(2026, 10, 25, 0, 0, tzinfo=timezone.utc), _reader_nightly_expiry(fall_before))
            fall_after = datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc)
            self.assertEqual(datetime(2026, 10, 26, 1, 0, tzinfo=timezone.utc), _reader_nightly_expiry(fall_after))

    def test_reader_session_rejects_nightly_expiry_even_with_future_idle_deadline(self):
        raw_token = "reader-session-e2e-token"
        now = datetime.now(timezone.utc)
        session_row = SimpleNamespace(
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            created_at=now - timedelta(days=2),
            expires_at=now + timedelta(hours=2),
        )
        reader = SimpleNamespace(
            id=uuid.uuid4(), username="owner-account", email="owner@gmail.com", role="admin", active=True,
            preferences={},
        )

        class Result:
            def one_or_none(self):
                return session_row, reader

        class Session:
            def __init__(self):
                self.delete = AsyncMock()
                self.commit = AsyncMock()

            async def execute(self, _statement):
                return Result()

        session = Session()

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *_args):
                return None

        settings = SimpleNamespace(
            timezone="Europe/Berlin",
            owner_email="owner@gmail.com",
            admin_session_ttl_hours=6, session_absolute_hours=12,
        )
        with (
            patch("app.admin.SessionLocal", return_value=SessionContext()),
            patch("app.admin.get_settings", return_value=settings),
        ):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(current_reader(raw_token))
        self.assertEqual(401, raised.exception.status_code)
        self.assertEqual("session expired", raised.exception.detail)
        session.delete.assert_awaited_once_with(session_row)
        session.commit.assert_awaited_once()

    def test_owner_incident_feed_surfaces_stale_collection_independently_of_readiness(self):
        now = datetime.now(timezone.utc)
        stale_no_run = SimpleNamespace(
            id=uuid.uuid4(), name="Legacy Dotin", deleted_at=None, status="active", config={},
        )
        stale_old_run = SimpleNamespace(
            id=uuid.uuid4(), name="Older workspace", deleted_at=None, status="active", config={},
        )
        newly_configured = SimpleNamespace(
            id=uuid.uuid4(), name="New source grace period", deleted_at=None, status="active", config={},
        )
        disabled = SimpleNamespace(
            id=uuid.uuid4(), name="Collection disabled", deleted_at=None, status="active",
            config={"runtime": {"collection_enabled": False}},
        )

        class Result:
            def __init__(self, *, values=None, scalar=None):
                self.values = values
                self.scalar = scalar

            def scalars(self):
                return self

            def all(self):
                return self.values

            def scalar_one(self):
                return self.scalar

            def scalar_one_or_none(self):
                return self.scalar

        class Session:
            def __init__(self):
                self.responses = [
                    Result(values=[stale_no_run, stale_old_run, newly_configured, disabled]),
                    Result(values=[
                        (stale_no_run.id, 1, now - timedelta(hours=37)),
                        (stale_old_run.id, 1, now - timedelta(hours=60)),
                        (newly_configured.id, 1, now - timedelta(hours=2)),
                    ]),
                    Result(values=[(stale_old_run.id, now - timedelta(hours=37))]),
                ]

            async def execute(self, _statement):
                return self.responses.pop(0)

        class SessionContext:
            async def __aenter__(self):
                return Session()

            async def __aexit__(self, *_args):
                return None

        owner = SimpleNamespace(username="owner-account", email="owner@gmail.com", role="admin", id=uuid.uuid4())
        with (
            patch("app.admin.list_admin_notifications", new=AsyncMock(return_value={"notifications": []})),
            patch("app.security_events.security_incidents", new=AsyncMock(return_value=[])),
            patch("app.admin._visible_project_scope_ids", new=AsyncMock(return_value=None)),
            patch("app.admin.SessionLocal", return_value=SessionContext()),
            patch("app.admin.get_settings", return_value=SimpleNamespace(owner_email="owner@gmail.com")),
        ):
            response = asyncio.run(list_admin_incidents(owner))
        freshness = {item["assistant_name"]: item for item in response["incidents"]}
        self.assertEqual(2, response["open"])
        self.assertEqual("critical", freshness["Legacy Dotin"]["severity"])
        self.assertIsNone(freshness["Legacy Dotin"]["last_success_at"])
        self.assertEqual("warning", freshness["Older workspace"]["severity"])
        self.assertNotIn("New source grace period", freshness)
        self.assertNotIn("Collection disabled", freshness)

    def test_only_owner_can_write_without_membership(self):
        self.assertFalse(workspace_write_allowed("admin", None))
        self.assertTrue(workspace_write_allowed("owner", None))

    def test_project_admin_requires_an_explicit_admin_membership(self):
        self.assertTrue(workspace_write_allowed("admin", "admin"))
        self.assertTrue(workspace_write_allowed("admin", "assistant_admin"))
        self.assertFalse(workspace_write_allowed("admin", "editor"))
        self.assertFalse(workspace_write_allowed("admin", "viewer"))

    def test_project_deletion_requires_explicit_admin_membership(self):
        self.assertTrue(workspace_delete_allowed("admin", "admin"))
        self.assertTrue(workspace_delete_allowed("assistant_admin", "assistant_admin"))
        self.assertFalse(workspace_delete_allowed("admin", None))
        self.assertFalse(workspace_delete_allowed("admin", "editor"))
        self.assertFalse(workspace_delete_allowed("editor", "editor"))
        self.assertTrue(workspace_delete_allowed("admin", None, owner=True))

    def test_editor_can_write_only_when_assigned(self):
        self.assertTrue(workspace_write_allowed("editor", "editor"))
        self.assertTrue(workspace_write_allowed("assistant_admin", "assistant_admin"))
        self.assertFalse(workspace_write_allowed("editor", None))
        self.assertFalse(workspace_write_allowed("viewer", "editor"))
        self.assertFalse(workspace_write_allowed("viewer", "viewer"))

    def test_lower_role_cannot_view_owner_account(self):
        owner = SimpleNamespace(id=uuid.uuid4(), username="owner-account", email="owner@gmail.com", role="admin")
        admin = SimpleNamespace(id=uuid.uuid4(), username="project-admin", role="admin")
        with patch("app.admin.get_settings", return_value=SimpleNamespace(owner_email="owner@gmail.com")):
            self.assertFalse(can_view_admin_user(admin, owner))
            self.assertTrue(can_view_admin_user(admin, admin))
            self.assertTrue(can_view_admin_user(owner, admin))

    def test_higher_roles_can_view_lower_roles_but_not_the_reverse(self):
        owner = SimpleNamespace(id=uuid.uuid4(), username="owner-account", email="owner@gmail.com", role="admin")
        admin = SimpleNamespace(id=uuid.uuid4(), username="project-admin", role="admin")
        editor = SimpleNamespace(id=uuid.uuid4(), username="editor", role="editor")
        viewer = SimpleNamespace(id=uuid.uuid4(), username="viewer", role="viewer")

        with patch("app.admin.get_settings", return_value=SimpleNamespace(owner_email="owner@gmail.com")):
            self.assertTrue(can_view_admin_user(owner, admin))
            self.assertTrue(can_view_admin_user(admin, editor))
            self.assertTrue(can_view_admin_user(editor, viewer))
            self.assertFalse(can_view_admin_user(admin, owner))
            self.assertFalse(can_view_admin_user(editor, admin))
            self.assertFalse(can_view_admin_user(viewer, editor))

    def test_every_account_can_view_itself(self):
        for role in ("owner", "admin", "assistant_admin", "editor", "analyst", "viewer"):
            account = SimpleNamespace(id=uuid.uuid4(), username=role, role=role)
            self.assertTrue(can_view_admin_user(account, account))

    def test_security_rows_collapse_duplicate_owner_username(self):
        current_id = uuid.uuid4()
        legacy_id = uuid.uuid4()
        current = SimpleNamespace(id=current_id, username="Admin", role="owner")
        legacy = SimpleNamespace(id=legacy_id, username="admin", role="admin")
        rows = _dedupe_admin_rows(
            [legacy, current],
            current_user_id=current_id,
            project_access={legacy_id: [{"assistant_id": "legacy"}], current_id: []},
        )
        self.assertEqual([current_id], [row.id for row in rows])

    def test_intermediate_roles_can_view_lower_project_users_but_not_higher_roles(self):
        editor = SimpleNamespace(id=uuid.uuid4(), username="editor", role="editor")
        viewer = SimpleNamespace(id=uuid.uuid4(), username="viewer", role="viewer")
        project_admin = SimpleNamespace(id=uuid.uuid4(), username="project-admin", role="admin")
        self.assertTrue(can_view_admin_user(editor, editor))
        self.assertTrue(can_view_admin_user(editor, viewer))
        self.assertFalse(can_view_admin_user(editor, project_admin))

    def test_configured_owner_uses_effective_role_for_visibility(self):
        configured_owner = SimpleNamespace(id=uuid.uuid4(), username="configured-owner", email="configuredowner@gmail.com", role="admin")
        lower = SimpleNamespace(id=uuid.uuid4(), username="lower", role="viewer")
        with patch("app.admin.get_settings", return_value=SimpleNamespace(owner_email="configured.owner@gmail.com")):
            self.assertTrue(can_view_admin_user(configured_owner, lower))
            self.assertFalse(can_view_admin_user(lower, configured_owner))

    def test_telegram_settings_accept_only_numeric_private_ids(self):
        self.assertEqual(
            "-1001234567890",
            TelegramSettingsUpdate(feedback_channel_id="-1001234567890").feedback_channel_id,
        )
        with self.assertRaises(ValidationError):
            TelegramSettingsUpdate(feedback_channel_id="https://t.me/+invite")

    def test_telegram_bot_identity_is_validated_without_accepting_a_token(self):
        settings = TelegramSettingsUpdate(bot_display_name="  Bee Researcher  ", bot_username="@ResearchBeeBot", bot_id="123456789")
        self.assertEqual("Bee Researcher", settings.bot_display_name)
        self.assertEqual("ResearchBeeBot", settings.bot_username)
        self.assertEqual("123456789", settings.bot_id)
        with self.assertRaises(ValidationError):
            TelegramSettingsUpdate(bot_username="https://t.me/bot")
        with self.assertRaises(ValidationError):
            TelegramSettingsUpdate(bot_id="-100123")

    def test_default_workspace_exposes_effective_server_channels_without_secret(self):
        settings = SimpleNamespace(
            telegram_channel_id="-1001234567890",
            telegram_observer_channel_id="-1009876543210",
            telegram_bot_token=SecretStr("123456789:secret-value"),
        )
        with patch("app.admin.get_settings", return_value=settings):
            result = _telegram_config({}, assistant_id=DEFAULT_ASSISTANT_ID)
        self.assertEqual("-1001234567890", result["feedback_channel_id"])
        self.assertEqual("-1009876543210", result["observer_channel_id"])
        self.assertEqual("123456789", result["bot_id"])
        self.assertEqual(["server_env", "server_env"], [row["source"] for row in result["channels"]])
        self.assertNotIn("secret-value", repr(result))

    def test_new_workspace_does_not_inherit_default_channel_destinations(self):
        settings = SimpleNamespace(
            telegram_channel_id="-1001234567890",
            telegram_observer_channel_id="-1009876543210",
            telegram_bot_token=SecretStr("123456789:secret-value"),
        )
        with patch("app.admin.get_settings", return_value=settings):
            result = _telegram_config({}, assistant_id=uuid.uuid4())
        self.assertIsNone(result["feedback_channel_id"])
        self.assertIsNone(result["observer_channel_id"])
        self.assertFalse(any(row["configured"] for row in result["channels"]))

    def test_admin_user_password_requires_long_secret(self):
        self.assertEqual(34, len(AdminUserPasswordUpdate(new_password="violet herons cross mountain lakes").new_password))
        with self.assertRaises(ValidationError):
            AdminUserPasswordUpdate(new_password="short")

    def test_user_management_supports_selected_projects_and_required_roles(self):
        selected = uuid.uuid4()
        payload = AdminUserRequest(username="limited-user", password="violet herons cross mountain lakes", role="editor", assistant_ids=[selected])
        self.assertEqual([selected], payload.assistant_ids)
        managed = AdminUserManageUpdate(role="viewer", assistant_ids=[selected], new_password="patient badgers traverse riverbanks")
        self.assertEqual("viewer", managed.role)
        self.assertEqual([selected], managed.assistant_ids)

    def test_user_portal_access_defaults_and_explicit_feedback_grant(self):
        owner = SimpleNamespace(id=uuid.uuid4(), username="owner-account", email="owner@gmail.com", role="admin", preferences={})
        viewer = SimpleNamespace(id=uuid.uuid4(), username="viewer", role="viewer", preferences={})
        granted = SimpleNamespace(id=uuid.uuid4(), username="viewer", role="viewer", preferences={"user_portal_access": {"enabled": True, "feedback_enabled": True}})
        with patch("app.admin.get_settings", return_value=SimpleNamespace(owner_email="owner@gmail.com")):
            self.assertTrue(user_portal_access_allowed(owner))
            self.assertFalse(user_feedback_access_allowed(owner))
            self.assertFalse(user_portal_access_allowed(viewer))
            self.assertTrue(user_portal_access_allowed(granted))
            self.assertTrue(user_feedback_access_allowed(granted))
            self.assertEqual({"user_portal_access": False, "user_feedback_access": False}, user_portal_access_payload(viewer))

    def test_user_portal_access_update_requires_feedback_dependency(self):
        with self.assertRaises(ValidationError):
            # The API model is permissive enough for a UI toggle pair; the
            # service function enforces the dependency atomically.
            UserPortalAccessUpdate(enabled=False, feedback_enabled=True)

    def test_runtime_settings_validate_model_and_feedback_users(self):
        settings = AssistantRuntimeSettingsUpdate(
            max_items_per_run=5,
            freshness_window_days=7,
            analysis_model="gpt-5.6-sol",
            allowed_feedback_usernames=["@FarhaadNoroozi", "farhaadnoroozi"],
        )
        self.assertEqual(["farhaadnoroozi"], settings.allowed_feedback_usernames)
        self.assertEqual(7, settings.freshness_window_days)
        for model in ("gpt-6.1-sol", "gpt-6-luna", "gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.5", "gpt-5.4"):
            self.assertEqual(model, AssistantRuntimeSettingsUpdate(analysis_model=model).analysis_model)
        with self.assertRaises(ValidationError):
            AssistantRuntimeSettingsUpdate(analysis_model="arbitrary-model")
        for invalid in (0, 31):
            with self.assertRaises(ValidationError):
                AssistantRuntimeSettingsUpdate(freshness_window_days=invalid)

    def test_runtime_settings_normalize_hourly_weekly_schedule(self):
        settings = AssistantRuntimeSettingsUpdate(
            schedule_slots=[
                {"weekday": 5, "time": "18:00"},
                {"weekday": 0, "time": "08:00"},
                {"weekday": 5, "time": "18:00"},
            ]
        )
        self.assertEqual(
            [{"weekday": 0, "time": "08:00"}, {"weekday": 5, "time": "18:00"}],
            settings.schedule_slots,
        )
        for invalid in ([], [{"weekday": 7, "time": "08:00"}], [{"weekday": 0, "time": "08:30"}]):
            with self.assertRaises(ValidationError):
                AssistantRuntimeSettingsUpdate(schedule_slots=invalid)


if __name__ == "__main__":
    unittest.main()
