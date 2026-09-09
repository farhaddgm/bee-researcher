import unittest

from app.config import Settings
from app.whatsapp_delivery import WhatsAppClient, whatsapp_readiness


class WhatsAppReadinessTest(unittest.TestCase):
    def settings(self, **overrides) -> Settings:
        values = {
            "postgres_db": "assistant_test",
            "postgres_user": "assistant_test",
            "postgres_password": "secret",
            "redis_password": "secret",
            "_env_file": None,
        }
        values.update(overrides)
        return Settings(**values)

    def test_disabled_by_default_and_secret_free(self):
        report = whatsapp_readiness(self.settings())
        self.assertFalse(report.ready)
        self.assertEqual("disabled_until_meta_approval", report.status)
        self.assertNotIn("access_token", report.safe_dict())

    def test_enabled_gate_lists_only_missing_prerequisites(self):
        report = whatsapp_readiness(
            self.settings(
                whatsapp_enabled=True,
                whatsapp_access_token="secret",
                whatsapp_webhook_verify_token="verify",
                whatsapp_webhook_public_url="https://example.test/webhooks/meta",
                whatsapp_business_account_id="waba",
                whatsapp_phone_number_id="phone",
            )
        )
        self.assertFalse(report.ready)
        self.assertEqual("awaiting_official_adapter_validation", report.status)
        self.assertEqual((), report.missing)

    def test_client_fails_closed_without_network_call(self):
        client = WhatsAppClient(self.settings())
        with self.assertRaisesRegex(RuntimeError, "disabled until official Meta"):
            import asyncio

            asyncio.run(client.send_text(text="test", idempotency_key="id-1"))
