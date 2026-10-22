"""Owner-facing, local-only checklist. A valid key is not privacy evidence."""
from datetime import datetime, timezone

from app.news_voice.schemas import Policy


def checklist(policy: Policy, *, configured: bool, server_enabled: bool, credential_revision: str | None = None, now=None):
    current = now or datetime.now(timezone.utc)
    checks = [
        ('server', bool(server_enabled)),
        ('key', bool(configured)),
        ('approval', credential_revision is None or policy._credential_revision == credential_revision),
        ('retention', not policy.require_zero_retention or (
            policy.zero_retention_verified and len(policy.retention_reference.strip()) >= 10)),
        ('pricing', bool(policy.price_reference.strip()) and bool(policy.price_expires_at and policy.price_expires_at > current)),
        ('transcription', policy.stt_verified),
        ('voice', any(v.verified for v in policy.voices)),
        ('policy', policy.enabled),
    ]
    return {'ready': all(ok for _, ok in checks),
            'checks': [{'id': key, 'passed': bool(ok)} for key, ok in checks],
            'privacy_required': policy.require_zero_retention,
            'account_entitlement_verified_by_this_check': False,
            'network_requests': 0}
