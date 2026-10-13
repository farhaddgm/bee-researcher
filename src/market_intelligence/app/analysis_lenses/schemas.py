from __future__ import annotations

import hashlib
import json
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

Language = Literal['fa', 'en', 'tr', 'ar', 'es', 'it', 'de', 'fr']
Section = Literal['opportunities', 'risks', 'counterpoints', 'next_questions', 'suggested_checks', 'connections']


def default_sections() -> list[Section]:
    return ['opportunities', 'risks', 'counterpoints', 'next_questions']


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


class Dimension(Strict):
    key: str = Field(min_length=1, max_length=60, pattern=r'^[a-z][a-z0-9_]*$')
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    questions: list[str] = Field(min_length=1, max_length=5)
    required_information: list[str] = Field(default_factory=list, max_length=5)
    priority: Literal['high', 'normal', 'low'] = 'normal'
    enabled: bool = True

    @model_validator(mode='after')
    def bounded(self):
        if any(not x.strip() or len(x) > 250 for x in self.questions + self.required_information):
            raise ValueError('dimension items must contain 1 to 250 characters')
        if not self.name.strip() or not self.description.strip():
            raise ValueError('dimension text is required')
        return self


class Labels(Strict):
    name: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=240)


class Definition(Strict):
    source_language: Language = 'en'
    name: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=240)
    definition: str = Field(min_length=1, max_length=1500)
    objective: str = Field(min_length=1, max_length=800)
    in_scope: list[str] = Field(default_factory=list, max_length=8)
    out_of_scope: list[str] = Field(default_factory=list, max_length=8)
    dimensions: list[Dimension] = Field(min_length=1, max_length=24)
    output_sections: list[Section] = Field(default_factory=default_sections)
    quality_criteria: list[str] = Field(min_length=1, max_length=8)
    examples: list[dict[str, str]] = Field(default_factory=list, max_length=3)
    localized_labels: dict[Language, Labels] = Field(default_factory=dict)

    def executable(self) -> dict:
        value = self.model_dump(exclude={'examples', 'localized_labels'})
        value['dimensions'] = [d.model_dump(exclude={'enabled'}) for d in self.dimensions if d.enabled]
        return value

    @model_validator(mode='after')
    def valid_definition(self):
        keys = [d.key for d in self.dimensions]
        if len(set(keys)) != len(keys) or not 1 <= sum(d.enabled for d in self.dimensions) <= 12:
            raise ValueError('one to twelve active, uniquely identified dimensions required')
        if len(set(self.output_sections)) != len(self.output_sections):
            raise ValueError('duplicate output section')
        if any(not x.strip() or len(x) > 200 for x in self.in_scope + self.out_of_scope):
            raise ValueError('scope item too large or empty')
        if any(not x.strip() or len(x) > 300 for x in self.quality_criteria):
            raise ValueError('quality criterion too large or empty')
        if any(set(x) != {'good', 'bad'} or any(not v.strip() or len(v) > 1200 for v in x.values()) for x in self.examples):
            raise ValueError('example needs bounded good and bad text')
        if any(not getattr(self, key).strip() for key in ('name', 'summary', 'definition', 'objective')):
            raise ValueError('definition text is required')
        if len(json.dumps(self.executable(), ensure_ascii=False)) > 6000:
            raise ValueError('executable definition exceeds 6000 characters')
        content = json.dumps(self.model_dump(mode='json'), ensure_ascii=False)
        if re.search(r'(?:\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}|\bgh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:api[_ -]?key|password|token)\s*[:=]\s*[A-Za-z0-9_-]{16,})', content, re.I):
            raise ValueError('secret-like content is not permitted in a global lens')
        return self


class Create(Strict):
    key: str = Field(min_length=1, max_length=60, pattern=r'^[a-z][a-z0-9_]*$')
    definition: Definition


class Draft(Strict):
    expected_version: int = Field(ge=1)
    definition: Definition


