"""Validated, account-owned answer length guidance, frozen for each request."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

LengthMode = Literal["short", "medium", "long", "auto"]


class CharacterRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: int = Field(ge=1, le=20000, strict=True)
    max: int = Field(ge=1, le=20000, strict=True)

    @model_validator(mode="after")
    def ordered(self):
        if self.min > self.max:
            raise ValueError("minimum characters must not exceed maximum")
        return self


class CharacterRanges(BaseModel):
    model_config = ConfigDict(extra="forbid")

    short: CharacterRange = Field(default_factory=lambda: CharacterRange(min=200, max=600))
    medium: CharacterRange = Field(default_factory=lambda: CharacterRange(min=600, max=1600))
    long: CharacterRange = Field(default_factory=lambda: CharacterRange(min=1600, max=4000))

    @model_validator(mode="after")
    def increasing(self):
        if not (self.short.min <= self.medium.min <= self.long.min
                and self.short.max <= self.medium.max <= self.long.max):
            raise ValueError("short, medium and long ranges must increase in that order")
        return self


class AnswerLength(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: LengthMode = "auto"
    characters: CharacterRanges = Field(default_factory=CharacterRanges)

    def instruction(self) -> str:
        if self.mode == "auto":
            return (" Choose the answer length yourself according to the question, available evidence and complexity. "
                    "Avoid unnecessary repetition; do not pad an answer to meet a character target.")
        target = getattr(self.characters, self.mode)
        return (f" The user's answer length preference is {self.mode}: aim for approximately "
                f"{target.min}-{target.max} characters in the entire answer, including spaces and citations. "
                "This length preference overrides requests for detailed treatment in the task format: prioritize "
                "the most useful points within the range. Preserve essential qualifications and exact citations; "
                "never invent content to reach the minimum or cut off a sentence, citation or required JSON structure. "
                "Evidence, accuracy and completeness of those essential elements take priority over the target.")
