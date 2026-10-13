from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import Field, PrivateAttr, SecretStr, model_validator
from app.news_chat.schemas import Strict

Language = Literal['fa', 'en', 'tr', 'ar', 'es', 'it', 'de', 'fr']
Key = Field(min_length=16, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')


class CredentialUpdate(Strict):
    action: Literal['set', 'delete']
    expected_revision: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')
    api_key: SecretStr | None = None

    @model_validator(mode='after')
    def key_valid(self):
        from app.news_voice.credentials import valid_key
        if self.action == 'set' and (not self.api_key or not valid_key(self.api_key.get_secret_value())):
            raise ValueError('voice_key_invalid')
        if self.action == 'delete' and self.api_key is not None:
            raise ValueError('unexpected_key')
        return self


class ConnectionCheck(Strict):
    api_key: SecretStr | None = None
    search: str = Field(default='', max_length=100)
    page_token: str | None = Field(default=None, max_length=1000)

    @model_validator(mode='after')
    def key_valid(self):
        from app.news_voice.credentials import valid_key
        if self.api_key is not None and not valid_key(self.api_key.get_secret_value()):
            raise ValueError('voice_key_invalid')
        return self


class Voice(Strict):
    voice_id: str = Field(min_length=8, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')
    label: str = Field(min_length=1, max_length=100)
    model_id: Literal['eleven_v3', 'eleven_v3_conversational', 'eleven_v4', 'eleven_v4_turbo'] = 'eleven_v3'
    transport: Literal['http', 'ttd'] = 'http'
    languages: list[Language] = Field(min_length=1, max_length=8)
    verified: bool = False
    timing: bool = False
    max_chars: int = Field(default=5000, ge=100, le=10000)
    usd_per_1000_chars: Decimal = Field(gt=0, le=100)
    pronunciation_dictionaries: list[dict[str, str]] = Field(default_factory=list, max_length=3)

    @model_validator(mode='after')
    def compatible(self):
        if len(set(self.languages)) != len(self.languages):
            raise ValueError('duplicate language')
        if self.transport == 'http' and self.model_id != 'eleven_v3':
            raise ValueError('v4 and conversational models require verified TTD transport')
        for d in self.pronunciation_dictionaries:
            if set(d) != {'pronunciation_dictionary_id', 'version_id'} or any(not v or len(v)>100 for v in d.values()):
                raise ValueError('invalid dictionary locator')
        return self

    @property
    def key(self):
        return self.model_id + ':' + self.voice_id


class Policy(Strict):
    _credential_revision: str | None = PrivateAttr(default=None)
    enabled: bool = False
    daily_budget_usd: Decimal = Field(default=Decimal(2), gt=0, le=1000)
    user_daily_budget_usd: Decimal = Field(default=Decimal('0.5'), gt=0, le=100)
    continuous_enabled: bool = False
    stt_verified: bool = False
    require_zero_retention: bool = False
    zero_retention_verified: bool = False
    retention_reference: str = Field(default='', max_length=240)
    voices: list[Voice] = Field(default_factory=list, max_length=12)
    stt_usd_per_minute: Decimal = Field(default=Decimal('0.0065'), gt=0, le=10)
    keyterms_multiplier: Decimal = Field(default=Decimal('1.2051282052'), ge=1, le=5)
    price_reference: str = Field(default='', max_length=240)
    price_expires_at: datetime | None = None
    max_input_seconds: int = Field(default=120, ge=10, le=120)
    max_session_seconds: int = Field(default=600, ge=30, le=600)
    daily_stt_seconds: int = Field(default=1200, ge=10, le=7200)
    max_audio_bytes: int = Field(default=25_000_000, ge=32000, le=25_000_000)
    storage_bytes: int = Field(default=250_000_000, ge=1_000_000, le=2_000_000_000)
    staging_seconds: int = Field(default=900, ge=120, le=900)
    retention_days: int | None = Field(default=None, ge=1, le=3650)

    @model_validator(mode='after')
    def valid(self):
        if self.user_daily_budget_usd>self.daily_budget_usd:
            raise ValueError('user voice budget exceeds global voice budget')
        if len({v.key for v in self.voices}) != len(self.voices):
            raise ValueError('duplicate voice')
        if self.price_expires_at and self.price_expires_at.tzinfo is None:
            raise ValueError('timezone required')
        if self.enabled and (not self.stt_verified or not any(v.verified for v in self.voices)
                             or len(self.price_reference)<10 or not self.price_expires_at
                             ):
            raise ValueError('verified capabilities and current price required')
        return self


class Start(Strict):
    idempotency_key: str = Key
    language: Language = 'fa'
    transfer_consent: Literal[True]
    consent_version: Literal['voice-1'] = 'voice-1'
    retain_user_audio_for_save: bool = False
    continuous: bool = False
    keyterms: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode='after')
    def terms(self):
        if any(not s.strip() or len(s)>80 for s in self.keyterms) or len(set(self.keyterms))!=len(self.keyterms):
            raise ValueError('invalid keyterms')
        return self


class TTS(Strict):
    streaming: bool = False
    idempotency_key: str = Key
    voice_key: str = Field(min_length=8, max_length=150)
    transfer_consent: Literal[True]
    # Link only genuine, same-owner STT recordings to a submitted generation.
    input_session_ids: list[UUID] = Field(default_factory=list, max_length=10)
    regenerate: bool = False


class Brief(Strict):
    idempotency_key: str = Key
    publication_ids: list[UUID] = Field(min_length=1,max_length=20)
    voice_key: str = Field(min_length=8,max_length=150)
    language: Language = 'fa'
    minutes: int = Field(default=3,ge=1,le=10)
    transfer_consent: Literal[True]

    @model_validator(mode='after')
    def unique(self):
        if len(set(self.publication_ids))!=len(self.publication_ids):raise ValueError('duplicate publication')
        return self


class Selection(Strict):
    asset_id: UUID
    start_seconds: float | None = Field(default=None, ge=0, le=600)
    end_seconds: float | None = Field(default=None, gt=0, le=600)

    @model_validator(mode='after')
    def range(self):
        if (self.start_seconds is None) != (self.end_seconds is None):
            raise ValueError('both range boundaries required')
        if self.start_seconds is not None and self.end_seconds<=self.start_seconds:
            raise ValueError('invalid range')
        return self


class Save(Strict):
    idempotency_key: str = Key
    scope: Literal['ai', 'dialogue'] = 'ai'
    title: str = Field(min_length=1, max_length=180)
    selections: list[Selection] = Field(min_length=1, max_length=50)
    retain_conversation: Literal[True]
    allow_partial: bool = False

    @model_validator(mode='after')
    def distinct(self):
        if len({s.asset_id for s in self.selections}) != len(self.selections) or not self.title.strip():
            raise ValueError('invalid selection')
        return self


class Playback(Strict):
    played_seconds: float = Field(ge=0, le=600)
    interrupted: bool = False
    # Actual locally played intervals, not an assertion inferred from a seek.
    played_ranges: list[tuple[float,float]] = Field(default_factory=list,max_length=100)

    @model_validator(mode='after')
    def intervals(self):
        import math
        if any(not(math.isfinite(a) and math.isfinite(b) and 0<=a<b<=600) for a,b in self.played_ranges):
            raise ValueError('invalid playback interval')
        return self


class Bookmark(Strict):
    version: int = Field(ge=0)
    seconds: float = Field(ge=0, le=600)
    label: str = Field(min_length=1, max_length=180)

    @model_validator(mode='after')
    def nonempty(self):
        self.label=self.label.strip()
        if not self.label:raise ValueError('label required')
        return self


class Reconcile(Strict):
    actual_usd: Decimal = Field(ge=0,le=10000)
    provider_reference: str = Field(min_length=10,max_length=180,pattern=r'^[A-Za-z0-9 _.:/-]+$')
