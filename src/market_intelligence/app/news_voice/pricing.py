"""Dated public API rates; account contracts still require owner verification.

The 2026-10-12 v4 promotion has expired. Expiry below is Bee's seven-day
review window, not a price guarantee made by ElevenLabs.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

SOURCE = 'https://elevenlabs.io/pricing/api'
REVIEWED_AT = datetime(2026, 10, 13, tzinfo=timezone.utc)
EXPIRES_AT = REVIEWED_AT + timedelta(days=7)
STT_PER_MINUTE = Decimal('0.39') / 60
KEYTERMS_MULTIPLIER = Decimal('1.2051282052')  # ceil((0.39 + 0.08) / 0.39)
TTS_PER_1000 = {'eleven_v3':Decimal('0.08'), 'eleven_v3_conversational':Decimal('0.04'),
    'eleven_v4':Decimal('0.08'), 'eleven_v4_turbo':Decimal('0.04')}


def snapshot():
    return {'reference':SOURCE, 'reviewed_at':REVIEWED_AT.isoformat(), 'expires_at':EXPIRES_AT.isoformat(),
        'stt_usd_per_minute':str(STT_PER_MINUTE), 'keyterms_multiplier':str(KEYTERMS_MULTIPLIER),
        'tts_usd_per_1000_chars':{k:str(v) for k,v in TTS_PER_1000.items()},
        'scope':'published_standard_api_rates', 'account_contract_verified':False,
        'expired_promotions_included':False, 'expiry_policy':'bee_seven_day_review'}
