from datetime import datetime, timedelta, timezone
import unittest

from app.news_voice.readiness import checklist
from app.news_voice.schemas import Policy, Voice


class ReadinessTests(unittest.TestCase):
    def test_default_policy_explains_every_missing_gate_without_network(self):
        value = checklist(Policy(require_zero_retention=True), configured=True, server_enabled=True)
        checks = {row['id']: row['passed'] for row in value['checks']}
        self.assertTrue(checks['key'])
        self.assertFalse(checks['retention'])
        self.assertFalse(checks['voice'])
        self.assertFalse(checks['pricing'])
        self.assertFalse(value['ready'])
        self.assertEqual(0, value['network_requests'])
        self.assertFalse(value['account_entitlement_verified_by_this_check'])

    def test_metadata_only_valid_key_does_not_verify_retention(self):
        now = datetime.now(timezone.utc)
        policy = Policy(enabled=True, stt_verified=True, require_zero_retention=True,
            voices=[Voice(voice_id='syntheticvoice001', label='Synthetic', languages=['en'],
                          verified=True, usd_per_1000_chars='.08')],
            price_reference='https://elevenlabs.io/pricing/api', price_expires_at=now+timedelta(days=1))
        value = checklist(policy, configured=True, server_enabled=True, now=now)
        self.assertFalse(value['ready'])
        policy.zero_retention_verified=True
        policy.retention_reference='synthetic evidence reference'
        self.assertTrue(checklist(policy, configured=True, server_enabled=True, now=now)['ready'])
        self.assertFalse(checklist(policy, configured=True, server_enabled=True, now=now+timedelta(days=2))['ready'])

    def test_owner_key_rotation_requires_fresh_approval(self):
        value=checklist(Policy(),configured=True,server_enabled=True,credential_revision='new-key-revision')
        self.assertFalse(next(row['passed'] for row in value['checks'] if row['id']=='approval'))
        policy=Policy();policy._credential_revision='new-key-revision'
        value=checklist(policy,configured=True,server_enabled=True,credential_revision='new-key-revision')
        self.assertTrue(next(row['passed'] for row in value['checks'] if row['id']=='approval'))
