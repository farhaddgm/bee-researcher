import unittest

from app.admin import _sanitize_template_config


class WorkspaceTemplateTest(unittest.TestCase):
    def test_template_copy_removes_credentials_and_channel_destinations(self):
        source = {
            "topics": ["payments"],
            "telegram_bot_token": "do-not-copy",
            "telegram_channel_id": "-1001234567890",
            "nested": {"openai_api_key": "do-not-copy", "threshold": 0.5},
        }
        result = _sanitize_template_config(source)
        self.assertEqual({"topics": ["payments"], "nested": {"threshold": 0.5}}, result)


if __name__ == "__main__":
    unittest.main()
