"""Read-only, workspace-scoped product health. Liveness is not AI readiness."""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app.config import get_settings
from app.database import SessionLocal
from app.models import AssistantWorkspace, JobRun, Source, Topic
from app.openai_client import OpenAIClient
from app.pipeline_service import _local_day_start_utc, _utcnow, pipeline_metrics, settings_for_assistant


PROVIDER_CODES = frozenset({"provider_quota_exhausted", "provider_authentication_failed", "provider_model_unavailable"})


def observed_provider_state(*, configured: bool, latest: JobRun | None, cooling: dict) -> dict:
    """Expose safe, dated observations, never declare a key to be a healthy API."""
    code = str(latest.error_message or "") if latest is not None else ""
    result = {"configured": configured, "state": "not_checked" if configured else "not_configured",
              "code": None, "observed_at": latest.finished_at or latest.created_at if latest is not None else None}
    if not configured:
        return result
    if cooling.get("state") == "cooldown":
        return {**result, "state": "blocked", "code": cooling.get("code"), "retry_after_seconds": cooling.get("retry_after_seconds", 0)}
    if latest is not None:
        if latest.status == "running" and latest.created_at >= _utcnow() - timedelta(minutes=10):
            result["state"] = "processing"
        elif latest.status == "failed":
            result.update(state="blocked" if code in PROVIDER_CODES else "error", code=code if code in PROVIDER_CODES else "provider_request_failed")
        elif latest.status == "succeeded":
            result["state"] = "last_attempt_succeeded"
    return result


async def operations_status(*, assistant_id: uuid.UUID) -> dict[str, object]:
    settings = await settings_for_assistant(get_settings(), assistant_id)
    now = _utcnow()
    day_start = _local_day_start_utc(now, settings.timezone)
    client = OpenAIClient(settings)
    async with SessionLocal() as session:
        workspace = await session.get(AssistantWorkspace, assistant_id)
        source_count = int(await session.scalar(select(func.count(Source.id)).where(Source.assistant_id == assistant_id, Source.enabled.is_(True))) or 0)
        topic_count = int(await session.scalar(select(func.count(Topic.id)).where(Topic.assistant_id == assistant_id, Topic.enabled.is_(True))) or 0)
        latest = await session.scalar(select(JobRun).where(JobRun.assistant_id == assistant_id, JobRun.job_type.in_(["relevance_model", "analysis_model"]),
            # Quota/auth failures affect the account; model errors only describe
            # that model. Do not show a previous model's failure as current.
            ((JobRun.result["model"].as_string() == settings.analysis_model) | JobRun.result["model"].as_string().is_(None) |
             JobRun.error_message.in_(["provider_quota_exhausted", "provider_authentication_failed"])),
        ).order_by(JobRun.created_at.desc()).limit(1))
        provider = observed_provider_state(configured=client.configured, latest=latest, cooling=client.provider_health())
        budgets = {}
        for kind, cap in (("relevance_model", settings.relevance_daily_request_cap), ("analysis_model", settings.model_daily_request_cap)):
            count, chars = (await session.execute(select(func.count(JobRun.id), func.coalesce(func.sum(JobRun.result["input_chars"].as_integer()), 0)).where(
                JobRun.assistant_id == assistant_id, JobRun.job_type == kind, JobRun.created_at >= day_start,
            ))).one()
            budgets[kind] = {"used_requests": int(count), "request_cap": cap, "remaining_requests": max(0, cap - int(count)),
                             "used_input_chars": int(chars), "input_char_cap": settings.model_daily_input_char_cap}
        collection = await session.scalar(select(JobRun).where(JobRun.assistant_id == assistant_id, JobRun.job_type == "market_pipeline").order_by(JobRun.created_at.desc()).limit(1))
        config = dict(workspace.config or {}) if workspace else {}
        runtime = config.get("runtime") or {}
    metrics = await pipeline_metrics(assistant_id=assistant_id)
    blockers = []
    if workspace is None or workspace.deleted_at is not None or workspace.status != "active":
        blockers.append("workspace_inactive")
    if not source_count:
        blockers.append("no_enabled_sources")
    if not topic_count:
        blockers.append("no_enabled_topics")
    if not client.configured:
        blockers.append("provider_not_configured")
    elif provider["state"] in {"blocked", "error"}:
        blockers.append(provider["code"])
    elif metrics.get("pending_ai_articles", 0) and budgets["relevance_model"]["remaining_requests"] == 0:
        blockers.append("relevance_budget_reached")
    return {"assistant_id": str(assistant_id), "checked_at": now, "timezone": settings.timezone,
            "model": settings.analysis_model, "provider": provider, "blockers": blockers,
            "state": "needs_attention" if blockers else "processing" if provider["state"] == "processing" else "awaiting_analysis" if metrics.get("pending_ai_articles", 0) else "operational",
            "pending_ai_articles": metrics.get("pending_ai_articles", 0), "enabled_sources": source_count, "enabled_topics": topic_count,
            "budgets": budgets, "budget_day_start": day_start, "collection_enabled": runtime.get("collection_enabled", True) is not False,
            "last_collection_at": collection.finished_at or collection.started_at if collection is not None else None,
            "last_collection_state": collection.status if collection is not None else "not_run",
            "no_external_request": True}
