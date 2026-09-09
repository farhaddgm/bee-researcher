import unittest

from app.telegram_delivery import SAFE_MESSAGE_LIMIT, TELEGRAM_MESSAGE_LIMIT, split_message


class BeeCFOMediaMessageLimitTest(unittest.TestCase):
    def test_default_product_limit_is_preserved_and_media_limit_can_use_telegram_space(self):
        message = "\n\n".join(f"دسته {index}\n• نظر رسانه‌ای {index}" for index in range(80))
        self.assertGreater(len(split_message(message, limit=3900)[0]), SAFE_MESSAGE_LIMIT)
        self.assertLessEqual(max(len(chunk) for chunk in split_message(message, limit=3900)), 3900)
        self.assertLessEqual(3900, TELEGRAM_MESSAGE_LIMIT)


if __name__ == "__main__":
    unittest.main()
