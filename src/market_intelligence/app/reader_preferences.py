"""Account-owned chat defaults; provider permissions remain in chat policy."""

from typing import Literal

from pydantic import BaseModel, Field


class ReaderChatDefaults(BaseModel):
    model_config = {"extra": "forbid"}

    provider: Literal["openai", "anthropic", "google"] = "openai"
    model_key: str = Field(default="", max_length=120, pattern=r"^[a-zA-Z0-9_.:-]*$")
    language: Literal["fa", "en", "tr", "ar", "es", "it", "de", "fr"] = "en"
    voice_key: str = Field(default="", max_length=120, pattern=r"^[a-zA-Z0-9_.:-]*$")
    voice_consent: bool = False
    retain_voice: bool = False
    continuous_voice: bool = False
    voice_terms: str = Field(default="", max_length=3000)


def chat_defaults(value: object) -> dict[str, object]:
    try:
        return ReaderChatDefaults.model_validate(value or {}).model_dump()
    except (ValueError, TypeError):
        return ReaderChatDefaults().model_dump()
