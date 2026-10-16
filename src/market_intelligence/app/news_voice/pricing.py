"""Dated public API rates; account contracts still require owner verification.

The 2026-10-12 v4 promotion has expired. The review window below is Bee's
rolling seven-day policy, not a price guarantee made by ElevenLabs. The rate
card itself is reviewed by people when it is changed in a release; automatic
renewal (``matches``) only confirms the Owner's saved rates equal this card.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

SOURCE = 'https://elevenlabs.io/pricing/api'
RATE_CARD_REVIEWED_AT = datetime(2026, 10, 13, tzinfo=timezone.utc)
REVIEW_DAYS = 7
RENEW_WITHIN = timedelta(days=1)
STT_PER_MINUTE = Decimal('0.39') / 60
KEYTERMS_MULTIPLIER = Decimal('1.2051282052')  # ceil((0.39 + 0.08) / 0.39)
TTS_PER_1000 = {'eleven_v3':Decimal('0.08'), 'eleven_v3_conversational':Decimal('0.04'),
    'eleven_v4':Decimal('0.08'), 'eleven_v4_turbo':Decimal('0.04')}


def window(now=None):
    return (now or datetime.now(timezone.utc)) + timedelta(days=REVIEW_DAYS)


def matches(policy):
    """True only when every saved rate equals the released rate card."""
    return (policy.price_reference.startswith(SOURCE) and policy.stt_usd_per_minute == STT_PER_MINUTE
        and policy.keyterms_multiplier == KEYTERMS_MULTIPLIER
        and all(v.model_id in TTS_PER_1000 and v.usd_per_1000_chars == TTS_PER_1000[v.model_id] for v in policy.voices))


def snapshot():
    return {'reference':SOURCE, 'reviewed_at':RATE_CARD_REVIEWED_AT.isoformat(), 'expires_at':window().isoformat(),
        'stt_usd_per_minute':str(STT_PER_MINUTE), 'keyterms_multiplier':str(KEYTERMS_MULTIPLIER),
        'tts_usd_per_1000_chars':{k:str(v) for k,v in TTS_PER_1000.items()},
        'scope':'published_standard_api_rates', 'account_contract_verified':False,
        'expired_promotions_included':False, 'expiry_policy':'bee_rolling_seven_day_review', 'review_days':REVIEW_DAYS}
