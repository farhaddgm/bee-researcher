from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Annotated

TokenCount = Annotated[int, Field(strict=True, ge=0, le=1_000_000_000_000)]


class Limits(BaseModel):
    model_config = ConfigDict(extra='forbid')
    six_hours: TokenCount | None = None
    daily: TokenCount | None = None
    monthly: TokenCount | None = None
    total: TokenCount | None = None


class SaveLimit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    assistant_id: UUID | None = None
    user_id: UUID | None = None
    inherit: bool = Field(default=False, strict=True)
    limits: Limits
    version: int = Field(ge=0, strict=True)

    @model_validator(mode='after')
    def scope(self):
        if self.assistant_id is None and (self.user_id is not None or self.inherit):
            raise ValueError('global defaults cannot inherit or target a user')
        return self