class Policy(Strict):
    enabled: bool = False
    default_key: str = Field(default='general', min_length=1, max_length=60)
    output_tokens: int = Field(default=6000, ge=2000, le=8000)
    input_characters: int = Field(default=48000, ge=12000, le=64000)
    version: int = Field(default=1, ge=1)


class RevisionAction(Strict):
    expected_version: int = Field(ge=1)
    revision: int = Field(ge=1)
    definition_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    preview_id: UUID | None = None
    approved: bool = False
    reason: str = Field(default='', max_length=300)
    replacement_key: str | None = Field(default=None, max_length=60)


class Preview(Strict):
    revision: int = Field(ge=1)
    definition_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    publication_id: UUID
    model_key: str = Field(min_length=3, max_length=120)
    language: Language = 'fa'
    idempotency_key: str = Field(min_length=16, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')


class Selection(Strict):
    scope: Literal['focused', 'contextual'] = 'focused'
    lens_id: UUID
    lens_revision: int = Field(ge=1)
    lens_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    discovery_snapshot_id: UUID | None = None
    lookback_days: Literal[7, 30, 90, 365] = 30

    @model_validator(mode='after')
    def discovery(self):
        if (self.scope == 'contextual') != bool(self.discovery_snapshot_id):
            raise ValueError('contextual analysis requires discovery snapshot; focused must not have one')
        return self


class Discovery(Strict):
    lookback_days: Literal[7, 30, 90, 365] = 30


class Claim(Strict):
    text: str = Field(min_length=1, max_length=1200)
    quote: str = Field(min_length=1, max_length=600, description='Short, exact contiguous quotation from a cited segment, in its original language. Do not translate or paraphrase.')
    citations: list[str] = Field(min_length=1, max_length=8)


class Finding(Strict):
    dimension: str = Field(min_length=1, max_length=60)
    heading: str = Field(min_length=1, max_length=120)
    status: Literal['supported', 'limited', 'insufficient', 'not_applicable']
    finding: str = Field(min_length=1, max_length=1600)
    citations: list[str] = Field(default_factory=list, max_length=8)
    assumptions: list[str] = Field(default_factory=list, max_length=5)
    gaps: list[str] = Field(default_factory=list, max_length=5)


class Effect(Strict):
    dimension: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=1200)
    mechanism: str = Field(min_length=1, max_length=1200)
    conditions: list[str] = Field(min_length=1, max_length=5)
    support: Literal['adequate', 'limited', 'insufficient']
    citations: list[str] = Field(min_length=1, max_length=8)


class Connection(Strict):
    publication_id: UUID
    explanation: str = Field(min_length=1, max_length=1200)
    citations: list[str] = Field(min_length=1, max_length=8)


class Result(Strict):
    schema_version: Literal[1] = 1
    summary: str = Field(min_length=1, max_length=1800)
    reported_claims: list[Claim] = Field(default_factory=list, max_length=12)
    dimensions: list[Finding] = Field(min_length=1, max_length=12)
    opportunities: list[Effect] = Field(default_factory=list, max_length=8)
    risks: list[Effect] = Field(default_factory=list, max_length=8)
    connections: list[Connection] = Field(default_factory=list, max_length=4)
    counterpoints: list[str] = Field(default_factory=list, max_length=6)
    next_questions: list[str] = Field(default_factory=list, max_length=6)
    suggested_checks: list[str] = Field(default_factory=list, max_length=6)
    limitations: list[str] = Field(min_length=1, max_length=8)

    @model_validator(mode='after')
    def bound_items(self):
        items = self.counterpoints + self.next_questions + self.suggested_checks + self.limitations
        items += [v for d in self.dimensions for v in d.assumptions + d.gaps]
        items += [v for d in self.opportunities + self.risks for v in d.conditions]
        if any(not v.strip() or len(v) > 1200 for v in items):
            raise ValueError('result item empty or too large')
        return self
