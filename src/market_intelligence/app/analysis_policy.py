"""Owner-managed per-project analyzer limits. Never store provider credentials."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.database import SessionLocal
from app.models import AssistantWorkspace


class AnalysisPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    relevance_review_margin: float = Field(default=.10, ge=0, le=.25)
    relevance_min_confidence: float = Field(default=.65, ge=.35, le=1)
    relevance_min_score: float = Field(default=.10, ge=0, le=.5)
    relevance_max_input_chars: int = Field(default=20000, ge=2000, le=64000)
    relevance_batch_size: int = Field(default=4, ge=1, le=8)
    relevance_max_requests_per_run: int = Field(default=10, ge=0, le=100)
    relevance_daily_request_cap: int = Field(default=100, ge=0, le=1000)
    model_daily_request_cap: int = Field(default=30, ge=0, le=500)


def policy_values(config: dict) -> dict:
    # Old projects retain their deployment budgets until explicitly saved.
    value = config.get("analysis_policy")
    return AnalysisPolicy.model_validate(value).model_dump() if isinstance(value, dict) else {}


router = APIRouter(prefix="/admin/api/assistants", tags=["analysis-policy"])


async def owner_access(token: str | None, assistant_id: uuid.UUID):
    from app.admin import current_admin, is_owner, _require_assistant_access
    user = await current_admin(token)
    if not is_owner(user):
        raise HTTPException(403, "owner role required")
    await _require_assistant_access(assistant_id, user, write=True)
    return user


@router.get("/{assistant_id}/analysis-policy")
async def get_policy(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict:
    await owner_access(token, assistant_id)
    from app.config import get_settings
    from app.pipeline_service import settings_for_assistant
    settings = await settings_for_assistant(get_settings(), assistant_id)
    return {"assistant_id": str(assistant_id), "values": {key: getattr(settings, key) for key in AnalysisPolicy.model_fields},
            "defaults": AnalysisPolicy().model_dump(), "owner_only": True, "scoring": "one_valid_assessment_per_content_and_context"}


@router.put("/{assistant_id}/analysis-policy")
async def put_policy(assistant_id: uuid.UUID, payload: AnalysisPolicy,
                     token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict:
    user = await owner_access(token, assistant_id)
    from app.admin import _audit
    async with SessionLocal() as session:
        item = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        if item is None:
            raise HTTPException(404, "assistant not found")
        config = dict(item.config or {})
        config["analysis_policy"] = payload.model_dump()
        config["analysis_policy_updated_at"] = datetime.now(timezone.utc).isoformat()
        item.config = config
        await session.commit()
    await _audit(user.id, "assistant.analysis_policy.update", assistant_id=assistant_id,
                 details={"fields": list(AnalysisPolicy.model_fields)})
    return await get_policy(assistant_id, token)
