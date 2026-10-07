import os
import unittest

from pydantic import ValidationError


os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_DB", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_USER", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_REDIS_PASSWORD", "test-password")

from app.config import Settings  # noqa: E402


class ConfigTest(unittest.TestCase):
    def test_default_version_comes_from_the_shipped_release_file(self):
        from pathlib import Path
        expected = Path(__file__).parents[1].joinpath("VERSION").read_text().strip()
        self.assertEqual(Settings.model_fields['version'].default, expected)

    def settings(self, **overrides) -> Settings:
        values = {
            "postgres_db": "assistant_test",
            "postgres_user": "assistant_test",
            "postgres_password": "secret",
            "redis_password": "secret",
            "version": "test-version",
            "pilot_mode": True,
            "auto_publish": False,
            "scheduler_enabled": True,
            "_env_file": None,
        }
        values.update(overrides)
        return Settings(**values)

    def test_dotin_schedule_is_normalized(self):
        settings = self.settings(
            schedule_times="08:00, 11:00,14:00,17:00,22:00,08:00",
            external_analysis_approved=False,
        )
        self.assertEqual(("08:00", "11:00", "14:00", "17:00", "22:00"), settings.schedule_time_values)
        self.assertEqual("Europe/Berlin", settings.timezone)
        self.assertEqual(7, settings.max_items_per_run)
        self.assertEqual("test-version", settings.version)
        self.assertEqual(1000, settings.processing_max_items_per_day)
        self.assertEqual(1000, settings.pipeline_max_candidates_per_run)
        self.assertEqual(6, settings.admin_session_ttl_hours)
        self.assertEqual(3, settings.fetch_concurrency)
        self.assertEqual(10, settings.database_pool_size)
        self.assertEqual(10, settings.database_max_overflow)
        self.assertEqual(15, settings.database_pool_timeout_seconds)
        self.assertTrue(settings.scheduler_enabled)
        self.assertTrue(settings.pilot_mode)
        self.assertFalse(settings.auto_publish)
        self.assertFalse(settings.external_analysis_approved)
        self.assertFalse(settings.whatsapp_enabled)

    def test_whatsapp_requires_https_and_known_destination(self):
        with self.assertRaises(ValidationError):
            self.settings(whatsapp_destination_type="web")
        with self.assertRaises(ValidationError):
            self.settings(whatsapp_webhook_public_url="http://example.test/hook")

    def test_public_schema_and_colliding_queue_are_rejected(self):
        with self.assertRaises(ValidationError):
            self.settings(database_schema="public")
        with self.assertRaises(ValidationError):
            self.settings(queue_namespace="ai-assistant")
        with self.assertRaises(ValidationError):
            self.settings(telegram_channel_id="https://t.me/+invite")

    def test_production_rejects_insecure_admin_cookie(self):
        with self.assertRaises(ValidationError):
            self.settings(environment="production", admin_cookie_secure=False)

    def test_public_domain_rejects_scheme_or_path(self):
        with self.assertRaises(ValidationError):
            self.settings(domain="https://market.example.com/admin")
        self.assertEqual("market.example.com", self.settings(domain="market.example.com.").domain)
        with self.assertRaises(ValidationError):
            self.settings(environment="production", admin_bootstrap_password="CHANGE_ME_TO_A_LONG_RANDOM_PASSWORD")

    def test_login_rate_limit_has_bounded_defaults(self):
        settings = self.settings()
        self.assertEqual(10, settings.login_max_attempts)
        self.assertEqual(30, settings.login_ip_max_attempts)
        self.assertEqual(900, settings.login_window_seconds)
        self.assertEqual(2_000_000, settings.max_request_body_bytes)
        self.assertTrue(settings.csp_report_only)
        self.assertTrue(settings.csp_strict)
        self.assertEqual("/admin/api/security/csp-report", settings.csp_report_uri)

    def test_csrf_signing_secret_requires_a_long_value_when_provided(self):
        with self.assertRaises(ValidationError):
            self.settings(csrf_signing_secret="too-short")
        self.assertIsNone(self.settings(csrf_signing_secret="").csrf_signing_secret)

    def test_csp_report_uri_is_same_origin(self):
        self.assertEqual("/csp", self.settings(csp_report_uri=" /csp ").csp_report_uri)
        with self.assertRaises(ValidationError):
            self.settings(csp_report_uri="https://collector.example/csp")
        with self.assertRaises(ValidationError):
            self.settings(csp_report_uri="//collector.example/csp")

    def test_secret_values_are_url_encoded(self):
        settings = self.settings(postgres_password="a:b@c", redis_password="a:b@c")
        self.assertIn("a%3Ab%40c", settings.database_url)
        self.assertIn("a%3Ab%40c", settings.redis_url)


if __name__ == "__main__":
    unittest.main()
