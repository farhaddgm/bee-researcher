from __future__ import annotations

from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

LANGUAGES = ("fa", "en", "tr", "ar", "es", "it", "de", "fr")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ModelSpec(Strict):
    provider: Literal["openai", "anthropic", "google"]
    model_id: str = Field(min_length=2, max_length=100, pattern=r"^[A-Za-z0-9._:/-]+$")
    label: str = Field(min_length=1, max_length=100)
    input_usd: Decimal = Field(gt=0, le=1000)
    output_usd: Decimal = Field(gt=0, le=1000)
    max_input_chars: int = Field(default=24000, ge=2000, le=64000)
    max_output_tokens: int = Field(default=1200, ge=200, le=4000)
    enabled: bool = False
    verified: bool = False
    price_reference: str = Field(min_length=10, max_length=200)

    @property
    def key(self):
        return self.provider + ":" + self.model_id


class ProjectPolicy(Strict):
    enabled: bool = False
    daily_budget_usd: Decimal = Field(default=Decimal("1"), gt=0, le=1000)
    model_keys: list[str] = Field(default_factory=list, max_length=12)


class Policy(Strict):
    enabled: bool = False
    daily_budget_usd: Decimal = Field(default=Decimal("5"), gt=0, le=1000)
    user_daily_budget_usd: Decimal = Field(default=Decimal("1"), gt=0, le=100)
    user_daily_requests: int = Field(default=30, ge=1, le=100)
    models: list[ModelSpec] = Field(default_factory=list, max_length=12)
    # Compatibility with saved pre-3.40.1 JSON only; no project gates/budgets.
    projects: dict[str, ProjectPolicy] = Field(default_factory=dict, json_schema_extra={"deprecated": True})

    @model_validator(mode="after")
    def unique_models(self):
        keys = [m.key for m in self.models]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate models")
        if any(set(p.model_keys) - set(keys) for p in self.projects.values()):
            raise ValueError("unknown project model")
        return self


class Start(Strict):
    model_key: str = Field(min_length=3, max_length=120)


class Question(Start):
    question: str = Field(min_length=1, max_length=4000)
    idempotency_key: str = Field(min_length=16, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    language: Literal["fa", "en", "tr", "ar", "es", "it", "de", "fr"] = "fa"
    context_version: str = Field(min_length=64, max_length=64)
    selected_segment: str | None = Field(default=None, max_length=20, pattern=r"^report-[0-9]+$")


class Feedback(Strict):
    value: Literal[-1, 1]


class Grant(Strict):
    enabled: bool
