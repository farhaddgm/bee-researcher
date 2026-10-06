"""Explicit, project-scoped approval of immutable business context for research.

Link/sync never activates context. Preview does not collect, edit news or publish.
The pipeline reads only a pinned, approved brief, never the remote API directly.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import delete, select

from app.business_context import (CompiledBusinessProfile, ContextError, DEFAULT_SECTIONS,
    apply_business_policy, assess_business, business_context_hash, compile_brief, date_value,
    digest, empty_brief, full_article_hash, local_export)
from app.config import Settings, get_settings
from app.database import SessionLocal
from app.models import (AdminAuditLog, AssistantWorkspace, BusinessProfile, ContenterBusinessLink,
    ContenterBusinessSnapshot, NewsBusinessAssessment, NormalizedArticle, ProjectResearchContext,
    ResearchContextPreview, Source, SourceItem, Topic)


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    source: Literal["none", "local", "contenter"] = "none"
    mode: Literal["topics", "contextual", "focused"] = "topics"
    rollout: Literal["shadow", "live"] = "shadow"
    local_business_id: int | None = Field(default=None, ge=1, le=32767)
    sections: list[str] = Field(default_factory=lambda: list(DEFAULT_SECTIONS), max_length=8)
    fact_ids: list[str] | None = Field(default=None, max_length=50)
    business_threshold: float = Field(default=.5, ge=0, le=1, strict=True)
    consent_ai: bool = False
    public_business_facts: bool = False
    sample_limit: int = Field(default=5, ge=1, le=10)


class ActivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: uuid.UUID
    confirmed: Literal[True]


@dataclass
class EffectiveContext:
    record: ProjectResearchContext
    state: str
    profile: CompiledBusinessProfile | None

    @property
    def live(self) -> bool:
        return self.record.rollout == "live"

    def provenance(self, article: NormalizedArticle, model: str = "") -> dict:
        return {"generation": str(self.record.generation), "brief_hash": self.record.semantic_hash,
                "model": model, "article_db_hash": article.content_hash,
                "source": self.record.source, "snapshot_version": self.record.snapshot_version,
                "content_hash": full_article_hash(article.title, article.normalized_text, article.extraction_status != "complete"),
                "report_policy_hash": digest({"brief": self.record.semantic_hash, "style": self.record.style,
                    "public_business_facts": self.record.brief.get("public_business_facts", False)})}


def live_snapshot(record: ProjectResearchContext) -> dict:
    return {"assistant_id": str(record.assistant_id), "generation": str(record.generation), "source": record.source,
            "mode": record.mode, "rollout": "live", "local_business_id": record.local_business_id,
            "external_business_id": record.external_business_id, "link_generation": str(record.link_generation) if record.link_generation else None,
            "snapshot_version": record.snapshot_version, "business_threshold": record.business_threshold,
            "brief": record.brief, "semantic_hash": record.semantic_hash, "style": record.style,
            "activated_by": str(record.activated_by) if record.activated_by else None, "activated_at": record.activated_at.isoformat()}


def restore_live(payload: dict) -> ProjectResearchContext:
    values = dict(payload)
    for key in ("assistant_id", "generation", "link_generation", "activated_by"):
        values[key] = uuid.UUID(values[key]) if values.get(key) else None
    values["activated_at"] = datetime.fromisoformat(values["activated_at"])
    return ProjectResearchContext(**values)


async def resolve_context(session: Any, assistant_id: uuid.UUID | None, settings: Settings | None = None, *, shadow: bool = False) -> EffectiveContext | None:
    if assistant_id is None:
        return None
    record = await session.get(ProjectResearchContext, assistant_id)
    # Also keeps legacy unit fixtures and old, unmanaged projects unchanged.
    if not isinstance(record, ProjectResearchContext):
        return None
    if not shadow and record.rollout == "shadow" and record.previous_live:
        record = restore_live(record.previous_live)
    state = "ready"
    if record.source == "contenter":
        from app.contenter import cache_visible, connection_status
        settings = settings or get_settings()
        link = await session.get(ContenterBusinessLink, assistant_id)
        if not connection_status(settings)["configured"]:
            state = "connection_not_configured"
        elif not link or link.external_business_id != record.external_business_id or link.generation != record.link_generation:
            state = "business_link_changed"
        elif not cache_visible(link, settings):
            state = "business_access_unavailable"
        elif link.version != record.snapshot_version and any(c["kind"] == "fact" for c in record.brief.get("claims", [])):
            latest = await session.scalar(select(ContenterBusinessSnapshot).where(ContenterBusinessSnapshot.assistant_id == assistant_id,
                ContenterBusinessSnapshot.version == link.version, ContenterBusinessSnapshot.external_business_id == link.external_business_id))
            now = datetime.now(timezone.utc)
            valid_ids = {"fact:" + f["id"] for f in (latest.payload.get("facts", []) if latest else [])
                if f.get("isActive") is True and f.get("verified") is True and f.get("source") in {"ADMIN", "AI"}
                and (f.get("validUntil") is None or (date_value(f.get("validUntil")) or now) > now)}
            if any(c["kind"] == "fact" and c["id"] not in valid_ids for c in record.brief.get("claims", [])):
                state = "business_facts_withdrawn"
    elif record.source == "local":
        profile = await session.get(BusinessProfile, record.local_business_id)
        if not profile or profile.assistant_id != assistant_id:
            state = "business_removed"
        else:
            try:
                current = compile_brief(local_export(profile), source="local", sections=record.brief["selected_sections"], fact_ids=record.brief["selected_fact_ids"])
                if current["semantic_hash"] != record.semantic_hash:
                    state = "business_changed"
            except ContextError:
                state = "business_changed"
    now = datetime.now(timezone.utc)
    if any(claim.get("valid_until") and (date_value(claim["valid_until"]) or now) <= now for claim in record.brief.get("claims", [])):
        state = "business_facts_expired"
    compiled = None if record.source == "none" or record.mode == "topics" else CompiledBusinessProfile(
        record.brief["business_name"], record.brief,
        output_language=record.style.get("output_language", "fa"), output_tone=record.style.get("output_tone", ""))
    if state != "ready":
        compiled = None  # Never transmit a cached private brief after revocation/expiry.
    return EffectiveContext(record, state, compiled)


async def candidate(session: Any, assistant_id: uuid.UUID, request: PreviewRequest, settings: Settings) -> dict:
    workspace = await session.get(AssistantWorkspace, assistant_id)
    if not workspace or workspace.deleted_at:
        raise ContextError("assistant_missing")
    existing = await session.get(ProjectResearchContext, assistant_id)
    topics = (await session.scalars(select(Topic).where(Topic.assistant_id == assistant_id, Topic.enabled.is_(True)).order_by(Topic.topic_key))).all()
    selected = (workspace.config or {}).get("active_business_id")
    baseline = None
    if selected or "active_business_id" not in (workspace.config or {}):
        statement = select(BusinessProfile).where(BusinessProfile.assistant_id == assistant_id).order_by(BusinessProfile.id)
        if selected:
            statement = statement.where(BusinessProfile.id == int(selected))
        baseline = await session.scalar(statement)
    style = dict(existing.style) if existing else {"output_language": baseline.output_language if baseline else "fa", "output_tone": baseline.output_tone if baseline else ""}
    generation, version, external, local_id = None, None, None, None
    if request.source == "none":
        if request.mode != "topics":
            raise ContextError("business_required_for_mode")
        brief = empty_brief()
    elif request.source == "local":
        local_id = request.local_business_id or selected
        profile = await session.get(BusinessProfile, local_id) if local_id else None
        if not profile or profile.assistant_id != assistant_id:
            raise ContextError("business_missing")
        brief = compile_brief(local_export(profile), source="local", sections=request.sections, fact_ids=request.fact_ids)
    else:
        from app.contenter import cache_visible, connection_status
        link = await session.get(ContenterBusinessLink, assistant_id)
        if not link or not cache_visible(link, settings) or not connection_status(settings)["configured"]:
            raise ContextError("business_access_unavailable")
        snapshot = await session.scalar(select(ContenterBusinessSnapshot).where(
            ContenterBusinessSnapshot.assistant_id == assistant_id, ContenterBusinessSnapshot.version == link.version,
            ContenterBusinessSnapshot.external_business_id == link.external_business_id))
        if not snapshot:
            raise ContextError("business_snapshot_missing")
        generation, version, external = str(link.generation), snapshot.version, link.external_business_id
        brief = compile_brief(snapshot.payload, source="contenter", sections=request.sections, fact_ids=request.fact_ids)
    if request.source != "none" and not request.consent_ai:
        raise ContextError("ai_data_consent_required")
    if not brief["ready"]:
        raise ContextError("approved_business_facts_required")
    brief = {**brief, "public_business_facts": request.public_business_facts}
    params = request.model_dump()
    proposal = {"params": params, "brief": brief, "style": style, "link_generation": generation,
                "snapshot_version": version, "external_business_id": external, "local_business_id": local_id}
    proposal["input_hash"] = digest({"proposal": proposal, "workspace": workspace.config, "mission": workspace.description,
        "active_generation": str(existing.generation) if existing else None, "model": settings.analysis_model,
        "topics": [{"key": t.topic_key, "name": t.name, "definition": t.definition, "threshold": t.threshold,
                    "positive": t.positive_terms, "negative": t.negative_terms} for t in topics]})
    return proposal


def preview_transition(old: dict, new: dict) -> str:
    return str(old.get("relevance_state", "pending")) + " → " + str(new.get("relevance_state", "pending"))


async def evaluate_preview(assistant_id: uuid.UUID, proposal: dict, settings: Settings) -> dict:
    from app.ai_relevance import assessment_metadata, classify_articles, relevance_decision
    from app.openai_client import OpenAIClient
    from app.pipeline_service import _article_decisions, _finish_job, _reserve_relevance_budget, settings_for_assistant
    settings = await settings_for_assistant(settings, assistant_id)
    params, brief = proposal["params"], proposal["brief"]
    async with SessionLocal() as session:
        workspace = await session.get(AssistantWorkspace, assistant_id)
        topics = (await session.scalars(select(Topic).where(Topic.assistant_id == assistant_id, Topic.enabled.is_(True)).order_by(Topic.topic_key))).all()
        # Use recent enabled-source news, including partial text to expose uncertainty.
        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.freshness_window_days)
        articles = (await session.scalars(select(NormalizedArticle).join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
            .join(Source, Source.id == SourceItem.source_id).where(NormalizedArticle.assistant_id == assistant_id,
            Source.assistant_id == assistant_id, Source.enabled.is_(True), NormalizedArticle.extraction_status.in_(["complete", "partial"]),
            (NormalizedArticle.published_at.is_(None)) | (NormalizedArticle.published_at >= cutoff))
            .order_by(NormalizedArticle.extracted_at.desc()).limit(params["sample_limit"]))).all()
        before = await _article_decisions(session, articles, settings) if articles else {}
    result: dict = {"state": "no_samples" if not articles else "no_topics" if not topics else "pending",
                   "rows": [], "evaluated": 0, "calls": 0, "live_ready": False, "warnings": brief["warnings"]}
    if not articles or not topics:
        return result
    client = OpenAIClient(settings)
    if not client.configured or client.provider_health()["state"] == "cooldown":
        result["state"] = "provider_unavailable"
        return result
    topic_payload = [{"topic_key": t.topic_key, "name": t.name, "definition": t.definition,
        "positive_terms": list(t.positive_terms), "negative_terms": list(t.negative_terms)} for t in topics]
    by_key = {t.topic_key: t for t in topics}
    business = CompiledBusinessProfile(brief["business_name"], brief).semantic_payload() if params["mode"] != "topics" else {}
    batch_size = max(1, min(5, 24 // len(topics)))
    for offset in range(0, len(articles), batch_size):
        batch = articles[offset:offset + batch_size]
        inputs: list[dict[str, Any]] = [{"id": str(a.id), "title": a.title, "text": a.normalized_text,
                   "incomplete": a.extraction_status != "complete"} for a in batch]
        chars = sum(min(len(a["text"]), 20000) + len(a["title"]) for a in inputs) + len(str(business)) + len(str(topic_payload))
        job = await _reserve_relevance_budget(settings, assistant_id, chars, job_type="research_preview_model")
        if not job:
            result["state"] = "budget_deferred"
            return result
        try:
            result["calls"] += 1
            scores = await classify_articles(client, articles=inputs, topics=topic_payload, business=business,
                mission=str(workspace.description or "") if workspace else "", max_input_chars=20000)
            await _finish_job(job, status="succeeded", result={"input_chars": chars, "model": settings.analysis_model})
            business_scores: dict[str, dict] = {}
            if params["mode"] != "topics":
                bchars = sum(min(len(a["text"]), 20000) + len(a["title"]) for a in inputs) + brief["input_chars"]
                job = await _reserve_relevance_budget(settings, assistant_id, bchars, job_type="research_preview_model")
                if not job:
                    result["state"] = "budget_deferred"
                    return result
                result["calls"] += 1
                business_scores = await assess_business(client, articles=inputs, brief=brief, language=proposal["style"]["output_language"])
                await _finish_job(job, status="succeeded", result={"input_chars": bchars, "model": settings.analysis_model})
            for article in batch:
                score_rows = [{**assessment_metadata(meta), "score": score, "valid": True,
                    "topic_key": key, "threshold": max(by_key[key].threshold, settings.relevance_threshold)}
                    for (aid, key), (score, meta) in scores.items() if aid == str(article.id)]
                proposed = relevance_decision(score_rows, topic_count=len(topics), incomplete=article.extraction_status != "complete" or len(article.normalized_text) > 20000)
                proposed = apply_business_policy(proposed, mode=params["mode"], threshold=params["business_threshold"], assessment=business_scores.get(str(article.id)))
                result["rows"].append({"article_id": str(article.id), "title": article.title,
                    "content_hash": full_article_hash(article.title, article.normalized_text, article.extraction_status != "complete"),
                    "before": before[article.id], "after": proposed, "transition": preview_transition(before[article.id], proposed)})
                result["evaluated"] += 1
        except Exception as exc:
            # Persist safe machine codes only; never raw prompts, keys or provider response bodies.
            if job is not None:
                await _finish_job(job, status="failed", result={"model": settings.analysis_model}, error=type(exc).__name__)
            result["state"] = "provider_failed"
            return result
    result.update(state="evaluated", live_ready=True, model=settings.analysis_model)
    return result


async def save_preview(assistant_id: uuid.UUID, actor_id: uuid.UUID, request: PreviewRequest, settings: Settings) -> dict:
    async with SessionLocal() as session:
        proposal = await candidate(session, assistant_id, request, settings)
    result = await evaluate_preview(assistant_id, proposal, settings)
    # Bind to the news text actually evaluated, not only configuration.
    proposal["samples"] = [{"article_id": r["article_id"], "content_hash": r["content_hash"]} for r in result["rows"]]
    preview = ResearchContextPreview(id=uuid.uuid4(), assistant_id=assistant_id, actor_id=actor_id,
        payload=proposal, result=result, input_hash=proposal["input_hash"], expires_at=datetime.now(timezone.utc) + timedelta(minutes=15))
    async with SessionLocal() as session:
        await session.execute(delete(ResearchContextPreview).where(ResearchContextPreview.assistant_id == assistant_id,
            ResearchContextPreview.expires_at < datetime.now(timezone.utc) - timedelta(days=1)))
        session.add(preview)
        await session.commit()
    return {"preview_id": str(preview.id), "expires_at": preview.expires_at.isoformat(), "proposal": proposal, "result": result}


async def activate_preview(session: Any, assistant_id: uuid.UUID, actor_id: uuid.UUID, preview_id: uuid.UUID, settings: Settings) -> ProjectResearchContext:
    workspace = await session.scalar(select(AssistantWorkspace).where(AssistantWorkspace.id == assistant_id).with_for_update())
    if not workspace or workspace.deleted_at:
        raise ContextError("assistant_missing")
    preview = await session.get(ResearchContextPreview, preview_id, with_for_update=True)
    if not preview or preview.assistant_id != assistant_id or preview.actor_id != actor_id:
        raise ContextError("preview_missing")
    if preview.consumed_at or preview.expires_at <= datetime.now(timezone.utc):
        raise ContextError("preview_expired_or_used")
    params = PreviewRequest.model_validate(preview.payload["params"])
    current = await candidate(session, assistant_id, params, settings)
    if current["input_hash"] != preview.input_hash:
        raise ContextError("preview_configuration_changed")
    if params.rollout == "live" and not preview.result.get("live_ready"):
        raise ContextError("evaluated_preview_required")
    for sample in preview.payload.get("samples", []):
        article = await session.get(NormalizedArticle, uuid.UUID(sample["article_id"]))
        if not article or article.assistant_id != assistant_id or sample["content_hash"] != full_article_hash(article.title, article.normalized_text, article.extraction_status != "complete"):
            raise ContextError("preview_news_changed")
    record = await session.get(ProjectResearchContext, assistant_id)
    if not record:
        record = ProjectResearchContext(assistant_id=assistant_id)
        session.add(record)
    if params.rollout == "shadow":
        record.previous_live = live_snapshot(record) if record.rollout == "live" else record.previous_live
    else:
        record.previous_live = None
    record.generation, record.source, record.mode, record.rollout = uuid.uuid4(), params.source, params.mode, params.rollout
    record.local_business_id, record.external_business_id = current["local_business_id"], current["external_business_id"]
    record.link_generation = uuid.UUID(current["link_generation"]) if current["link_generation"] else None
    record.snapshot_version, record.business_threshold = current["snapshot_version"], params.business_threshold
    record.brief, record.semantic_hash, record.style = current["brief"], current["brief"]["semantic_hash"], current["style"]
    record.activated_by, record.activated_at = actor_id, datetime.now(timezone.utc)
    preview.consumed_at = record.activated_at
    session.add(AdminAuditLog(user_id=actor_id, assistant_id=assistant_id, action="research_context.activated",
        details={"generation": str(record.generation), "source": params.source, "mode": params.mode,
                 "rollout": params.rollout, "brief_hash": record.semantic_hash, "version": record.snapshot_version}))
    return record


async def apply_context_decisions(session: Any, articles: list[NormalizedArticle], decisions: dict, context: EffectiveContext | None, settings: Settings) -> dict:
    if not context or context.record.mode == "topics":
        return decisions
    expected = business_context_hash(context.record.brief, settings.analysis_model)
    assessments = (await session.scalars(select(NewsBusinessAssessment).where(
        NewsBusinessAssessment.assistant_id == context.record.assistant_id, NewsBusinessAssessment.context_hash == expected,
        NewsBusinessAssessment.article_id.in_([a.id for a in articles])))).all()
    by_id = {(row.article_id, row.content_hash): row for row in assessments}
    for article in articles:
        row = by_id.get((article.id, full_article_hash(article.title, article.normalized_text, article.extraction_status != "complete")))
        value = row.payload if row and context.state == "ready" else None
        decisions[article.id] = apply_business_policy(decisions[article.id], mode=context.record.mode,
            threshold=context.record.business_threshold, assessment=value, context_state=context.state, shadow=not context.live)
    return decisions


async def view_context(assistant_id: uuid.UUID, settings: Settings) -> dict:
    async with SessionLocal() as session:
        context = await resolve_context(session, assistant_id, settings)
        proposed = await resolve_context(session, assistant_id, settings, shadow=True)
        local = (await session.scalars(select(BusinessProfile).where(BusinessProfile.assistant_id == assistant_id).order_by(BusinessProfile.id))).all()
        link = await session.get(ContenterBusinessLink, assistant_id)
        from app.contenter import cache_visible, connection_status
        link_visible = bool(link and cache_visible(link, settings) and connection_status(settings)["configured"])
        snapshot = await session.scalar(select(ContenterBusinessSnapshot).where(ContenterBusinessSnapshot.assistant_id == assistant_id,
            ContenterBusinessSnapshot.version == link.version, ContenterBusinessSnapshot.external_business_id == link.external_business_id)) if link_visible and link else None
        active = None
        if context:
            r = context.record
            # Revoked/expired remote access must not reveal its retained private brief.
            disclose = r.source != "contenter" or context.state not in {"connection_not_configured", "business_access_unavailable", "business_link_changed"}
            active = {"generation": str(r.generation), "source": r.source, "mode": r.mode, "rollout": r.rollout,
                "business_threshold": r.business_threshold, "snapshot_version": r.snapshot_version,
                "latest_version": link.version if link_visible and link else None,
                "state": context.state, "brief": r.brief if disclose else None,
                "local_business_id": r.local_business_id, "activated_at": r.activated_at.isoformat()}
        return {"active": active, "shadow_pending": bool(proposed and proposed.record.rollout == "shadow" and proposed.record.previous_live),
                "local_businesses": [{"id": p.id, "name": p.business_name} for p in local],
                "contenter_available": link_visible, "facts": snapshot.payload.get("facts", []) if snapshot else []}


router = APIRouter(prefix="/admin/api", tags=["research-context"])


async def authorize(token: str | None, assistant_id: uuid.UUID, *, write: bool = False) -> Any:
    from app.contenter import _user
    return await _user(token, assistant_id, write=write)


@router.get("/assistants/{assistant_id}/research-context")
async def get_context(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict:
    await authorize(token, assistant_id)
    try:
        await authorize(token, assistant_id, write=True)
        can_write = True
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        can_write = False
    return {**await view_context(assistant_id, get_settings()), "can_write": can_write}


@router.post("/assistants/{assistant_id}/research-context/preview")
async def preview_context(assistant_id: uuid.UUID, payload: PreviewRequest,
        token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict:
    actor = await authorize(token, assistant_id, write=True)
    try:
        result = await save_preview(assistant_id, actor.id, payload, get_settings())
        await authorize(token, assistant_id, write=True)
        return result
    except ContextError as exc:
        raise HTTPException(409, exc.code) from None


@router.post("/assistants/{assistant_id}/research-context/activate")
async def activate_context(assistant_id: uuid.UUID, payload: ActivateRequest,
        token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict:
    actor = await authorize(token, assistant_id, write=True)
    try:
        async with SessionLocal() as session:
            await activate_preview(session, assistant_id, actor.id, payload.preview_id, get_settings())
            await authorize(token, assistant_id, write=True)
            await session.commit()
    except ContextError as exc:
        raise HTTPException(409, exc.code) from None
    return {**await view_context(assistant_id, get_settings()), "can_write": True}


@router.get("/assistants/{assistant_id}/research-context/articles/{article_id}")
async def article_context(assistant_id: uuid.UUID, article_id: uuid.UUID,
        token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict:
    await authorize(token, assistant_id)
    async with SessionLocal() as session:
        article = await session.get(NormalizedArticle, article_id)
        if not article or article.assistant_id != assistant_id:
            raise HTTPException(404, "article_missing")
        context = await resolve_context(session, assistant_id)
        if not context or context.state != "ready":
            return {"items": [], "state": context.state if context else "unmanaged"}
        expected = business_context_hash(context.record.brief, (await _effective_settings(assistant_id)).analysis_model)
        rows = (await session.scalars(select(NewsBusinessAssessment).where(NewsBusinessAssessment.assistant_id == assistant_id,
            NewsBusinessAssessment.article_id == article_id, NewsBusinessAssessment.context_hash == expected))).all()
        return {"state": context.state, "items": [{"assessment": r.payload, "created_at": r.created_at.isoformat(),
            "current_text": r.content_hash == full_article_hash(article.title, article.normalized_text, article.extraction_status != "complete")} for r in rows]}


async def _effective_settings(assistant_id: uuid.UUID) -> Settings:
    from app.pipeline_service import settings_for_assistant
    return await settings_for_assistant(get_settings(), assistant_id)
