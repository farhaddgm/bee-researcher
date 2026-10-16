"""The seven-day price window renews itself only while rates equal the released card."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.news_voice import pricing, service
from app.news_voice.schemas import Policy, Voice


class FakeSession:
    def __init__(self, config):
        self.row = SimpleNamespace(config=config)

    async def get(self, model, key, with_for_update=False):
        return self.row


def policy_config(**override):
    voice = Voice(voice_id='syntheticvoice001', label='Synthetic', languages=['fa'], verified=True,
                  usd_per_1000_chars=str(pricing.TTS_PER_1000['eleven_v3']))
    value = Policy(enabled=True, stt_verified=True, voices=[voice], price_reference=pricing.SOURCE,
                   stt_usd_per_minute=pricing.STT_PER_MINUTE, keyterms_multiplier=pricing.KEYTERMS_MULTIPLIER,
                   price_expires_at=service.now() + timedelta(hours=6)).model_dump(mode='json')
    value.update(override)
    return {**value, '_credential_revision': 'r1'}


class RenewalTests(unittest.IsolatedAsyncioTestCase):
    async def renew(self, config):
        session = FakeSession(config)
        with patch('app.news_voice.credentials.managed', return_value={'revision': 'r1'}):
            return await service.renew_price_review(session), session.row.config

    async def test_window_is_seven_days_and_snapshot_rolls(self):
        self.assertEqual(7, pricing.REVIEW_DAYS)
        gap = pricing.window(service.now()) - service.now()
        self.assertAlmostEqual(7 * 86400, gap.total_seconds(), delta=5)

    async def test_rates_equal_to_card_renew_for_seven_days(self):
        renewed, config = await self.renew(policy_config())
        self.assertTrue(renewed)
        left = service.now() + timedelta(days=7) - Policy.model_validate({k: v for k, v in config.items() if k != '_credential_revision'}).price_expires_at
        self.assertLess(abs(left.total_seconds()), 5)
        self.assertEqual('r1', config['_credential_revision'])

    async def test_far_expiry_is_not_touched(self):
        config = policy_config(price_expires_at=(service.now() + timedelta(days=5)).isoformat())
        renewed, after = await self.renew(config)
        self.assertFalse(renewed)
        self.assertEqual(config['price_expires_at'], after['price_expires_at'])

    async def test_custom_rate_disabled_policy_opt_out_and_changed_key_never_renew(self):
        voice = dict(policy_config()['voices'][0], usd_per_1000_chars='0.5')
        for override in ({'voices': [voice]}, {'stt_usd_per_minute': '0.01'}, {'enabled': False, 'voices': []},
                         {'price_auto_renew': False}, {'price_reference': 'Account contract price'}):
            renewed, _ = await self.renew(policy_config(**override))
            self.assertFalse(renewed, override)
        with patch('app.news_voice.credentials.managed', return_value={'revision': 'other'}):
            self.assertFalse(await service.renew_price_review(FakeSession(policy_config())))

    async def test_expired_window_with_matching_rates_is_renewed(self):
        renewed, _ = await self.renew(policy_config(price_expires_at=(service.now() - timedelta(hours=3)).isoformat()))
        self.assertTrue(renewed)

    def test_matches_requires_every_rate(self):
        p = Policy.model_validate({k: v for k, v in policy_config().items() if k != '_credential_revision'})
        self.assertTrue(pricing.matches(p))
        self.assertEqual(Decimal('0.0065'), p.stt_usd_per_minute)


if __name__ == '__main__':
    unittest.main()
