import io
import json
import logging
import os
import unittest

os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_DB", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_USER", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_REDIS_PASSWORD", "test-password")

from app.observability import OperationalFormatter, configure_logging  # noqa: E402
from app.security_controls import redact_sensitive_text  # noqa: E402


class ObservabilityTest(unittest.TestCase):
    def test_logs_enabled_once_without_enabling_http_client_payloads(self):
        logger = logging.getLogger("app")
        configure_logging()
        handlers = list(logger.handlers)
        configure_logging()
        self.assertEqual(handlers, logger.handlers)
        self.assertTrue(logging.getLogger("app.runtime").isEnabledFor(logging.INFO))
        self.assertFalse(logger.propagate)
        self.assertFalse(logging.getLogger("httpx").isEnabledFor(logging.INFO))

    def test_exception_content_is_not_copied_to_logs(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(OperationalFormatter())
        logger = logging.Logger("fixture", level=logging.INFO)
        logger.addHandler(handler)
        try:
            raise RuntimeError("private customer message password=never-copy-this")
        except RuntimeError:
            logger.exception("operation failed")
        output = json.loads(stream.getvalue())
        self.assertEqual("RuntimeError", output["exception_type"])
        self.assertTrue(output["frames"])
        self.assertNotIn("never-copy-this", stream.getvalue())
        self.assertNotIn("private customer", stream.getvalue())

    def test_credentials_redacted_in_fields_urls_and_plain_api_keys(self):
        value = 'password="secret one" api_key=secret-two https://user:secret-three@example.org Bearer secret-four sk-proj-1234567890123456'
        output = redact_sensitive_text(value)
        for secret in ("secret one", "secret-two", "secret-three", "secret-four", "sk-proj-1234567890123456"):
            self.assertNotIn(secret, output)
