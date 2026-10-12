from typing import Literal
from uuid import UUID
from pydantic import Field, field_validator
from app.news_chat.schemas import Strict


class Watch(Strict):
    enabled: bool = True


class Seen(Strict):
    version: int = Field(ge=0)


class ExpertCreate(Strict):
    id: UUID
    assignee_id: UUID
    title: str = Field(min_length=1, max_length=180)
    question: str = Field(min_length=1, max_length=4000)
    excerpt: str = Field(default='', max_length=6000)
    publication_ids: list[UUID] = Field(min_length=1, max_length=5)

    @field_validator('title', 'question')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('text required')
        return value.strip()

    @field_validator('publication_ids')
    @classmethod
    def unique(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('duplicate source')
        return value


class Reply(Strict):
    id: UUID
    version: int = Field(ge=1)
    body: str = Field(min_length=1, max_length=6000)

    @field_validator('body')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('text required')
        return value.strip()


class RequestState(Strict):
    version: int = Field(ge=1)
    status: Literal['open', 'closed', 'cancelled']
