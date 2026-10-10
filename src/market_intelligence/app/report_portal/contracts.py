"""Private inputs: strict, bounded and never echoed in validation errors."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid", allow_inf_nan=False, str_strip_whitespace=True
    )


class Draft(Contract):
    draft_key: UUID | None = None
    business_id: UUID
    assistant_id: UUID
    title: str = Field(min_length=5, max_length=200)
    text: str = Field(min_length=50, max_length=20000)
    tags: list[str] = Field(min_length=1, max_length=5)
    reporter: str = Field(min_length=1, max_length=160)
    event_date: str = Field(default="", max_length=10)
    language: Literal["fa", "en", "tr", "ar", "es", "it", "de", "fr"] = "fa"
    classification: Literal["internal", "confidential", "very_confidential"] = (
        "internal"
    )
    revision: int = Field(default=0, ge=0)

    @field_validator("tags")
    @classmethod
    def tags_bounded(cls, values):
        if any(not isinstance(v, str) or not v.strip() or len(v) > 60 for v in values):
            raise ValueError("invalid tags")
        return list(dict.fromkeys(v.strip() for v in values))

    @field_validator("event_date")
    @classmethod
    def date_valid(cls, value):
        if value:
            from datetime import date

            date.fromisoformat(value)
        return value


class Submit(Contract):
    idempotency_key: UUID
    revision: int = Field(ge=1)
    confirmed: Literal[True]


class Bind(Contract):
    assistant_id: UUID


class Grant(Contract):
    business_id: UUID
    user_id: UUID
    role: Literal["reporter", "manager"]
    assistant_ids: list[UUID] = Field(min_length=1, max_length=30)
    active: bool = True


class Consent(Contract):
    confirmed: Literal[True]
    models: list[str] = Field(min_length=1, max_length=12)
    daily_cap: int = Field(default=10, ge=1, le=100)
    daily_budget_usd: float = Field(default=1, gt=0, le=100)
    retention_days: int = Field(default=90, ge=1, le=365)
