from datetime import date, datetime
from typing import Literal
from uuid import UUID
from pydantic import Field, field_validator, model_validator
from app.news_chat.schemas import Strict

Kind = Literal['topic', 'watch', 'action', 'decision', 'shared', 'meeting']


class Weights(Strict):
    freshness: int = Field(default=40, ge=0, le=100)
    relevance: int = Field(default=40, ge=0, le=100)
    interests: int = Field(default=20, ge=0, le=100)

    @model_validator(mode='after')
    def nonzero(self):
        if not self.freshness + self.relevance + self.interests:
            raise ValueError('at least one priority weight is required')
        return self


class Profile(Strict):
    version: int = Field(default=0, ge=0)
    interests: list[str] = Field(default_factory=list, max_length=30)
    muted_terms: list[str] = Field(default_factory=list, max_length=30)
    hide_duplicates: bool = False
    business_context: str = Field(default='', max_length=2000)
    weights: Weights = Field(default_factory=Weights)

    @field_validator('interests', 'muted_terms')
    @classmethod
    def terms(cls, values):
        clean = list(dict.fromkeys(v.strip() for v in values))
        if any(not v or len(v) > 100 for v in clean):
            raise ValueError('terms must be between 1 and 100 characters')
        return clean


class Attributes(Strict):
    meeting_kind: Literal['product', 'sales', 'management', 'custom'] = 'product'
    duration_minutes: int = Field(default=30, ge=10, le=180)
    objective: str = Field(default='', max_length=1000)
    meeting_at: datetime | None = None
    term: str = Field(default='', max_length=100)
    entity_type: Literal['company', 'competitor', 'product', 'regulation', 'topic'] = 'topic'
    notifications: Literal['off', 'important', 'all'] = 'important'
    reviewed_at: datetime | None = None
    assignee: str = Field(default='', max_length=120)
    due_on: date | None = None
    review_on: date | None = None
    status: Literal['open', 'doing', 'done', 'cancelled', 'active', 'reviewed', 'superseded'] = 'open'
    rationale: str = Field(default='', max_length=3000)

    @field_validator('reviewed_at', 'meeting_at')
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError('reviewed_at must include a timezone')
        return value


class Record(Strict):
    id: UUID | None = None
    version: int = Field(default=0, ge=0)
    kind: Kind
    title: str = Field(min_length=1, max_length=180)
    body: str = Field(default='', max_length=12000)
    attributes: Attributes = Field(default_factory=Attributes)
    publication_ids: list[UUID] = Field(default_factory=list, max_length=5)
    conversation_id: UUID | None = None
    generation_id: UUID | None = None

    @model_validator(mode='after')
    def valid_record(self):
        self.title = self.title.strip()
        if not self.title:
            raise ValueError('title is required')
        if len(set(self.publication_ids)) != len(self.publication_ids):
            raise ValueError('duplicate source')
        if self.kind in {'topic', 'watch'} and not self.attributes.term.strip():
            raise ValueError('tracking term is required')
        if self.kind in {'shared', 'meeting'} and (not self.body.strip() or not self.publication_ids):
            raise ValueError('a shared result requires text and published sources')
        return self
