from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from decimal import Decimal, InvalidOperation
from collections.abc import Mapping, Sequence
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import String, and_, case, cast, delete, distinct, exists, false as false_condition, func, or_, select, true, update
from sqlalchemy.engine import Row
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from app.article_extraction import ArticleDocument, ArticleFetcher
from app.config import Settings, get_settings
from app.ai_relevance import SCORER_REVISION, article_digest, assessment_metadata, classify_articles, relevance_context_hash, relevance_decision
from app.business_context import CompiledBusinessProfile, assess_business, business_context_hash, full_article_hash
from app.research_context import resolve_context, apply_context_decisions
from app.database import SessionLocal
from app.fetchers import FetchFailure
from app.ingestion_service import DEFAULT_ASSISTANT_ID, run_ingestion, run_sources_independently
from app.models import (
    ArticleAnalysis,
    ArticleTopic,
    BusinessProfile,
    ClusterMember,
    EventCluster,
    Feedback,
    JobRun,
    NormalizedArticle,
    Publication,
    Source,
    SourceItem,
    Topic,
    WeeklyReport,
    AssistantWorkspace,
    NewsBusinessAssessment,
)
from app.openai_client import (
    OpenAIClient,
    StructuredAnalysis,
    sanitize_untrusted_source,
)
from app.queue_names import pipeline_lock_key
from app.report_language import LANGUAGES, LANGUAGE_REVISION, LIST_FIELDS, TEXT_FIELDS, ReportLanguageError, analysis_language, analysis_text, language_issues, prose_matches_language, report_copy
from app.security_controls import redact_sensitive_text
from app.retention import effective_retention_days
from app.relevance import (
    cluster_key,
    combine_topic_score,
    jaccard_similarity,
    lexical_topic_score,
)
from app.telegram_delivery import (
    MESSAGE_TEMPLATE_VERSION,
    TelegramClient,
    render_analysis_message,
)


SENTENCE_BREAK = re.compile(r"(?<=[.!؟])\s+|\n+")
LOGGER = logging.getLogger(__name__)

# Borderline items are intentionally visible to an operator, but they never
# become publishable on their own.  A tenth of a point is wide enough to catch
# useful misses without turning the review queue into a copy of every feed.
REVIEW_MARGIN = 0.10


class BusinessContext(Protocol):
    business_name: str
    description: str
    products_services: str
    target_customers: str
    markets: str
    revenue_model: str
    strategic_goals: str
    competitors: list
    sensitivities: list
    output_language: str
    output_tone: str


@dataclass
class GeneralMarketContext:
    business_name: str
    description: str
    products_services: str = ""
    target_customers: str = ""
    markets: str = ""
    revenue_model: str = ""
    strategic_goals: str = ""
    competitors: list = field(default_factory=list)
    sensitivities: list = field(default_factory=list)
    output_language: str = "fa"
    output_tone: str = "کوتاه، تحلیلی و اجرایی"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _payload_float(value: object, *, default: float = 0.0) -> float:
    """Parse only JSON-like numeric scalars from generated/fallback payloads."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError, InvalidOperation):
        return default
    return result if math.isfinite(result) else default


def _payload_int(value: object, *, default: int = 0) -> int:
    parsed = _payload_float(value, default=float("nan"))
    return int(parsed) if math.isfinite(parsed) and parsed.is_integer() else default


def _render_publication_message(
    *,
    analysis: ArticleAnalysis,
    article: NormalizedArticle,
    source: Source,
    business_name: str = "داتین",
    template_blocks: list[dict[str, object]] | None = None,
    output_language: str | None = None,
) -> str:
    """Keep native titles canonical; foreign titles need faithful translation.

    Never splice untranslated excerpts into localized template headings. A
    budget/provider failure is a pending translation, not a translated report.
    The original title/body remain immutable in NormalizedArticle.
    """
    language = output_language or analysis_language(analysis, source)
    copy = report_copy(language)
    headline = article.title
    translated_title = str(getattr(analysis, "headline", "") or "")
    original_language = str(getattr(article, "language", "") or getattr(source, "language", "") or "").casefold()
    if (original_language in LANGUAGES and original_language != language) or not prose_matches_language(headline, language):
        headline = translated_title
    issues = language_issues(analysis_text(analysis), language)
    stale_language = any(isinstance(citation, dict) and citation.get("output_language") and citation["output_language"] != language for citation in (getattr(analysis, "citations", None) or []))
    pending = bool(stale_language or issues or not headline or not prose_matches_language(headline, language))
    return render_analysis_message(
        headline=copy["pending_title"] if pending else headline,
        summary=copy["pending_summary"] if pending else analysis.news_summary,
        business_connection=copy["analysis_pending"] if pending else analysis.business_connection,
        opportunity="" if pending else analysis.opportunity,
        risk="" if pending else analysis.risk,
        action=analysis.suggested_action,
        confidence=analysis.confidence,
        source_name=source.name,
        source_url=article.canonical_url,
        published_at=article.published_at.isoformat() if article.published_at else None,
        incomplete=article.extraction_status == "partial",
        business_name=business_name or "داتین",
        template_blocks=template_blocks,
        output_language=language,
    )


def _template_has_image(blocks: object) -> bool:
    if not isinstance(blocks, list):
        return False
    return any(
        isinstance(block, dict)
        and str(block.get("type") or "") == "image"
        and bool(block.get("visible", True))
        for block in (blocks or [])
    )


async def settings_for_assistant(settings: Settings, assistant_id: uuid.UUID | None) -> Settings:
    """Resolve safe, non-secret runtime settings for one assistant.

    Secrets remain deployment-managed. Workspace configuration may override
    destinations, model, output cap, freshness window and feedback allowlist.
    """
    if assistant_id is None:
        return settings
    async with SessionLocal() as session:
        assistant = await session.get(AssistantWorkspace, assistant_id)
        research = await resolve_context(session, assistant_id, settings) if isinstance(assistant, AssistantWorkspace) else None
        active_profile: BusinessContext | None = None
        if isinstance(assistant, AssistantWorkspace):
            selected_id = (assistant.config or {}).get("active_business_id")
            profile_query = select(BusinessProfile).where(BusinessProfile.assistant_id == assistant_id)
            if selected_id:
                profile_query = profile_query.where(BusinessProfile.id == int(selected_id))
            if selected_id or "active_business_id" not in (assistant.config or {}):
                active_profile = (await session.execute(profile_query.order_by(BusinessProfile.id))).scalars().first()
    if assistant is None:
        return settings
    telegram = (assistant.config or {}).get("telegram") or {}
    runtime = (assistant.config or {}).get("runtime") or {}
    if "relevance_threshold" not in runtime and assistant_id != DEFAULT_ASSISTANT_ID:
        # Topic thresholds are authoritative unless an admin explicitly adds
        # a project-wide floor. Do not silently raise a configured .20 to .45.
        settings = settings.model_copy(update={"relevance_threshold": 0.0})
    if isinstance(runtime.get("relevance_threshold"), (int, float)) and not isinstance(runtime.get("relevance_threshold"), bool) and 0 <= runtime["relevance_threshold"] <= 1:
        settings = settings.model_copy(update={"relevance_threshold": float(runtime["relevance_threshold"])})
    sandbox = (assistant.config or {}).get("sandbox") or {}
    raw_limits = (assistant.config or {}).get("limits") or {}
    try:
        max_items_limit = min(max(int(raw_limits.get("max_items_per_run", 7)), 1), 7)
    except (TypeError, ValueError):
        max_items_limit = 7
    try:
        freshness_limit = min(max(int(raw_limits.get("max_freshness_window_days", 7)), 1), 7)
    except (TypeError, ValueError):
        freshness_limit = 7
    message_templates = (assistant.config or {}).get("message_templates") or {}
    updates: dict[str, object] = {}
    if research and research.live:
        # Do not leak a legacy/local business label into explicitly business-free projects.
        active_profile = research.profile
    # The message renderer must use the active workspace's business name; the
    # deployment default is only a backwards-compatible fallback for the
    # legacy workspace.
    if research and research.live:
        updates["business_name"] = str(active_profile.business_name).strip() if active_profile else assistant.name
    elif active_profile is not None and str(active_profile.business_name).strip():
        updates["business_name"] = str(active_profile.business_name).strip()
    else:
        workspace_name = getattr(assistant, "business_name", None)
        if isinstance(workspace_name, str) and workspace_name.strip():
            updates["business_name"] = workspace_name.strip()
        else:
            # Do not fall back to the legacy Dotin label for a workspace that
            # intentionally has no business profile.  The assistant name is
            # a neutral, deterministic label for generated messages.
            assistant_name = str(getattr(assistant, "name", "") or "").strip()
            if assistant_name:
                updates["business_name"] = assistant_name
    # The original Dotin workspace may inherit deployment-managed channel
    # destinations. Every newly-created workspace is isolated and must opt in
    # with its own channel IDs; otherwise readiness must fail fast instead of
    # probing or publishing to the original project's channel.
    if assistant_id == DEFAULT_ASSISTANT_ID:
        if "feedback_channel_id" in telegram:
            updates["telegram_channel_id"] = telegram.get("feedback_channel_id") or None
        if "observer_channel_id" in telegram:
            updates["telegram_observer_channel_id"] = telegram.get("observer_channel_id") or None
    else:
        updates["telegram_channel_id"] = telegram.get("feedback_channel_id") or None
        updates["telegram_observer_channel_id"] = telegram.get("observer_channel_id") or None
    if isinstance(runtime.get("max_items_per_run"), int) and 1 <= runtime["max_items_per_run"] <= 7:
        updates["max_items_per_run"] = min(runtime["max_items_per_run"], max_items_limit)
    if isinstance(runtime.get("freshness_window_days"), int) and 1 <= runtime["freshness_window_days"] <= 7:
        updates["freshness_window_days"] = min(runtime["freshness_window_days"], freshness_limit)
    # Daily collection budgets are calendar-day budgets in the workspace's
    # configured timezone.  Keep the effective Settings aligned with the
    # scheduler/runtime timezone so a project does not roll over at UTC
    # midnight while its owner is still in the previous local day.
    timezone_name = runtime.get("timezone")
    if isinstance(timezone_name, str) and timezone_name.strip():
        timezone_name = timezone_name.strip()
        try:
            ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
        else:
            updates["timezone"] = timezone_name
    # Owner-managed collection limits reuse the existing bounded pipeline
    # settings.  Publication limits stay on max_items_per_run and are never
    # reduced by these values.
    if isinstance(runtime.get("collection_max_items_per_source"), int) and 1 <= runtime["collection_max_items_per_source"] <= 200:
        updates["fetch_max_items_per_source"] = runtime["collection_max_items_per_source"]
    if isinstance(runtime.get("collection_max_items_per_run"), int) and 1 <= runtime["collection_max_items_per_run"] <= 1000:
        updates["pipeline_max_candidates_per_run"] = runtime["collection_max_items_per_run"]
    if isinstance(runtime.get("collection_max_items_per_day"), int) and 1 <= runtime["collection_max_items_per_day"] <= 1000:
        updates["processing_max_items_per_day"] = runtime["collection_max_items_per_day"]
    if isinstance(runtime.get("telegram_silent_notifications"), bool):
        updates["telegram_silent_notifications"] = runtime["telegram_silent_notifications"]
    if isinstance(sandbox, dict) and sandbox.get("enabled"):
        # A sandbox can analyse and build previews, but it must never inherit
        # a real destination or publish automatically.
        updates["pilot_mode"] = True
        updates["auto_publish"] = False
    if isinstance(runtime.get("analysis_model"), str) and runtime["analysis_model"]:
        updates["analysis_model"] = runtime["analysis_model"]
    users = runtime.get("allowed_feedback_usernames")
    if isinstance(users, list):
        updates["allowed_telegram_usernames"] = ",".join(str(value).strip().lower().lstrip("@") for value in users if str(value).strip())
    if isinstance(message_templates, dict):
        # The admin API validates the block vocabulary and ordering. Runtime
        # code only accepts the persisted JSON object and never evaluates it.
        updates["message_templates"] = message_templates
    return settings.model_copy(update=updates) if updates else settings


def _not_retention_tombstone():
    """Exclude source items whose content was erased by the retention job."""
    return ~SourceItem.raw_metadata.has_key("retention_purged_at")


def _freshness_condition(column, settings: Settings):
    """Accept undated feed items, but reject dated items older than the window."""
    cutoff = _utcnow() - timedelta(days=settings.freshness_window_days)
    return or_(column.is_(None), column >= cutoff)


async def _profile_for_assistant(session, assistant_id: uuid.UUID | None) -> BusinessProfile | CompiledBusinessProfile | None:
    context = await resolve_context(session, assistant_id)
    if context and context.live:
        return context.profile
    statement = select(BusinessProfile).order_by(BusinessProfile.id)
    if assistant_id is not None:
        statement = statement.where(BusinessProfile.assistant_id == assistant_id)
        assistant = await session.get(AssistantWorkspace, assistant_id)
        if assistant is not None:
            if "active_business_id" in (assistant.config or {}) and not (assistant.config or {}).get("active_business_id"):
                return None
            selected = (assistant.config or {}).get("active_business_id")
            if selected:
                selected_statement = select(BusinessProfile).where(
                    BusinessProfile.id == int(selected), BusinessProfile.assistant_id == assistant_id
                )
                chosen = (await session.execute(selected_statement)).scalar_one_or_none()
                # A deleted/invalid explicitly selected profile must never
                # silently switch the project to a different business.
                return chosen
    return (await session.execute(statement)).scalars().first()


def _relevance_hash(settings: Settings, assistant: AssistantWorkspace | None, topics: Sequence[Topic], profile: BusinessContext | None) -> str:
    return relevance_context_hash({
        "revision": SCORER_REVISION, "model": settings.analysis_model,
        "assistant_id": str(getattr(assistant, "id", "")),
        "topics": [{"topic_key": t.topic_key, "name": t.name, "definition": t.definition,
                    "positive_terms": list(t.positive_terms), "negative_terms": list(t.negative_terms)} for t in topics],
        "business": _profile_payload(profile) if profile else {},
        "mission": str(getattr(assistant, "description", "") or ""),
    })


async def _article_decisions(session, articles: Sequence[NormalizedArticle], settings: Settings) -> dict[uuid.UUID, dict]:
    """Bulk read; never trust historical selected flags or lexical/feedback scores."""
    decisions = {}
    for assistant_id in {a.assistant_id for a in articles}:
        scoped = [a for a in articles if a.assistant_id == assistant_id]
        effective = await settings_for_assistant(settings, assistant_id)
        assistant = await session.get(AssistantWorkspace, assistant_id)
        profile = await _profile_for_assistant(session, assistant_id)
        topics = (await session.scalars(select(Topic).where(Topic.assistant_id == assistant_id, Topic.enabled.is_(True)).order_by(Topic.topic_key))).all()
        context_hash = _relevance_hash(effective, assistant, topics, profile)
        context = await resolve_context(session, assistant_id, effective)
        by_topic = {t.id: t for t in topics}
        scores = (await session.scalars(select(ArticleTopic).where(ArticleTopic.assistant_id == assistant_id, ArticleTopic.article_id.in_([a.id for a in scoped]), ArticleTopic.topic_id.in_(by_topic)))).all()
        grouped: dict[uuid.UUID, list] = {}
        for score in scores:
            grouped.setdefault(score.article_id, []).append(score)
        for article in scoped:
            content_hash = article_digest(article.title, article.normalized_text, article.extraction_status != "complete")
            assessed = []
            for score in grouped.get(article.id, []):
                metadata = assessment_metadata(score.explanation)
                topic = by_topic[score.topic_id]
                assessed.append({**metadata, "score": score.ai_score, "topic_key": topic.topic_key,
                                 "threshold": max(topic.threshold, effective.relevance_threshold),
                                 "valid": score.ai_score is not None and score.context_hash == context_hash and metadata.get("content_hash") == content_hash
                                     and (not context or not context.live or metadata.get("full_content_hash") == full_article_hash(article.title, article.normalized_text, article.extraction_status != "complete"))})
            decisions[article.id] = relevance_decision(assessed, topic_count=len(topics), incomplete=article.extraction_status != "complete" or any(r.get("truncated") for r in assessed))
        await apply_context_decisions(session, list(scoped), decisions, context, effective)
    return decisions


def _general_market_profile(assistant: AssistantWorkspace | None) -> GeneralMarketContext:
    """Return a read-only profile-shaped context for business-free workspaces.

    The analysis contract expects the same fields whether a business profile
    exists or not.  A small in-memory context keeps the pipeline path
    uniform without inserting a fake profile into the database or leaking the
    legacy deployment business into a new assistant.
    """
    name = str(getattr(assistant, "name", "") or "").strip() or "این دستیار"
    return GeneralMarketContext(
        business_name=name,
        description="تمرکز بر پایش عمومی بازار و اخبار موضوعات انتخاب‌شده.",
    )


async def _claim_job(
    idempotency_key: str,
    job_type: str,
    *,
    assistant_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID | None, str]:
    """Claim a job without losing the workspace ownership boundary.

    The first multi-workspace migration left a database default pointing at
    the legacy Dotin workspace. That default is useful for old callers, but a
    scheduled or manual run for a newly-created assistant must pass its own
    workspace explicitly or its operational history is silently attributed to
    Dotin. Keep the legacy fallback only for truly global jobs.
    """
    job_id = uuid.uuid4()
    now = _utcnow()
    statement = (
        postgresql_insert(JobRun)
        .values(
            id=job_id,
            assistant_id=assistant_id or DEFAULT_ASSISTANT_ID,
            job_type=job_type,
            status="running",
            idempotency_key=idempotency_key,
            scheduled_for=now,
            started_at=now,
            attempt=1,
            result={},
        )
        .on_conflict_do_nothing(index_elements=[JobRun.idempotency_key])
        .returning(JobRun.id)
    )
    async with SessionLocal() as session:
        inserted = (await session.execute(statement)).scalar_one_or_none()
        if inserted is not None:
            await session.commit()
            return inserted, "claimed"
        existing = (
            await session.execute(
                select(JobRun).where(JobRun.idempotency_key == idempotency_key)
            )
        ).scalar_one()
        stale_running = (
            existing.status == "running"
            and existing.started_at is not None
            and existing.started_at < now - timedelta(minutes=15)
        )
        if existing.status in {"failed", "cancelled"} or stale_running:
            existing.status = "running"
            existing.started_at = now
            existing.finished_at = None
            existing.attempt += 1
            existing.result = {}
            existing.error_message = None
            await session.commit()
            return existing.id, "reclaimed"
        return None, existing.status


async def _finish_job(
    job_id: uuid.UUID,
    *,
    status: str,
    result: Mapping[str, object],
    error: str | None = None,
) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(JobRun)
            .where(JobRun.id == job_id)
            .values(
                status=status,
                finished_at=_utcnow(),
                result=dict(result),
                error_message=error,
            )
        )
        await session.commit()


async def expire_abandoned_job_runs(*, now: datetime | None = None) -> int:
    """Reconcile orphaned history, never retry work or reset its budget ledger.

    A process can die without reaching _finish_job. Slot-specific keys mean
    those rows are never reclaimed and otherwise remain 'running' forever.
    A conservative 24-hour boundary does not confuse normal model/collection
    latency with an abandoned execution. Delivery claims and publications are
    intentionally untouched: an uncertain external send must not be replayed.
    """
    timestamp = now or _utcnow()
    async with SessionLocal() as session:
        result = await session.execute(
            update(JobRun)
            .where(
                JobRun.status == "running",
                JobRun.finished_at.is_(None),
                func.coalesce(JobRun.started_at, JobRun.created_at) < timestamp - timedelta(days=1),
            )
            .values(status="failed", finished_at=timestamp, error_message="abandoned_execution_expired")
        )
        await session.commit()
    return int(result.rowcount or 0)


async def extract_pending_articles(
    settings: Settings,
    *,
    limit: int,
    assistant_id: uuid.UUID | None = None,
) -> dict[str, object]:
    async with SessionLocal() as session:
        sources = (
            await session.execute(
                select(Source).where(Source.enabled.is_(True)).where(Source.assistant_id == assistant_id if assistant_id is not None else true()).order_by(
                    Source.priority.desc(), Source.source_key
                )
            )
        ).scalars().all()
        per_source = max(1, math.ceil(limit / max(len(sources), 1)))
        rows: list[Any] = []
        selected_ids: set[uuid.UUID] = set()
        for source in sources:
            source_rows = (
                await session.execute(
                    select(SourceItem, Source)
                    .join(Source, Source.id == SourceItem.source_id)
                    .outerjoin(
                        NormalizedArticle,
                        NormalizedArticle.source_item_id == SourceItem.id,
                    )
                    .where(
                        SourceItem.source_id == source.id,
                        SourceItem.assistant_id == assistant_id if assistant_id is not None else true(),
                        _freshness_condition(SourceItem.published_at, settings),
                        NormalizedArticle.id.is_(None),
                        _not_retention_tombstone(),
                    )
                    .order_by(
                        SourceItem.published_at.desc().nullslast(),
                        SourceItem.discovered_at.desc(),
                    )
                    .limit(per_source)
                )
            ).all()
            rows.extend(source_rows)
            selected_ids.update(item.id for item, _ in source_rows)
        if len(rows) < limit:
            fill_statement = (
                select(SourceItem, Source)
                .join(Source, Source.id == SourceItem.source_id)
                .outerjoin(
                    NormalizedArticle,
                    NormalizedArticle.source_item_id == SourceItem.id,
                )
                .where(
                    NormalizedArticle.id.is_(None),
                    SourceItem.assistant_id == assistant_id if assistant_id is not None else true(),
                    _freshness_condition(SourceItem.published_at, settings),
                    _not_retention_tombstone(),
                    Source.enabled.is_(True),
                )
                .order_by(
                    SourceItem.published_at.desc().nullslast(),
                    SourceItem.discovered_at.desc(),
                )
                .limit(limit - len(rows))
            )
            if selected_ids:
                fill_statement = fill_statement.where(
                    SourceItem.id.not_in(selected_ids)
                )
            rows.extend((await session.execute(fill_statement)).all())
        rows = rows[:limit]

    fetcher = ArticleFetcher(settings)

    async def handler(row: Any) -> tuple[SourceItem, ArticleDocument]:
        item, source = row
        try:
            document = await fetcher.fetch(
                url=item.url,
                source_key=source.source_key,
                source_name=source.name,
                fallback_title=item.title,
                fallback_published_at=item.published_at,
                robots_policy=source.robots_policy,
                max_retries=source.max_retries,
            )
        except Exception as exc:
            document = ArticleDocument(
                url=item.url,
                canonical_url=item.url,
                title=item.title,
                author=None,
                published_at=item.published_at,
                language=source.language,
                text=item.excerpt,
                raw_html=None,
                extraction_status="partial" if item.excerpt else "failed",
                extraction_method="feed_fallback",
                quality_score=0.1 if item.excerpt else 0,
                content_hash=(
                    hashlib.sha256(item.excerpt.encode("utf-8")).hexdigest()
                    if item.excerpt
                    else None
                ),
                provenance={"source_key": source.source_key, "fallback": True},
                error=f"{type(exc).__name__}: {exc}"[:2000],
            )
        return item, document

    def on_error(row: Any, exc: Exception) -> tuple[SourceItem, ArticleDocument]:
        item, source = row
        return item, ArticleDocument(
            url=item.url,
            canonical_url=item.url,
            title=item.title,
            author=None,
            published_at=item.published_at,
            language=source.language,
            text=item.excerpt,
            raw_html=None,
            extraction_status="failed",
            extraction_method="isolation_fallback",
            quality_score=0,
            content_hash=None,
            provenance={"source_key": source.source_key, "fallback": True},
            error=f"{type(exc).__name__}: {exc}"[:2000],
        )

    results = await run_sources_independently(
        rows,
        handler,
        concurrency=settings.extraction_concurrency,
        on_error=on_error,
    )
    if results:
        statement = (
            postgresql_insert(NormalizedArticle)
            .values(
                [
                    {
                        "id": uuid.uuid4(),
                        # Preserve the workspace boundary through extraction;
                        # the database default is the legacy workspace and
                        # must never be used for a new assistant's articles.
                        "assistant_id": item.assistant_id,
                        "source_item_id": item.id,
                        "canonical_url": document.canonical_url,
                        "title": document.title,
                        "author": document.author,
                        "language": document.language,
                        "published_at": document.published_at,
                        "raw_html": document.raw_html,
                        "normalized_text": document.text,
                        "content_hash": document.content_hash,
                        "extraction_status": document.extraction_status,
                        "extraction_method": document.extraction_method,
                        "quality_score": document.quality_score,
                        "provenance": document.provenance,
                        "last_error": document.error,
                    }
                    for item, document in results
                ]
            )
            .on_conflict_do_nothing(index_elements=[NormalizedArticle.source_item_id])
        )
        async with SessionLocal() as session:
            await session.execute(statement)
            await session.commit()
    return {
        "attempted": len(results),
        "complete": sum(doc.extraction_status == "complete" for _, doc in results),
        "partial": sum(doc.extraction_status == "partial" for _, doc in results),
        "failed": sum(doc.extraction_status in {"failed", "blocked"} for _, doc in results),
    }


async def _reserve_relevance_budget(settings: Settings, assistant_id: uuid.UUID, input_chars: int, *, job_type: str = "relevance_model", article_id: uuid.UUID | None = None) -> uuid.UUID | None:
    """Reserve before the API call; failed requests also consume the budget."""
    now = _utcnow()
    async with SessionLocal() as session:
        workspace = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        allowed_statuses = {"active", "draft", "testing", "paused"} if job_type == "research_preview_model" else {"active"}
        if workspace is None or workspace.status not in allowed_statuses or workspace.deleted_at is not None:
            return None
        # The workspace row lock serializes reservations. Recovery and the
        # scheduled pipeline must not pay to analyse the same article twice.
        if article_id is not None and await session.scalar(select(JobRun.id).where(
            JobRun.assistant_id == assistant_id, JobRun.job_type == job_type,
            JobRun.status == "running", JobRun.created_at >= now - timedelta(minutes=10),
            JobRun.result["article_id"].as_string() == str(article_id),
        ).limit(1)) is not None:
            return None
        count, chars = (await session.execute(select(func.count(JobRun.id), func.coalesce(func.sum(JobRun.result["input_chars"].as_integer()), 0)).where(
            JobRun.assistant_id == assistant_id,
            JobRun.job_type == "relevance_model" if job_type == "relevance_model" else JobRun.job_type.in_(["analysis_model", "business_model", "research_preview_model"]),
            JobRun.created_at >= _local_day_start_utc(now, settings.timezone),
        ))).one()
        cap = settings.relevance_daily_request_cap if job_type == "relevance_model" else settings.model_daily_request_cap
        if int(count) >= cap or int(chars) + input_chars > settings.model_daily_input_char_cap:
            return None
        job_id = uuid.uuid4()
        budget_result: dict[str, object] = {"input_chars": input_chars, "model": settings.analysis_model}
        if article_id is not None:
            budget_result["article_id"] = str(article_id)
        session.add(JobRun(id=job_id, assistant_id=assistant_id, job_type=job_type, status="running", idempotency_key=job_type + ":" + str(job_id), scheduled_for=now, started_at=now, attempt=1, result=budget_result))
        await session.commit()
        return job_id


async def score_pending_articles(
    settings: Settings,
    *,
    limit: int,
    rescore: bool = False,
    assistant_id: uuid.UUID | None = None,
) -> dict[str, object]:
    if assistant_id is None:
        # Never compare one project's articles with another project's topics.
        async with SessionLocal() as session:
            ids = (await session.scalars(select(AssistantWorkspace.id).where(AssistantWorkspace.status == "active", AssistantWorkspace.deleted_at.is_(None)))).all()
        results = [await score_pending_articles(await settings_for_assistant(settings, aid), limit=limit, rescore=rescore, assistant_id=aid) for aid in ids]
        return {"articles": sum(_payload_int(r.get("articles", 0)) for r in results), "scores": sum(_payload_int(r.get("scores", 0)) for r in results), "workspaces": results}
    settings = await settings_for_assistant(settings, assistant_id)
    async with SessionLocal() as session:
        topics = (
            await session.execute(
                select(Topic).where(Topic.enabled.is_(True)).where(Topic.assistant_id == assistant_id if assistant_id is not None else true()).order_by(Topic.topic_key)
            )
        ).scalars().all()
        assistant = await session.get(AssistantWorkspace, assistant_id)
        profile = await _profile_for_assistant(session, assistant_id)
        context = await resolve_context(session, assistant_id, settings)
        business = _profile_payload(profile) if profile is not None else {}
        topic_context = [{"topic_key": t.topic_key, "name": t.name, "definition": t.definition, "positive_terms": list(t.positive_terms), "negative_terms": list(t.negative_terms)} for t in topics]
        mission = str(getattr(assistant, "description", "") or "")
        context_hash = _relevance_hash(settings, assistant, topics, profile)
        article_statement = (
            select(NormalizedArticle)
            .where(
                NormalizedArticle.extraction_status.in_(["complete", "partial"]),
                NormalizedArticle.assistant_id == assistant_id if assistant_id is not None else true(),
                _freshness_condition(NormalizedArticle.published_at, settings),
            )
            .order_by(NormalizedArticle.extracted_at.desc())
            .limit(limit)
        )
        if not rescore:
            article_statement = article_statement.where(select(func.count(ArticleTopic.id)).where(
                ArticleTopic.article_id == NormalizedArticle.id,
                ArticleTopic.ai_score.is_not(None), ArticleTopic.context_hash == context_hash,
                ArticleTopic.topic_id.in_([t.id for t in topics]),
                ArticleTopic.scored_at >= NormalizedArticle.extracted_at,
            ).correlate(NormalizedArticle).scalar_subquery() < len(topics))
        articles = (await session.execute(article_statement)).scalars().all()
    if not topics or not articles:
        business_result = await score_business_articles(settings, assistant_id=assistant_id, limit=limit)
        return {"articles": len(articles), "scores": 0, "semantic": "not_needed", "business": business_result}

    ai_scores: dict[tuple[str, str], tuple[float, str]] = {}
    semantic_status = "disabled"
    client = OpenAIClient(settings)
    health = client.provider_health()
    if health["state"] == "cooldown":
        semantic_status = "provider_failed:" + str(health["code"])
    elif client.configured:
        requests = 0
        # Bound output size as well as input size: 20 topics must not cause
        # 160 score objects to be truncated in one model response.
        batch_size = min(settings.relevance_batch_size, max(1, 24 // len(topics)))
        for offset in range(0, len(articles), batch_size):
            if requests >= settings.relevance_max_requests_per_run:
                semantic_status = "budget_deferred"
                break
            batch = articles[offset:offset + batch_size]
            inputs: list[dict[str, Any]] = [{"id": str(a.id), "title": a.title, "text": a.normalized_text if context and context.live else a.normalized_text[:6000], "incomplete": a.extraction_status != "complete"} for a in batch]
            input_chars = sum(len(a["text"]) + len(a["title"]) for a in inputs) + len(str(topic_context)) + len(str(business)) + len(mission)
            job_id = await _reserve_relevance_budget(settings, assistant_id, input_chars)
            if job_id is None:
                semantic_status = "budget_deferred"
                break
            requests += 1
            try:
                ai_scores.update(await classify_articles(client, articles=inputs, topics=topic_context, business=business, mission=mission,
                    **({"max_input_chars": 20000} if context and context.live else {})))
                await _finish_job(job_id, status="succeeded", result={"input_chars": input_chars, "articles": len(batch), "model": settings.analysis_model})
                semantic_status = "succeeded"
            except Exception as exc:
                # No model evidence -> review-only lexical data, retried next run.
                provider_code = str(getattr(exc, "code", type(exc).__name__))
                semantic_status = "provider_failed:" + provider_code
                await _finish_job(job_id, status="failed", result={"input_chars": input_chars, "model": settings.analysis_model, "scorer_revision": SCORER_REVISION}, error=provider_code)
                break

    rows: list[dict[str, object]] = []
    selected_articles: set[uuid.UUID] = set()
    for article in articles:
        for topic in topics:
            if topic.assistant_id != article.assistant_id:
                continue
            lexical, positive, negative = lexical_topic_score(
                title=article.title,
                text=article.normalized_text,
                positive_terms=list(topic.positive_terms),
                negative_terms=list(topic.negative_terms),
            )
            score = combine_topic_score(
                lexical=lexical,
                semantic=None,
                threshold=max(topic.threshold, settings.relevance_threshold),
                positive_matches=positive,
                negative_matches=negative,
            )
            model_score = ai_scores.get((str(article.id), topic.topic_key))
            combined = model_score[0] if model_score is not None else score.combined_score
            metadata = assessment_metadata(model_score[1]) if model_score else {}
            decision = relevance_decision([{**metadata, "valid": bool(metadata), "score": combined,
                                           "threshold": max(topic.threshold, settings.relevance_threshold)}], topic_count=1,
                                          incomplete=article.extraction_status != "complete")
            selected = decision["publishable"]
            selected_articles.update([article.id] if selected else [])
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "assistant_id": article.assistant_id,
                    "article_id": article.id,
                    "topic_id": topic.id,
                    "lexical_score": score.lexical_score,
                    "ai_score": model_score[0] if model_score is not None else None,
                    "context_hash": context_hash if model_score is not None else None,
                    "semantic_score": score.semantic_score,
                    "combined_score": combined,
                    "matched_positive": list(score.positive_matches),
                    "matched_negative": list(score.negative_matches),
                    "explanation": model_score[1] if model_score else score.explanation + "; ai_pending=" + semantic_status,
                    "selected": selected,
                }
            )
    async with SessionLocal() as session:
        # PostgreSQL/asyncpg has a 32767-parameter ceiling. A normal 1000
        # article / 20 topic run must not fail after paying for AI calls.
        for offset in range(0, len(rows), 500):
            insert_statement = postgresql_insert(ArticleTopic).values(rows[offset:offset + 500])
            excluded = insert_statement.excluded
            insert_statement = insert_statement.on_conflict_do_update(
                index_elements=[ArticleTopic.article_id, ArticleTopic.topic_id],
                set_={
                    "lexical_score": excluded.lexical_score,
                    "ai_score": excluded.ai_score,
                    "context_hash": excluded.context_hash,
                    "semantic_score": excluded.semantic_score,
                    "combined_score": excluded.combined_score,
                    "matched_positive": excluded.matched_positive,
                    "matched_negative": excluded.matched_negative,
                    "explanation": excluded.explanation,
                    "selected": excluded.selected,
                    "scored_at": _utcnow(),
                },
                where=or_(excluded.ai_score.is_not(None), ArticleTopic.ai_score.is_(None)),
            )
            # A temporary provider/quota failure must not erase valid model
            # evidence. Changed contexts are still invalidated on every read.
            await session.execute(insert_statement)
        invalidated = 0
        if rescore and semantic_status == "succeeded":
            valid_articles = select(ArticleTopic.article_id).where(
                ArticleTopic.selected.is_(True), ArticleTopic.assistant_id == assistant_id,
                ArticleTopic.context_hash == context_hash,
            )
            invalid_analysis_ids = select(ArticleAnalysis.id).where(
                ArticleAnalysis.article_id.not_in(valid_articles), ArticleAnalysis.assistant_id == assistant_id,
            )
            invalidation = await session.execute(
                update(Publication)
                .where(
                    Publication.analysis_id.in_(invalid_analysis_ids),
                    Publication.status == "preview",
                    Publication.assistant_id == assistant_id,
                )
                .values(audit=Publication.audit.op("||")({"review_only": True}), updated_at=_utcnow())
            )
            invalidated = int(invalidation.rowcount or 0)
        await session.commit()
    business_result = await score_business_articles(settings, assistant_id=assistant_id, limit=limit)
    return {
        "articles": len(articles),
        "scores": len(rows),
        "selected_articles": len(selected_articles),
        "semantic": semantic_status,
        "rescore": rescore,
        "previews_invalidated": invalidated,
        "business": business_result,
    }


async def score_business_articles(settings: Settings, *, assistant_id: uuid.UUID, limit: int, shadow: bool = False) -> dict:
    result = await _score_business_context(settings, assistant_id=assistant_id, limit=limit, shadow=shadow)
    if not shadow and settings.model_max_requests_per_run >= 2:
        async with SessionLocal() as session:
            proposed = await resolve_context(session, assistant_id, settings, shadow=True)
        if proposed and proposed.record.rollout == "shadow" and proposed.record.previous_live:
            result["shadow"] = await _score_business_context(settings, assistant_id=assistant_id, limit=limit, shadow=True)
    return result


async def _score_business_context(settings: Settings, *, assistant_id: uuid.UUID, limit: int, shadow: bool = False) -> dict:
    """Independent bounded assessment; never substitutes B for the topic score."""
    async with SessionLocal() as session:
        context = await resolve_context(session, assistant_id, settings, shadow=shadow)
        proposed = await resolve_context(session, assistant_id, settings, shadow=True)
        has_shadow = bool(proposed and proposed.record.rollout == "shadow" and proposed.record.previous_live)
        if shadow and not has_shadow:
            return {"state": "not_enabled", "assessed": 0}
        if not context or context.record.mode == "topics":
            return {"state": "not_enabled", "assessed": 0}
        if context.state != "ready":
            return {"state": context.state, "assessed": 0}
        expected = business_context_hash(context.record.brief, settings.analysis_model)
        generation = context.record.generation
        brief = context.record.brief
        articles = list((await session.scalars(select(NormalizedArticle).join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
            .join(Source, Source.id == SourceItem.source_id).where(Source.enabled.is_(True), Source.assistant_id == assistant_id,
            NormalizedArticle.assistant_id == assistant_id, NormalizedArticle.extraction_status.in_(["complete", "partial"]),
            _freshness_condition(NormalizedArticle.published_at, settings)).order_by(NormalizedArticle.extracted_at.desc())
            .limit(max(1, min(limit, settings.pipeline_max_candidates_per_run))))).all())
        decisions = await _article_decisions(session, articles, settings)
        stored = (await session.scalars(select(NewsBusinessAssessment).where(NewsBusinessAssessment.assistant_id == assistant_id,
            NewsBusinessAssessment.context_hash == expected, NewsBusinessAssessment.article_id.in_([a.id for a in articles])))).all()
        current = {(r.article_id, r.content_hash) for r in stored}
        articles = [a for a in articles if decisions[a.id].get("topic_relevance_state", decisions[a.id]["relevance_state"]) in {"selected", "borderline"}
            and (a.id, full_article_hash(a.title, a.normalized_text, a.extraction_status != "complete")) not in current][:settings.max_items_per_run]
    client = OpenAIClient(settings)
    if not client.configured or client.provider_health()["state"] == "cooldown":
        return {"state": "provider_unavailable", "assessed": 0}
    assessed, calls = 0, 0
    for offset in range(0, len(articles), 5):
        if calls >= max(1, settings.model_max_requests_per_run // (2 if has_shadow else 1)):
            return {"state": "budget_deferred", "assessed": assessed}
        batch = articles[offset:offset + 5]
        inputs: list[dict[str, Any]] = [{"id": str(a.id), "title": a.title, "text": a.normalized_text, "incomplete": a.extraction_status != "complete"} for a in batch]
        chars = sum(min(len(a["text"]), 20000) + len(a["title"]) for a in inputs) + brief["input_chars"]
        job = await _reserve_relevance_budget(settings, assistant_id, chars, job_type="business_model")
        if not job:
            return {"state": "budget_deferred", "assessed": assessed}
        calls += 1
        try:
            results = await assess_business(client, articles=inputs, brief=brief, language=context.record.style.get("output_language", "fa"))
            async with SessionLocal() as session:
                live = await resolve_context(session, assistant_id, settings, shadow=shadow)
                if not live or live.record.generation != generation or live.state != "ready":
                    await _finish_job(job, status="cancelled", result={"input_chars": chars}, error="context_changed")
                    return {"state": "context_changed", "assessed": assessed}
                for article in batch:
                    result = results[str(article.id)]
                    statement = postgresql_insert(NewsBusinessAssessment).values(id=uuid.uuid4(), assistant_id=assistant_id,
                        article_id=article.id, context_hash=expected, content_hash=result["content_hash"], payload=result)
                    await session.execute(statement.on_conflict_do_nothing(index_elements=[NewsBusinessAssessment.assistant_id,
                        NewsBusinessAssessment.article_id, NewsBusinessAssessment.context_hash, NewsBusinessAssessment.content_hash]))
                await session.commit()
            await _finish_job(job, status="succeeded", result={"input_chars": chars, "articles": len(batch), "model": settings.analysis_model})
            assessed += len(batch)
        except Exception as exc:
            await _finish_job(job, status="failed", result={"input_chars": chars}, error=type(exc).__name__)
            return {"state": "provider_failed", "assessed": assessed}
    return {"state": "succeeded", "assessed": assessed, "calls": calls}


async def rescore_existing_articles(*, limit: int = 1000) -> dict[str, object]:
    return await score_pending_articles(get_settings(), limit=limit, rescore=True)


async def cluster_pending_articles(settings: Settings, *, limit: int, assistant_id: uuid.UUID | None = None) -> dict[str, int]:
    async with SessionLocal() as session:
        articles = (
            await session.execute(
                select(NormalizedArticle)
                .join(ArticleTopic, ArticleTopic.article_id == NormalizedArticle.id)
                .join(Topic, Topic.id == ArticleTopic.topic_id)
                .outerjoin(ClusterMember, ClusterMember.article_id == NormalizedArticle.id)
                .where(ArticleTopic.ai_score.is_not(None), Topic.enabled.is_(True), ArticleTopic.ai_score >= Topic.threshold,
                       ClusterMember.id.is_(None), NormalizedArticle.assistant_id == assistant_id if assistant_id is not None else true(), _freshness_condition(NormalizedArticle.published_at, settings))
                .group_by(NormalizedArticle.id)
                .order_by(NormalizedArticle.extracted_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        decisions = await _article_decisions(session, articles, settings)
        articles = [a for a in articles if decisions[a.id]["publishable"]]
        existing_rows = (
            await session.execute(
                select(EventCluster, NormalizedArticle)
                .join(
                    NormalizedArticle,
                    NormalizedArticle.id == EventCluster.representative_article_id,
                )
                .where(EventCluster.updated_at >= _utcnow() - timedelta(days=14), EventCluster.assistant_id == assistant_id if assistant_id is not None else true())
            )
        ).all()
        existing: list[tuple[EventCluster, NormalizedArticle]] = [
            (cluster, representative) for cluster, representative in existing_rows
        ]

        new_clusters = 0
        joined_clusters = 0
        for article in articles:
            best_cluster: EventCluster | None = None
            best_similarity = 0.0
            for candidate, representative in existing:
                if candidate.assistant_id != article.assistant_id:
                    continue
                similarity = jaccard_similarity(article.title, representative.title)
                if similarity > best_similarity:
                    best_cluster = candidate
                    best_similarity = similarity
            if best_cluster is None or best_similarity < settings.clustering_threshold:
                best_cluster = EventCluster(
                    assistant_id=article.assistant_id,
                    cluster_key=hashlib.sha256(f"{article.assistant_id}:{cluster_key(article.title)}".encode()).hexdigest(),
                    representative_article_id=article.id,
                    headline=article.title,
                    source_count=1,
                    updated_at=_utcnow(),
                )
                session.add(best_cluster)
                await session.flush()
                existing.append((best_cluster, article))
                best_similarity = 1.0
                new_clusters += 1
            else:
                best_cluster.updated_at = _utcnow()
                joined_clusters += 1
            session.add(
                ClusterMember(
                    assistant_id=article.assistant_id,
                    cluster_id=best_cluster.id,
                    article_id=article.id,
                    similarity=best_similarity,
                )
            )
        await session.commit()

        affected_ids = {cluster.id for cluster, _ in existing}
        for cluster_id in affected_ids:
            count = (
                await session.execute(
                    select(func.count(distinct(SourceItem.source_id)))
                    .select_from(ClusterMember)
                    .join(
                        NormalizedArticle,
                        NormalizedArticle.id == ClusterMember.article_id,
                    )
                    .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
                    .where(ClusterMember.cluster_id == cluster_id)
                )
            ).scalar_one()
            await session.execute(
                update(EventCluster)
                .where(EventCluster.id == cluster_id)
                .values(source_count=count)
            )
        await session.commit()
    return {
        "articles": len(articles),
        "new_clusters": new_clusters,
        "joined_existing": joined_clusters,
    }


def _profile_payload(profile: BusinessContext, *, for_report: bool = False) -> dict[str, object]:
    if isinstance(profile, CompiledBusinessProfile):
        return profile.report_payload(disclose_facts=profile.research_brief.get("public_business_facts") is True) if for_report else profile.semantic_payload()
    return {
        "business_name": profile.business_name,
        "description": profile.description,
        "products_services": profile.products_services,
        "target_customers": profile.target_customers,
        "markets": profile.markets,
        "revenue_model": profile.revenue_model,
        "strategic_goals": profile.strategic_goals,
        "competitors": profile.competitors,
        "sensitivities": profile.sensitivities,
        "output_language": profile.output_language,
        "output_tone": profile.output_tone,
    }


def _source_output_language(source: Source, profile: BusinessContext) -> str:
    """Resolve the publication language for one source.

    ``source`` means follow the configured business/profile language. A
    concrete per-source override is intentionally resolved here, at analysis
    time, so changing one media source never changes another source or the
    business profile itself.
    """
    selected = str(getattr(source, "output_language", "source") or "source").strip().casefold()
    if selected == "source":
        selected = str(getattr(profile, "output_language", "fa") or "fa").strip().casefold()
    return selected if selected in {"fa", "en", "tr", "ar", "it", "es", "de", "fr"} else "fa"


def _template_guidance(message_templates: dict | None) -> str:
    """Expose owner-authored per-block writing guidance to the model safely."""
    if not isinstance(message_templates, dict):
        return ""
    lines: list[str] = []
    for channel in ("feedback", "observer"):
        item = message_templates.get(channel)
        blocks = item.get("blocks") if isinstance(item, dict) else None
        if not isinstance(blocks, list):
            continue
        for block in blocks[:12]:
            if not isinstance(block, dict) or not block.get("visible", True):
                continue
            guidance = str(block.get("guidance") or "").strip()
            if guidance:
                lines.append(f"{block.get('type', 'section')}: {guidance[:400]}")
    return "\n".join(dict.fromkeys(lines))[:3000]


def _fallback_analysis(
    article: NormalizedArticle,
    *,
    profile: BusinessContext,
    topic_rows: Sequence[Row[tuple[Topic, ArticleTopic]]],
    source: Source,
    reason: str,
) -> dict[str, Any]:
    safe_title, safe_text, source_safety = sanitize_untrusted_source(
        title=article.title,
        text=article.normalized_text,
    )
    title_prefixes = sorted(
        {
            prefix.strip()
            for prefix in [safe_title, *re.split(r"[؟?!|:+–—-]+", safe_title)]
            if len(prefix.strip()) > 5
        },
        key=len,
        reverse=True,
    )
    sentences: list[str] = []
    for part in SENTENCE_BREAK.split(safe_text):
        raw_candidate = part.strip()
        has_leading_separator = raw_candidate.startswith(("+", ":", "-", "–", "—", "|"))
        candidate = raw_candidate.lstrip("+:-–—| ")
        if candidate.count("»") >= 2:
            continue
        while candidate.startswith(safe_title):
            candidate = candidate[len(safe_title) :].strip(" +:-–—|")
        if has_leading_separator:
            for prefix in title_prefixes:
                if candidate.startswith(prefix):
                    candidate = candidate[len(prefix) :].strip(" +:-–—|")
                    break
        if len(candidate) > 30:
            sentences.append(candidate)
    summary = " ".join(sentences[:3])[:1200] or safe_title or article.title
    topic_names = "، ".join(topic.name for topic, score in topic_rows if score.selected)
    connection = f"این خبر برای بررسی موضوعات {topic_names or 'این دستیار'} انتخاب شده است؛ تحلیل تکمیلی هنوز آماده نیست."
    return {
        "status": "fallback",
        "headline": safe_title or article.title,
        "news_summary": summary,
        "business_connection": connection,
        "opportunity": "برای فرصت مشخص، شواهد بیشتری از متن یا بازار لازم است.",
        "risk": "ریسک مشخصی فراتر از محتوای منبع استنباط نشد.",
        "suggested_action": "خبر و منبع اصلی توسط تیم مرتبط مرور شود.",
        "time_horizon": "نامشخص",
        "confidence": min(0.55, max(article.quality_score, 0.25)),
        "facts": [summary],
        "inferences": [
            connection,
            *(["یادداشت ایمنی منبع: الگوهای دستوری مشکوک از متن منبع حذف و برای تحلیل نادیده گرفته شد."] if source_safety.detected else []),
        ],
        "citations": [
            {
                "source": source.name,
                "url": article.canonical_url,
                "output_language": _source_output_language(source, profile),
                "translation_pending": not prose_matches_language(summary, _source_output_language(source, profile)),
                "published_at": article.published_at.isoformat() if article.published_at else None,
            }
        ],
        "topic_scores": {
            topic.topic_key: score.combined_score for topic, score in topic_rows
        },
        "model": "deterministic-fallback",
        "input_tokens": 0,
        "output_tokens": 0,
        "estimated_cost_usd": 0.0,
        "error_message": reason[:2000],
    }


async def regenerate_fallback_analyses(*, limit: int = 200, assistant_id: uuid.UUID | None = None) -> dict[str, int]:
    """Repair incomplete fallback previews, never completed translations or sends."""
    base_settings = get_settings()
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(ArticleAnalysis, NormalizedArticle, SourceItem, Source, Publication)
                .join(NormalizedArticle, NormalizedArticle.id == ArticleAnalysis.article_id)
                .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
                .join(Source, Source.id == SourceItem.source_id)
                .outerjoin(Publication, Publication.analysis_id == ArticleAnalysis.id)
                .where(ArticleAnalysis.status == "fallback",
                       ArticleAnalysis.assistant_id == NormalizedArticle.assistant_id,
                       Source.assistant_id == NormalizedArticle.assistant_id,
                       or_(Publication.id.is_(None), Publication.status == "preview"),
                       ArticleAnalysis.assistant_id == assistant_id if assistant_id is not None else true())
                .order_by(ArticleAnalysis.created_at.desc())
                .limit(limit)
            )
        ).all()
        updated = 0
        preview_updated = 0
        preserved = 0
        contexts: dict[uuid.UUID, tuple[Settings, BusinessContext]] = {}
        for analysis, article, item, source, publication in rows:
            aid = article.assistant_id
            if aid not in contexts:
                effective = await settings_for_assistant(base_settings, aid)
                assistant = await session.get(AssistantWorkspace, aid)
                profile_row = await _profile_for_assistant(session, aid)
                contexts[aid] = (effective, profile_row or _general_market_profile(assistant))
            effective, profile = contexts[aid]
            if not language_issues(analysis_text(analysis), _source_output_language(source, profile)):
                preserved += 1
                continue
            topic_rows = (
                await session.execute(
                    select(Topic, ArticleTopic)
                    .join(ArticleTopic, ArticleTopic.topic_id == Topic.id)
                    .where(ArticleTopic.article_id == article.id, Topic.assistant_id == aid, Topic.enabled.is_(True))
                    .order_by(ArticleTopic.combined_score.desc())
                )
            ).all()
            payload = _fallback_analysis(
                article,
                profile=profile,
                topic_rows=topic_rows,
                source=source,
                reason="model unavailable or configured request/input budget reached",
            )
            analysis.headline = str(payload["headline"])
            analysis.news_summary = str(payload["news_summary"])
            analysis.business_connection = str(payload["business_connection"])
            analysis.opportunity = str(payload["opportunity"])
            analysis.risk = str(payload["risk"])
            analysis.suggested_action = str(payload["suggested_action"])
            analysis.time_horizon = str(payload["time_horizon"])
            analysis.confidence = _payload_float(payload["confidence"])
            analysis.facts = payload["facts"]
            analysis.inferences = payload["inferences"]
            analysis.citations = payload["citations"]
            analysis.topic_scores = payload["topic_scores"]
            analysis.error_message = str(payload["error_message"])
            updated += 1
            if publication is not None and publication.status == "preview":
                blocks = (effective.message_templates.get("feedback") or {}).get("blocks") if isinstance(effective.message_templates, dict) else None
                publication.message_text = _render_publication_message(
                    analysis=analysis,
                    article=article,
                    source=source,
                    business_name=profile.business_name,
                    template_blocks=blocks if isinstance(blocks, list) else None,
                    output_language=_source_output_language(source, profile),
                )
                publication.audit = {**(publication.audit or {}), "translation_pending": True}
                publication.updated_at = _utcnow()
                preview_updated += 1
        await session.commit()
    return {"analyses_updated": updated, "previews_updated": preview_updated, "translations_preserved": preserved}


async def _model_budget(settings: Settings, *, assistant_id: uuid.UUID | None = None) -> tuple[int, int]:
    day_start = _local_day_start_utc(_utcnow(), settings.timezone)
    async with SessionLocal() as session:
        attempts, attempt_chars = (await session.execute(select(func.count(JobRun.id), func.coalesce(func.sum(JobRun.result["input_chars"].as_integer()), 0)).where(
            JobRun.job_type.in_(["analysis_model", "business_model", "research_preview_model"]), JobRun.created_at >= day_start,
            JobRun.assistant_id == assistant_id if assistant_id is not None else true(),
        ))).one()
        count, chars = (
            await session.execute(
                select(
                    func.count(ArticleAnalysis.id),
                    func.coalesce(func.sum(ArticleAnalysis.input_chars), 0),
                ).where(
                    ArticleAnalysis.created_at >= day_start,
                    ArticleAnalysis.status == "succeeded",
                    ArticleAnalysis.assistant_id == assistant_id if assistant_id is not None else true(),
                    ~exists(select(JobRun.id).where(JobRun.job_type == "analysis_model", JobRun.result["article_id"].as_string() == cast(ArticleAnalysis.article_id, String))),
                )
            )
        ).one()
    return int(count) + int(attempts), int(chars) + int(attempt_chars)


def _local_day_start_utc(now: datetime, timezone_name: str | None) -> datetime:
    """Return the UTC instant of the current calendar day in a workspace TZ."""
    zone: tzinfo = timezone.utc
    try:
        zone = ZoneInfo(timezone_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        pass
    local_now = now.astimezone(zone)
    return local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


async def _daily_processing_count(assistant_id: uuid.UUID, timezone_name: str | None = None) -> int:
    """Count newly extracted articles since the project's local day start."""
    day_start = _local_day_start_utc(_utcnow(), timezone_name)
    async with SessionLocal() as session:
        count = await session.scalar(
            select(func.count(NormalizedArticle.id)).where(
                NormalizedArticle.assistant_id == assistant_id,
                NormalizedArticle.extracted_at >= day_start,
            )
        )
    return int(count or 0)


def _structured_analysis_payload(
    result: StructuredAnalysis,
    *,
    article: NormalizedArticle,
    source: Source,
) -> dict[str, Any]:
    model_payload = result.payload
    inferences = list(model_payload["inferences"])
    source_safety = model_payload.get("_source_content_safety")
    if isinstance(source_safety, dict) and source_safety.get("detected"):
        metadata = model_payload.get("_report_language") or {}
        inferences.append(report_copy(str(metadata.get("output_language") or "fa"))["safety_note"])
    return {
        "status": "succeeded",
        **{
            key: model_payload[key]
            for key in (
                "headline",
                "news_summary",
                "business_connection",
                "opportunity",
                "risk",
                "suggested_action",
                "time_horizon",
                "confidence",
                "facts",
                "inferences",
            )
        },
        "inferences": inferences,
        "citations": [
            {
                "source": source.name,
                "url": article.canonical_url,
                **(model_payload.get("_report_language") or {}),
                "published_at": (
                    article.published_at.isoformat() if article.published_at else None
                ),
            }
        ],
        "topic_scores": {
            row["topic_key"]: row["score"] for row in model_payload["topic_scores"]
        },
        "model": result.model,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "estimated_cost_usd": result.estimated_cost_usd,
        "error_message": None,
    }


async def analyze_pending_articles(settings: Settings, *, limit: int, assistant_id: uuid.UUID | None = None, fallback_only: bool = False) -> dict[str, object]:
    if assistant_id is None:
        async with SessionLocal() as session:
            ids = (await session.scalars(select(AssistantWorkspace.id).where(AssistantWorkspace.status == "active", AssistantWorkspace.deleted_at.is_(None)))).all()
        results = [await analyze_pending_articles(settings, limit=limit, assistant_id=aid, fallback_only=fallback_only) for aid in ids]
        return {"succeeded": sum(_payload_int(r.get("succeeded")) for r in results), "workspaces": results}
    settings = await settings_for_assistant(settings, assistant_id)
    daily_count, daily_chars = await _model_budget(settings, assistant_id=assistant_id)
    available_requests = max(0, settings.model_daily_request_cap - daily_count)
    request_limit = min(limit, settings.model_max_requests_per_run, available_requests)
    async with SessionLocal() as session:
        assistant = await session.get(AssistantWorkspace, assistant_id)
        profile_row = await _profile_for_assistant(session, assistant_id)
        topics = (await session.scalars(select(Topic).where(Topic.enabled.is_(True), Topic.assistant_id == assistant_id).order_by(Topic.topic_key))).all()
        current_hash = _relevance_hash(settings, assistant, topics, profile_row)
        research_context = await resolve_context(session, assistant_id, settings)
        managed_live = bool(research_context and research_context.live)
        # Analyse both publishable scores and the narrow manual-review band.
        # The latter deliberately does not require an EventCluster: clustering
        # remains reserved for items that already passed the real threshold.
        reviewable_topic = exists(
            select(ArticleTopic.id)
            .join(Topic, Topic.id == ArticleTopic.topic_id)
            .where(
                ArticleTopic.article_id == NormalizedArticle.id,
                Topic.enabled.is_(True), Topic.assistant_id == assistant_id,
                ArticleTopic.ai_score.is_not(None),
                ArticleTopic.context_hash == current_hash,
                ArticleTopic.ai_score >= func.greatest(Topic.threshold, settings.relevance_threshold) - REVIEW_MARGIN,
            )
        )
        rows = (
            await session.execute(
                select(NormalizedArticle, SourceItem, Source, ArticleAnalysis)
                .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
                .join(Source, Source.id == SourceItem.source_id)
                .outerjoin(
                    ArticleAnalysis,
                    ArticleAnalysis.article_id == NormalizedArticle.id,
                )
                .where(
                    (and_(ArticleAnalysis.status == "fallback", exists(select(Publication.id).where(Publication.analysis_id == ArticleAnalysis.id, Publication.assistant_id == assistant_id, Publication.status == "preview")))
                     if fallback_only else or_(ArticleAnalysis.id.is_(None), ArticleAnalysis.status.in_(["fallback", "failed"]),
                         or_(ArticleAnalysis.research_provenance["generation"].as_string().is_distinct_from(str(research_context.record.generation)),
                             ArticleAnalysis.research_provenance["model"].as_string().is_distinct_from(settings.analysis_model),
                             ArticleAnalysis.research_provenance["article_db_hash"].as_string().is_distinct_from(NormalizedArticle.content_hash)) if managed_live and research_context else false_condition())),
                    NormalizedArticle.assistant_id == assistant_id if assistant_id is not None else true(),
                    Source.assistant_id == assistant_id,
                    Source.enabled.is_(True),
                    ~exists(select(Publication.id).where(Publication.analysis_id == ArticleAnalysis.id, Publication.status != "preview")),
                    reviewable_topic,
                )
                .where(_freshness_condition(NormalizedArticle.published_at, settings))
                .order_by(NormalizedArticle.extracted_at.desc())
                .limit(max(limit, settings.max_items_per_run))
            )
        ).all()
        decisions = await _article_decisions(session, [r[0] for r in rows], settings)
        rows = [r for r in rows if decisions[r[0].id]["relevance_state"] in {"selected", "borderline"}]
        if managed_live and research_context and research_context.state != "ready":
            rows = []
        # A missing business profile is valid for general market monitoring.
        # Keep the profile-shaped analysis payload stable with an in-memory
        # context rather than aborting the whole run.
        profile: BusinessContext
        if profile_row is None:
            profile = _general_market_profile(assistant)
            if managed_live and research_context:
                profile.output_language = research_context.record.style.get("output_language", "fa")
                profile.output_tone = research_context.record.style.get("output_tone", "")
        else:
            profile = profile_row
        assistant_config = dict(assistant.config or {}) if assistant is not None else {}
        knowledge_library = assistant_config.get("business_knowledge") if isinstance(assistant_config.get("business_knowledge"), dict) else {}
        if managed_live:
            knowledge_library = {}

    client = OpenAIClient(settings)
    model_calls = 0
    fallback_calls = 0
    created = 0
    succeeded = 0
    provider_blocked = client.provider_health()["state"] == "cooldown"
    for article, item, source, existing_report in rows[:limit]:
        async with SessionLocal() as session:
            topic_rows = (
                await session.execute(
                    select(Topic, ArticleTopic)
                    .join(ArticleTopic, ArticleTopic.topic_id == Topic.id)
                    .where(ArticleTopic.article_id == article.id, ArticleTopic.context_hash == current_hash, Topic.enabled.is_(True), Topic.assistant_id == assistant_id)
                    .order_by(ArticleTopic.combined_score.desc())
                )
            ).all()
        payload: dict[str, object]
        can_call_model = (
            client.configured
            and not provider_blocked
            and model_calls < request_limit
            and daily_chars + len(article.normalized_text) <= settings.model_daily_input_char_cap
        )
        attempt_id = None
        input_chars = min(len(article.normalized_text), settings.analysis_max_input_chars)
        if can_call_model:
            attempt_id = await _reserve_relevance_budget(settings, assistant_id, input_chars, job_type="analysis_model", article_id=article.id)
            can_call_model = attempt_id is not None
        if can_call_model:
            # Count attempts, including provider failures, before making a
            # request. Otherwise a provider outage could trigger 1000 calls.
            model_calls += 1
            daily_chars += input_chars
            try:
                result = await client.analyze(
                    article_title=article.title,
                    article_text=article.normalized_text,
                    source_name=source.name,
                    source_url=article.canonical_url,
                    published_at=(article.published_at.isoformat() if article.published_at else None),
                    business_profile={**_profile_payload(profile, for_report=True), "knowledge_library": knowledge_library,
                        "business_relationship": {k: (decisions[article.id].get("business_assessment") or {}).get(k) for k in ("score", "confidence", "relation", "impact", "urgency")},
                        "message_template_guidance": _template_guidance(settings.message_templates)},
                    topics=[
                        {
                            "topic_key": topic.topic_key,
                            "name": topic.name,
                            "definition": topic.definition,
                            "current_score": score.ai_score,
                            "evidence": assessment_metadata(score.explanation).get("evidence", []),
                        }
                        for topic, score in topic_rows
                    ],
                    incomplete_text=article.extraction_status == "partial",
                    output_language=_source_output_language(source, profile),
                )
                payload = _structured_analysis_payload(
                    result,
                    article=article,
                    source=source,
                )
                if attempt_id is not None:
                    await _finish_job(attempt_id, status="succeeded", result={"input_chars": input_chars, "article_id": str(article.id), "model": settings.analysis_model})
            except Exception as exc:
                provider_code = str(getattr(exc, "code", type(exc).__name__))
                provider_blocked = provider_code in {"provider_quota_exhausted", "provider_authentication_failed", "provider_model_unavailable"}
                if attempt_id is not None:
                    await _finish_job(attempt_id, status="failed", result={"input_chars": input_chars, "article_id": str(article.id), "model": settings.analysis_model}, error=provider_code)
                payload = _fallback_analysis(
                    article,
                    profile=profile,
                    topic_rows=topic_rows,
                    source=source,
                    reason=f"model fallback: {provider_code}",
                )
                fallback_calls += 1
        else:
            payload = _fallback_analysis(
                article,
                profile=profile,
                topic_rows=topic_rows,
                source=source,
                reason="model unavailable or configured request/input budget reached",
            )
            fallback_calls += 1
        if payload["status"] == "fallback" and existing_report is not None and not language_issues(analysis_text(existing_report), _source_output_language(source, profile)):
            # Budget outages must not destroy a previously completed
            # translation by replacing it with the original English excerpt.
            continue
        provenance = research_context.provenance(article, settings.analysis_model) if managed_live and research_context else {}
        statement = (
            postgresql_insert(ArticleAnalysis)
            .values(
                id=uuid.uuid4(),
                assistant_id=article.assistant_id,
                article_id=article.id,
                status=payload["status"],
                headline=str(payload["headline"])[:2000],
                news_summary=str(payload["news_summary"]),
                business_connection=str(payload["business_connection"]),
                opportunity=str(payload["opportunity"]),
                risk=str(payload["risk"]),
                suggested_action=str(payload["suggested_action"]),
                time_horizon=str(payload["time_horizon"]),
                confidence=_payload_float(payload["confidence"]),
                facts=payload["facts"],
                inferences=payload["inferences"],
                citations=payload["citations"],
                topic_scores=payload["topic_scores"],
                model=str(payload["model"]),
                input_chars=len(article.normalized_text),
                input_tokens=_payload_int(payload["input_tokens"]),
                output_tokens=_payload_int(payload["output_tokens"]),
                estimated_cost_usd=_payload_float(payload["estimated_cost_usd"]),
                error_message=payload["error_message"],
                research_provenance=provenance,
            )
            .on_conflict_do_update(
                index_elements=[ArticleAnalysis.article_id],
                set_={key: value for key, value in payload.items() if key not in {"input_chars"}} | {"input_chars": len(article.normalized_text), "research_provenance": provenance},
                where=or_(ArticleAnalysis.status.in_(["fallback", "failed"]),
                    or_(ArticleAnalysis.research_provenance["generation"].as_string().is_distinct_from(provenance["generation"]),
                        ArticleAnalysis.research_provenance["model"].as_string().is_distinct_from(provenance["model"]),
                        ArticleAnalysis.research_provenance["article_db_hash"].as_string().is_distinct_from(provenance["article_db_hash"])) if provenance else false_condition()),
            )
            .returning(ArticleAnalysis.id)
        )
        async with SessionLocal() as session:
            inserted = (await session.execute(statement)).scalar_one_or_none()
            if inserted is not None and payload["status"] == "succeeded":
                current = await session.get(ArticleAnalysis, inserted)
                preview = await session.scalar(select(Publication).where(Publication.analysis_id == inserted, Publication.assistant_id == assistant_id, Publication.status == "preview"))
                if current is not None and preview is not None:
                    blocks = (settings.message_templates.get("feedback") or {}).get("blocks") if isinstance(settings.message_templates, dict) else None
                    preview.message_text = _render_publication_message(analysis=current, article=article, source=source, business_name=settings.business_name, template_blocks=blocks if isinstance(blocks, list) else None, output_language=_source_output_language(source, profile))
                    preview.audit = {**(preview.audit or {}), "translation_pending": False, "message_template": MESSAGE_TEMPLATE_VERSION}
                    preview.updated_at = _utcnow()
            await session.commit()
            created += int(inserted is not None)
            succeeded += int(inserted is not None and payload["status"] == "succeeded")
    return {
        "succeeded": succeeded,
        "candidates": len(rows[:limit]),
        "created": created,
        "model_calls": model_calls,
        "fallback_calls": fallback_calls,
        "daily_model_requests_before_run": daily_count,
        "daily_input_chars_before_run": daily_chars,
        "request_cap": settings.model_daily_request_cap,
    }


async def reanalyze_fallback_articles(
    settings: Settings,
    *,
    limit: int = 5,
    assistant_id: uuid.UUID | None = None,
) -> dict[str, object]:
    """Use the authoritative pipeline for recovery, with a total call ceiling.

    No legacy profile #1, historical selected flag, direct send or unpaid
    retry path. The same context, evidence, translation and budget gates apply.
    """
    async with SessionLocal() as session:
        ids = (await session.scalars(select(AssistantWorkspace.id).where(
            AssistantWorkspace.status == "active", AssistantWorkspace.deleted_at.is_(None),
            AssistantWorkspace.id == assistant_id if assistant_id is not None else true(),
        ).order_by(AssistantWorkspace.created_at))).all()
    remaining = max(0, min(limit, 20))
    results: list[dict[str, object]] = []
    for aid in ids:
        if remaining <= 0:
            break
        result = await analyze_pending_articles(settings, limit=remaining, assistant_id=aid, fallback_only=True)
        calls = _payload_int(result.get("model_calls"))
        remaining -= calls
        results.append({"assistant_id": str(aid), **result})
    succeeded = sum(_payload_int(r.get("succeeded")) for r in results)
    calls = sum(_payload_int(r.get("model_calls")) for r in results)
    return {"candidates": sum(_payload_int(r.get("candidates")) for r in results),
            "succeeded": succeeded, "failed": max(0, calls - succeeded),
            "model_calls": calls, "no_publish": True, "workspaces": results}


async def create_publication_previews(settings: Settings, *, limit: int, assistant_id: uuid.UUID | None = None) -> dict[str, int]:
    settings = await settings_for_assistant(settings, assistant_id)
    async with SessionLocal() as session:
        # Once clustering has grouped several sources into one event, only
        # the representative article enters the publication queue. Every
        # member remains visible through the cluster/insights endpoints for
        # fact-checking and disagreement review.
        clustered_non_representative = exists(
            select(ClusterMember.id)
            .join(EventCluster, EventCluster.id == ClusterMember.cluster_id)
            .where(
                ClusterMember.article_id == ArticleAnalysis.article_id,
                EventCluster.representative_article_id != ArticleAnalysis.article_id,
            )
        )
        rows = (
            await session.execute(
                select(ArticleAnalysis, NormalizedArticle, SourceItem, Source)
                .join(NormalizedArticle, NormalizedArticle.id == ArticleAnalysis.article_id)
                .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
                .join(Source, Source.id == SourceItem.source_id)
                .outerjoin(Publication, Publication.analysis_id == ArticleAnalysis.id)
                .where(
                    Publication.id.is_(None),
                    ~clustered_non_representative,
                    ArticleAnalysis.assistant_id == assistant_id if assistant_id is not None else true(),
                    _freshness_condition(NormalizedArticle.published_at, settings),
                )
                .order_by(ArticleAnalysis.created_at.desc())
                .limit(limit)
            )
        ).all()
        decisions = await _article_decisions(session, [r[1] for r in rows], settings)
    preview_settings = settings
    telegram = TelegramClient(preview_settings)
    feedback_template = (
        (preview_settings.message_templates.get("feedback") or {}).get("blocks")
        if isinstance(preview_settings.message_templates, dict)
        else None
    )
    created = 0
    for analysis, article, item, source in rows:
        _, _, source_safety = sanitize_untrusted_source(
            title=article.title,
            text=article.normalized_text,
        )
        image_url = str((article.provenance or {}).get("image_url") or "").strip()
        include_image = _template_has_image(feedback_template)
        message = _render_publication_message(
            analysis=analysis,
            article=article,
            source=source,
            business_name=getattr(preview_settings, "business_name", "داتین"),
            template_blocks=feedback_template if isinstance(feedback_template, list) else None,
        )
        statement = (
            postgresql_insert(Publication)
            .values(
                id=uuid.uuid4(),
                assistant_id=analysis.assistant_id,
                analysis_id=analysis.id,
                idempotency_key=f"analysis:{analysis.id}",
                status="preview",
                channel_id_hash=telegram.channel_hash,
                message_text=message,
                telegram_payload={
                    "message_ids": [],
                    "dry_run": True,
                    "parse_mode": "HTML",
                    "link_preview_is_disabled": True,
                    **({"image_url": image_url} if include_image and image_url.startswith("https://") else {}),
                },
                audit={
                    "created_by": "pipeline",
                    "pilot_mode": settings.pilot_mode,
                    "message_template": MESSAGE_TEMPLATE_VERSION,
                    # Borderline items are visible in the review queue but are
                    # never eligible for automatic Telegram delivery.
                    "review_only": decisions[article.id]["review_only"],
                    "relevance_state": decisions[article.id]["relevance_state"],
                    "source_content_safety": source_safety.as_dict(),
                },
            )
            .on_conflict_do_nothing(index_elements=[Publication.idempotency_key])
            .returning(Publication.id)
        )
        async with SessionLocal() as session:
            inserted = (await session.execute(statement)).scalar_one_or_none()
            await session.commit()
            created += int(inserted is not None)
    return {"candidates": len(rows), "created": created}


async def refresh_publication_previews(*, limit: int = 200) -> dict[str, int]:
    """Apply the current renderer only to unpublished preview rows."""
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(
                    Publication,
                    ArticleAnalysis,
                    NormalizedArticle,
                    Source,
                )
                .join(ArticleAnalysis, ArticleAnalysis.id == Publication.analysis_id)
                .join(NormalizedArticle, NormalizedArticle.id == ArticleAnalysis.article_id)
                .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
                .join(Source, Source.id == SourceItem.source_id)
                .where(Publication.status == "preview")
                .order_by(Publication.created_at.desc())
                .limit(limit)
            )
        ).all()
        for publication, analysis, article, source in rows:
            refresh_settings = await settings_for_assistant(get_settings(), publication.assistant_id)
            refresh_template = (
                (refresh_settings.message_templates.get("feedback") or {}).get("blocks")
                if isinstance(refresh_settings.message_templates, dict)
                else None
            )
            publication.message_text = _render_publication_message(
                analysis=analysis,
                article=article,
                source=source,
                business_name=getattr(refresh_settings, "business_name", "داتین"),
                template_blocks=refresh_template if isinstance(refresh_template, list) else None,
            )
            publication.telegram_payload = {
                **publication.telegram_payload,
                "dry_run": True,
                "parse_mode": "HTML",
                "link_preview_is_disabled": True,
            }
            publication.audit = {
                **publication.audit,
                "message_template": MESSAGE_TEMPLATE_VERSION,
                "preview_refreshed_by": "pipeline",
            }
            publication.updated_at = _utcnow()
        await session.commit()
    return {"candidates": len(rows), "refreshed": len(rows)}


async def repair_report_translations(settings: Settings, *, assistant_id: uuid.UUID, limit: int = 5, apply: bool = False) -> dict[str, Any]:
    """Scoped, budgeted repair; original source/scores/delivery stay immutable.

    Only previews are repaired. Never sends or edits Telegram, and never
    changes a published/edited/closed article or another assistant's report.
    Provider failures retain original evidence for a later bounded retry.
    """
    settings = await settings_for_assistant(settings, assistant_id)
    async with SessionLocal() as session:
        assistant = await session.get(AssistantWorkspace, assistant_id)
        if assistant is None or assistant.deleted_at is not None:
            raise ValueError("assistant not found")
        profile = await _profile_for_assistant(session, assistant_id)
        context: BusinessContext = profile or _general_market_profile(assistant)
        rows = (await session.execute(
            select(ArticleAnalysis, NormalizedArticle, Source, Publication)
            .join(NormalizedArticle, NormalizedArticle.id == ArticleAnalysis.article_id)
            .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
            .join(Source, Source.id == SourceItem.source_id)
            .join(Publication, Publication.analysis_id == ArticleAnalysis.id)
            .where(ArticleAnalysis.assistant_id == assistant_id, Source.assistant_id == assistant_id, Publication.assistant_id == assistant_id, Publication.status == "preview")
            .order_by(ArticleAnalysis.created_at.desc())
        )).all()
    result: dict[str, Any] = {"assistant_id": str(assistant_id), "apply": apply, "candidates": 0, "translated": 0, "refreshed": 0, "failed": 0, "budget_deferred": 0, "items": []}
    calls = 0
    translated_reports: dict[uuid.UUID, StructuredAnalysis] = {}
    failed_reports: set[uuid.UUID] = set()
    client = OpenAIClient(settings)
    template = (settings.message_templates.get("feedback") or {}).get("blocks") if isinstance(settings.message_templates, dict) else None
    for row_index, (analysis, article, source, publication) in enumerate(rows):
        target = _source_output_language(source, context)
        needs_translation = bool(language_issues(analysis_text(analysis), target))
        rendered = _render_publication_message(analysis=analysis, article=article, source=source, business_name=settings.business_name, template_blocks=template if isinstance(template, list) else None, output_language=target)
        if not needs_translation and rendered == publication.message_text:
            continue
        result["candidates"] += 1
        result["items"].append({"analysis_id": str(analysis.id), "translation_required": needs_translation, "output_language": target})
        if not apply:
            continue
        fields = analysis_text(analysis)
        original = json.dumps(fields, ensure_ascii=False, sort_keys=True)
        translation = None
        attempt = None
        if needs_translation:
            if analysis.id in failed_reports:
                result["failed"] += 1
                continue
            if analysis.id not in translated_reports and (calls >= min(max(limit, 1), settings.model_max_requests_per_run) or not client.configured):
                result["budget_deferred"] += 1
                continue
            if analysis.id not in translated_reports:
                batch: dict[str, dict[str, Any]] = {}
                for candidate, candidate_article, candidate_source, _preview in rows[row_index:]:
                    if len(batch) >= 3:
                        break
                    if candidate.id in failed_reports or candidate.id in translated_reports or _source_output_language(candidate_source, context) != target or not language_issues(analysis_text(candidate), target):
                        continue
                    candidate_fields = analysis_text(candidate)
                    # Translate evidence, not the legacy fallback's invented
                    # banking connection. Keep its fallback status unchanged.
                    if candidate.status == "fallback":
                        candidate_fields.update(business_connection=report_copy(target)["analysis_pending"], opportunity="", risk="", suggested_action=report_copy(target)["analysis_pending"], inferences=[])
                    candidate_fields["headline"] = candidate_article.title
                    batch[str(candidate.id)] = candidate_fields
                input_chars = len(json.dumps(batch, ensure_ascii=False))
                attempt = await _reserve_relevance_budget(settings, assistant_id, input_chars, job_type="analysis_model", article_id=article.id)
                if attempt is None:
                    result["budget_deferred"] += 1
                    continue
                calls += 1
                try:
                    batch_result = await client.translate_reports(reports=batch, output_language=target)
                    for index, item in enumerate(batch_result.payload["reports"]):
                        translated_reports[uuid.UUID(item["report_id"])] = StructuredAnalysis(payload=item, model=batch_result.model, input_tokens=batch_result.input_tokens // len(batch) + int(index < batch_result.input_tokens % len(batch)), output_tokens=batch_result.output_tokens // len(batch) + int(index < batch_result.output_tokens % len(batch)), estimated_cost_usd=batch_result.estimated_cost_usd / len(batch))
                    await _finish_job(attempt, status="succeeded", result={"article_id": str(article.id), "input_chars": input_chars, "purpose": "report_translation", "output_language": target, "report_count": len(batch)})
                except Exception as exc:
                    failed_reports.update(uuid.UUID(key) for key in batch)
                    # Language exceptions contain only schema field names,
                    # never provider output. Keep that safe diagnostic so
                    # false positives do not require another paid probe.
                    error = str(exc) if isinstance(exc, ReportLanguageError) else type(exc).__name__
                    await _finish_job(attempt, status="failed", result={"article_id": str(article.id), "input_chars": input_chars, "purpose": "report_translation", "report_count": len(batch)}, error=error)
                    result["failed"] += 1
                    continue
            translation = translated_reports[analysis.id]
        async with SessionLocal() as session:
            current = await session.get(ArticleAnalysis, analysis.id, with_for_update=True)
            preview = await session.get(Publication, publication.id, with_for_update=True)
            # An owner/scheduler may have published or reanalysed while the
            # provider was running. Don't overwrite their concurrent work.
            current_source = await session.get(Source, source.id)
            current_assistant = await session.get(AssistantWorkspace, assistant_id)
            current_profile = await _profile_for_assistant(session, assistant_id)
            current_target = _source_output_language(current_source, current_profile or _general_market_profile(current_assistant)) if current_source is not None else None
            if current is None or preview is None or preview.status != "preview" or preview.message_text != publication.message_text or current.status != analysis.status or current_target != target or json.dumps(analysis_text(current), ensure_ascii=False, sort_keys=True) != original:
                result["failed"] += 1
                continue
            if translation is not None:
                for key in (*TEXT_FIELDS, *LIST_FIELDS):
                    setattr(current, key, translation.payload[key])
                current.input_tokens += translation.input_tokens
                current.output_tokens += translation.output_tokens
                current.estimated_cost_usd += translation.estimated_cost_usd
                current.citations = [{**citation, "output_language": target, "language_revision": LANGUAGE_REVISION, "translation_pending": False, "translation_model": translation.model} for citation in (current.citations or [{"source": source.name, "url": article.canonical_url}])]
            preview.message_text = _render_publication_message(analysis=current, article=article, source=source, business_name=settings.business_name, template_blocks=template if isinstance(template, list) else None, output_language=target)
            preview.audit = {**(preview.audit or {}), "message_template": MESSAGE_TEMPLATE_VERSION, "translation_repaired_at": _utcnow().isoformat(), "output_language": target}
            preview.updated_at = _utcnow()
            await session.commit()
        result["translated" if translation else "refreshed"] += 1
    return result


PUBLISH_CLAIM_STALE_AFTER = timedelta(minutes=15)


async def _release_publish_claim(publication_id: uuid.UUID, previous_status: str, error: str) -> None:
    """Return a claimed publication to its prior state after a failed send."""
    async with SessionLocal() as session:
        publication = await session.get(Publication, publication_id, with_for_update=True)
        if publication is not None and publication.status == "publishing":
            publication.status = previous_status
            publication.error_message = error[:2000]
            audit = dict(publication.audit or {})
            audit.pop("publishing_started_at", None)
            publication.audit = audit
            publication.updated_at = _utcnow()
            await session.commit()


async def publish_publication(publication_id: uuid.UUID, *, allow_stale_claim: bool = False) -> dict[str, object]:
    """Send one publication to Telegram at most once.

    The row is moved to ``publishing`` inside the locked transaction before
    anything is sent, so a concurrent scheduler run or manual click sees the
    claim and never sends a second copy.  A failed send releases the claim.
    A claim left behind by a crashed process is never retried
    automatically (the message may already be out); only an explicit owner
    action (``allow_stale_claim``) may retry it after 15 minutes.
    """
    settings = get_settings()
    observer_message_context: tuple[ArticleAnalysis, NormalizedArticle, Source] | None = None
    image_url: str | None = None
    sandbox_enabled = False
    async with SessionLocal() as session:
        publication = await session.get(Publication, publication_id, with_for_update=True)
        if publication is None:
            raise KeyError("publication not found")
        if publication.status in {"published", "edited"}:
            return {
                "publication_id": str(publication.id),
                "status": publication.status,
                "message_id": publication.message_id,
                "idempotent": True,
            }
        previous_status = publication.status
        if publication.status == "publishing":
            try:
                started = datetime.fromisoformat(str((publication.audit or {}).get("publishing_started_at")))
            except (TypeError, ValueError):
                started = publication.updated_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if not allow_stale_claim or _utcnow() - started < PUBLISH_CLAIM_STALE_AFTER:
                raise RuntimeError("publication is already being sent")
            previous_status = "preview"
        elif publication.status not in {"preview", "failed"}:
            raise RuntimeError(f"publication in status {publication.status} cannot be sent")
        analysis_id = publication.analysis_id
        assistant_id = publication.assistant_id
        assistant = await session.get(AssistantWorkspace, assistant_id)
        sandbox_value = (assistant.config or {}).get("sandbox") if isinstance(assistant, AssistantWorkspace) else None
        sandbox_enabled = bool(isinstance(sandbox_value, dict) and sandbox_value.get("enabled"))
        if sandbox_enabled:
            raise RuntimeError("sandbox publication is disabled; use the preview only")
        approval_state = ((publication.audit or {}).get("approval") or {}).get("state")
        if approval_state in {"draft", "review", "rejected"}:
            raise RuntimeError("publication requires final approval before delivery")
        message_text = publication.message_text
        image_url = str((publication.telegram_payload or {}).get("image_url") or "").strip() or None
        observer_row = (
            await session.execute(
                select(ArticleAnalysis, NormalizedArticle, Source)
                .join(NormalizedArticle, NormalizedArticle.id == ArticleAnalysis.article_id)
                .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
                .join(Source, Source.id == SourceItem.source_id)
                .where(ArticleAnalysis.id == analysis_id)
            )
        ).one_or_none()
        if observer_row is None:
            raise RuntimeError("publication requires its original article and source")
        if observer_row is not None:
            observer_message_context = (observer_row[0], observer_row[1], observer_row[2])
            if any(row.assistant_id != assistant_id for row in observer_row):
                raise RuntimeError("publication context must belong to its project")
            effective = await settings_for_assistant(settings, assistant_id)
            if not isinstance(assistant, AssistantWorkspace) or assistant.status != "active" or assistant.deleted_at is not None or not observer_row[2].enabled:
                raise RuntimeError("publication requires an active project and enabled source")
            published_at = observer_row[1].published_at
            if published_at is not None and published_at < _utcnow() - timedelta(days=effective.freshness_window_days):
                raise RuntimeError("publication is outside the configured freshness window")
            if observer_row[0].status != "succeeded":
                raise RuntimeError("publication requires completed AI analysis")
            current_topics = (await session.scalars(select(Topic).where(Topic.assistant_id == assistant_id, Topic.enabled.is_(True)).order_by(Topic.topic_key))).all()
            current_profile = await _profile_for_assistant(session, assistant_id)
            context_for_language = await resolve_context(session, assistant_id, effective)
            language_profile: BusinessContext = current_profile or _general_market_profile(assistant)
            if current_profile is None and context_for_language and context_for_language.live:
                language_profile.output_language = context_for_language.record.style.get("output_language", "fa")
                language_profile.output_tone = context_for_language.record.style.get("output_tone", "")
            target_language = _source_output_language(observer_row[2], language_profile)
            if language_issues(analysis_text(observer_row[0]), target_language):
                raise RuntimeError("publication requires a complete translation in the configured output language")
            stored_language = analysis_language(observer_row[0], observer_row[2])
            recorded = next((citation.get("output_language") for citation in (observer_row[0].citations or []) if isinstance(citation, dict) and citation.get("output_language")), stored_language)
            if stored_language != target_language or recorded != target_language:
                raise RuntimeError("publication translation must match the current output language")
            decision = (await _article_decisions(session, [observer_row[1]], effective))[observer_row[1].id]
            research_context = await resolve_context(session, assistant_id, effective)
            if research_context and research_context.live:
                if research_context.state != "ready" or not decision.get("business_ready", True) or not decision.get("business_gate_passed", True):
                    raise RuntimeError("publication requires a current approved business assessment")
                if observer_row[0].research_provenance != research_context.provenance(observer_row[1], effective.analysis_model):
                    raise RuntimeError("publication analysis must match the approved research context and complete news text")
            approval = (publication.audit or {}).get("relevance_approval") or {}
            manually_approved = bool(decision["can_approve"] and approval.get("context_hash") == _relevance_hash(effective, assistant, current_topics, current_profile)
                                     and approval.get("threshold") == decision["relevance_threshold"]
                                     and approval.get("score") == decision["relevance_score"]
                                     and approval.get("content_hash") == article_digest(observer_row[1].title, observer_row[1].normalized_text, observer_row[1].extraction_status != "complete"))
            if not decision["publishable"] and not manually_approved:
                raise RuntimeError("publication requires current AI relevance above the project/topic threshold")
        # Claim before releasing the row lock: from here on no other caller
        # can start a second send of this publication.
        publication.status = "publishing"
        publication.audit = {**(publication.audit or {}), "publishing_started_at": _utcnow().isoformat()}
        publication.updated_at = _utcnow()
        await session.commit()
    try:
        return await _send_claimed_publication(
            publication_id,
            settings=settings,
            assistant_id=assistant_id,
            analysis_id=analysis_id,
            message_text=message_text,
            image_url=image_url,
            observer_message_context=observer_message_context,
        )
    except _DeliveredNotRecorded:
        # The message is already in Telegram. Keep the claim so no retry
        # can send it again; the owner sees the stuck ``publishing`` row.
        raise
    except Exception as exc:
        # Nothing was delivered (the main send raised), so the claim is
        # released and the item stays eligible.
        await _release_publish_claim(publication_id, previous_status, f"{type(exc).__name__}: {exc}")
        raise


class _DeliveredNotRecorded(RuntimeError):
    """Telegram accepted the message but the result could not be stored."""


async def _send_claimed_publication(
    publication_id: uuid.UUID,
    *,
    settings: Settings,
    assistant_id: uuid.UUID,
    analysis_id: uuid.UUID,
    message_text: str,
    image_url: str | None,
    observer_message_context: tuple[ArticleAnalysis, NormalizedArticle, Source] | None,
) -> dict[str, object]:
    settings = await settings_for_assistant(settings, assistant_id)
    # Re-render at delivery time as well as at preview time. This upgrades
    # previews created by an older release so an already-queued message cannot
    # leak the deployment-wide business label into a project channel.
    if observer_message_context is not None:
        delivery_analysis, delivery_article, delivery_source = observer_message_context
        feedback_template = (
            (settings.message_templates.get("feedback") or {}).get("blocks")
            if isinstance(settings.message_templates, dict)
            else None
        )
        message_text = _render_publication_message(
            analysis=delivery_analysis,
            article=delivery_article,
            source=delivery_source,
            business_name=getattr(settings, "business_name", "داتین"),
            template_blocks=feedback_template if isinstance(feedback_template, list) else None,
        )
        if _template_has_image(feedback_template if isinstance(feedback_template, list) else None):
            candidate = str((delivery_article.provenance or {}).get("image_url") or "").strip()
            image_url = candidate if candidate.startswith("https://") else None
    telegram = TelegramClient(settings)
    permission = await telegram.check_permissions()
    if not permission.ready:
        raise RuntimeError(permission.error or "Telegram bot lacks Post Messages permission")
    silent = bool(getattr(settings, "telegram_silent_notifications", False))
    message_ids = await telegram.send_analysis(message_text, analysis_id=analysis_id, silent=silent, image_url=image_url)
    try:
        observer_message_ids, observer_error = await _send_observer_copy(
            telegram, settings, analysis_id, message_text, silent, observer_message_context
        )
    except Exception as exc:
        # The feedback channel already has the message: never undo the claim
        # (a retry would duplicate it). Record the observer failure instead.
        observer_message_ids, observer_error = [], redact_sensitive_text(f"{type(exc).__name__}: {exc}", limit=500)
    try:
        await _record_delivery(publication_id, settings, message_ids, observer_message_ids, observer_error, permission)
    except Exception as exc:
        LOGGER.exception("publication delivered but not recorded", extra={"publication_id": str(publication_id)})
        raise _DeliveredNotRecorded(f"delivered as {message_ids} but not recorded: {type(exc).__name__}") from exc
    return {
        "publication_id": str(publication_id),
        "status": "published",
        "message_ids": message_ids,
        "observer_message_ids": observer_message_ids,
        "idempotent": False,
    }


async def _record_delivery(
    publication_id: uuid.UUID,
    settings: Settings,
    message_ids: list[int],
    observer_message_ids: list[int],
    observer_error: str | None,
    permission,
) -> None:
    now = _utcnow()
    async with SessionLocal() as session:
        publication = await session.get(Publication, publication_id, with_for_update=True)
        if publication is None:
            raise KeyError("publication not found after send")
        publication.status = "published"
        publication.message_id = message_ids[0] if message_ids else None
        publication.telegram_payload = {
            "message_ids": message_ids,
            "observer_message_ids": observer_message_ids,
            "channels": {
                "feedback": settings.telegram_channel_id,
                "observer": settings.telegram_observer_channel_id,
            },
            "dry_run": False,
            **({"observer_error": observer_error} if observer_error else {}),
        }
        audit = {k: v for k, v in (publication.audit or {}).items() if k != "publishing_started_at"}
        publication.audit = {
            **audit,
            "published_by": "pipeline",
            "permission": asdict(permission),
        }
        publication.published_at = now
        publication.updated_at = now
        publication.error_message = None
        await session.commit()


async def _send_observer_copy(
    telegram: TelegramClient,
    settings: Settings,
    analysis_id: uuid.UUID,
    message_text: str,
    silent: bool,
    observer_message_context: tuple[ArticleAnalysis, NormalizedArticle, Source] | None,
) -> tuple[list[int], str | None]:
    observer_message_ids: list[int] = []
    if settings.telegram_observer_channel_id and settings.telegram_observer_channel_id != settings.telegram_channel_id:
        observer_message = message_text
        observer_template = (
            (settings.message_templates.get("observer") or {}).get("blocks")
            if isinstance(settings.message_templates, dict)
            else None
        )
        if isinstance(observer_template, list) and observer_message_context is not None:
            observer_analysis, observer_article, observer_source = observer_message_context
            observer_message = _render_publication_message(
                analysis=observer_analysis,
                article=observer_article,
                source=observer_source,
                business_name=getattr(settings, "business_name", "داتین"),
                template_blocks=observer_template,
            )
        observer_message_ids = await telegram.send_analysis(
            observer_message,
            analysis_id=analysis_id,
            channel_id=settings.telegram_observer_channel_id,
            include_feedback_buttons=False,
            silent=silent,
            image_url=(
                str((observer_article.provenance or {}).get("image_url") or "").strip()
                if observer_message_context is not None and _template_has_image(observer_template if isinstance(observer_template, list) else None)
                else None
            ),
        )
    return observer_message_ids, None


async def approve_borderline_publication(publication_id: uuid.UUID) -> dict[str, object]:
    """Approve one borderline review item, enforcing a daily cap of ten."""
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    now = _utcnow()
    async with SessionLocal() as session:
        publication = await session.get(Publication, publication_id, with_for_update=True)
        if publication is None:
            raise KeyError("publication not found")
        audit = dict(publication.audit or {})
        article = await session.scalar(select(NormalizedArticle).join(ArticleAnalysis, ArticleAnalysis.article_id == NormalizedArticle.id).where(ArticleAnalysis.id == publication.analysis_id))
        if article is None or article.assistant_id != publication.assistant_id:
            raise RuntimeError("publication requires its original article")
        settings = await settings_for_assistant(get_settings(), publication.assistant_id)
        assistant = await session.get(AssistantWorkspace, publication.assistant_id, with_for_update=True)
        topics = (await session.scalars(select(Topic).where(Topic.assistant_id == publication.assistant_id, Topic.enabled.is_(True)).order_by(Topic.topic_key))).all()
        profile = await _profile_for_assistant(session, publication.assistant_id)
        decision = (await _article_decisions(session, [article], settings))[article.id]
        if not decision["can_approve"]:
            raise RuntimeError("publication is not a borderline review item")
        day_start = datetime.now(ZoneInfo(settings.timezone)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        approved = (await session.execute(
            select(Publication).where(
                Publication.audit["borderline_approved_at"].astext >= day_start.isoformat(),
                Publication.assistant_id == publication.assistant_id,
                Publication.id != publication.id,
            ).with_for_update()
        )).scalars().all()
        used_today = sum(1 for item in approved if bool((item.audit or {}).get("borderline_approved")))
        if used_today >= 10:
            raise RuntimeError("borderline daily approval limit reached")
        publication.audit = {
            **audit,
            "review_only": False,
            "borderline_approved": True,
            "borderline_approved_at": now.isoformat(),
            "relevance_approval": {"context_hash": _relevance_hash(settings, assistant, topics, profile),
                                   "threshold": decision["relevance_threshold"], "score": decision["relevance_score"],
                                   "content_hash": article_digest(article.title, article.normalized_text, article.extraction_status != "complete")},
        }
        publication.updated_at = now
        await session.commit()
    return await publish_publication(publication_id)


async def publish_ready_previews(
    settings: Settings,
    *,
    limit: int,
    assistant_id: uuid.UUID | None = None,
    created_after: datetime | None = None,
    newest_first: bool = False,
) -> dict[str, object]:
    settings = await settings_for_assistant(settings, assistant_id)
    # The workspace may lower the deployment cap; never let a global scheduler
    # call bypass that project-level publication limit.
    limit = min(limit, settings.max_items_per_run)
    if settings.pilot_mode or not settings.auto_publish:
        return {"published": 0, "status": "dry_run_gate"}
    async with SessionLocal() as session:
        filters = [
            Publication.status == "preview",
            Publication.assistant_id == assistant_id if assistant_id is not None else true(),
            _freshness_condition(NormalizedArticle.published_at, settings),
        ]
        if created_after is not None:
            filters.append(Publication.created_at >= created_after)
        candidates = (
            await session.execute(
                select(Publication, NormalizedArticle)
                .join(ArticleAnalysis, ArticleAnalysis.id == Publication.analysis_id)
                .join(NormalizedArticle, NormalizedArticle.id == ArticleAnalysis.article_id)
                .where(*filters)
                .order_by(Publication.created_at.desc() if newest_first else Publication.created_at)
            )
        ).all()
        # A borderline article is an operator signal, not an automatic
        # delivery candidate.  Filter after the freshness/scope query so a
        # large review queue cannot starve genuinely selected items.
        decisions = await _article_decisions(session, [article for _, article in candidates], settings)
        ids = [
            publication.id
            for publication, article in candidates
            if decisions[article.id]["publishable"]
            and (((publication.audit or {}).get("approval") or {}).get("state") in {None, "", "unmanaged", "approved"})
        ][:limit]
    results: list[dict[str, object]] = []
    for publication_id in ids:
        try:
            results.append(await publish_publication(publication_id))
        except Exception as exc:
            results.append(
                {
                    "publication_id": str(publication_id),
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}"[:500],
                }
            )
    return {
        "published": sum(result["status"] == "published" for result in results),
        "eligible_since": created_after.isoformat() if created_after is not None else None,
        "results": results,
    }


async def record_feedback(
    analysis_id: uuid.UUID,
    *,
    actor_key: str,
    value: str,
    note: str | None = None,
    source: str = "api",
) -> dict[str, object]:
    if value not in {"up", "down"}:
        raise ValueError("feedback value must be up or down")
    actor_key = actor_key.strip().lower().lstrip("@")[:128]
    if not actor_key:
        raise ValueError("feedback actor is required")
    async with SessionLocal() as session:
        analysis_owner = await session.execute(
            select(ArticleAnalysis.id, ArticleAnalysis.assistant_id, AssistantWorkspace.config)
            .join(AssistantWorkspace, AssistantWorkspace.id == ArticleAnalysis.assistant_id)
            .where(ArticleAnalysis.id == analysis_id)
        )
        analysis_row = analysis_owner.one_or_none()
    if analysis_row is None:
        raise ValueError("analysis not found for feedback")
    assistant_id = analysis_row.assistant_id
    runtime = (analysis_row.config or {}).get("runtime") or {}
    configured_users = runtime.get("allowed_feedback_usernames")
    allowed_users = {
        str(value).strip().lower().lstrip("@")
        for value in (configured_users if isinstance(configured_users, list) else get_settings().allowed_telegram_username_values)
        if str(value).strip()
    }
    if actor_key not in allowed_users:
        raise ValueError("feedback actor is not authorized")
    statement = (
        postgresql_insert(Feedback)
        .values(
            id=uuid.uuid4(),
            assistant_id=assistant_id,
            analysis_id=analysis_id,
            actor_key=actor_key,
            value=value,
            note=note,
            source=source,
        )
        .on_conflict_do_nothing(
            index_elements=[Feedback.analysis_id, Feedback.actor_key],
        )
        .returning(Feedback.id)
    )
    try:
        async with SessionLocal() as session:
            feedback_id = (await session.execute(statement)).scalar_one_or_none()
            duplicate = feedback_id is None
            if duplicate:
                feedback_id = (
                    await session.execute(
                        select(Feedback.id).where(
                            Feedback.analysis_id == analysis_id,
                            Feedback.actor_key == actor_key,
                        )
                    )
                ).scalar_one()
            await session.commit()
    except Exception:
        LOGGER.exception("feedback persistence failed", extra={"analysis_id": str(analysis_id), "actor_key": actor_key, "value": value})
        raise ValueError("feedback persistence failed") from None
    return {
        "feedback_id": str(feedback_id),
        "analysis_id": str(analysis_id),
        "value": value,
        "duplicate": duplicate,
    }


async def feedback_daily_report(*, days: int = 1, assistant_id: uuid.UUID | None = None, now: datetime | None = None) -> dict[str, object]:
    """Return an auditable feedback summary without changing ranking or thresholds."""
    if days < 1 or days > 30:
        raise ValueError("days must be between 1 and 30")
    period_end = now or _utcnow()
    period_start = period_end - timedelta(days=days)
    base = [Feedback.created_at >= period_start, Feedback.created_at <= period_end]
    if assistant_id is not None:
        base.append(Feedback.assistant_id == assistant_id)
    async with SessionLocal() as session:
        totals = (await session.execute(
            select(
                func.count(Feedback.id),
                func.count(distinct(Feedback.actor_key)),
                func.sum(case((Feedback.value == "up", 1), else_=0)),
                func.sum(case((Feedback.value == "down", 1), else_=0)),
            ).where(*base)
        )).one()
        source_rows = (await session.execute(
            select(Feedback.source, func.count(Feedback.id)).where(*base).group_by(Feedback.source).order_by(func.count(Feedback.id).desc())
        )).all()
        actor_rows = (await session.execute(
            select(
                Feedback.actor_key,
                func.count(Feedback.id),
                func.sum(case((Feedback.value == "up", 1), else_=0)),
                func.sum(case((Feedback.value == "down", 1), else_=0)),
            ).where(*base).group_by(Feedback.actor_key).order_by(func.count(Feedback.id).desc(), Feedback.actor_key)
        )).all()
        actor_timeline_rows = (await session.execute(
            select(Feedback.actor_key, Feedback.created_at, Feedback.value)
            .where(*base)
            .order_by(Feedback.created_at.asc())
        )).all()
        topic_base = [*base, ArticleAnalysis.id == Feedback.analysis_id, ArticleTopic.article_id == ArticleAnalysis.article_id, Topic.id == ArticleTopic.topic_id]
        topic_rows = (await session.execute(
            select(
                Topic.id,
                Topic.name,
                func.count(distinct(Feedback.id)),
                func.sum(case((Feedback.value == "up", 1), else_=0)),
                func.sum(case((Feedback.value == "down", 1), else_=0)),
            ).select_from(Feedback, ArticleAnalysis, ArticleTopic, Topic).where(*topic_base).group_by(Topic.id, Topic.name).order_by(func.count(distinct(Feedback.id)).desc())
        )).all()
    total, actors, up, down = (int(value or 0) for value in totals)
    topics = [
        {"topic_id": str(topic_id), "topic": name, "samples": int(samples or 0), "up": int(up_votes or 0), "down": int(down_votes or 0)}
        for topic_id, name, samples, up_votes, down_votes in topic_rows
    ]
    timeline_by_actor: dict[str, dict[str, dict[str, int]]] = {}
    for actor, created_at, value in actor_timeline_rows:
        actor_key = str(actor or "-")
        day = created_at.date().isoformat() if hasattr(created_at, "date") else str(created_at)[:10]
        day_row = timeline_by_actor.setdefault(actor_key, {}).setdefault(day, {"count": 0, "up": 0, "down": 0})
        day_row["count"] += 1
        if value in {"up", "down"}:
            day_row[value] += 1
    return {
        "status": "report",
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "days": days,
        "assistant_id": str(assistant_id) if assistant_id else None,
        "total_feedback": total,
        "signal_count": total,
        "unique_actors": actors,
        "up": up,
        "down": down,
        "related": up,
        "unrelated": down,
        "relevant": up,
        "irrelevant": down,
        "by_source": [{"source": source, "count": int(count)} for source, count in source_rows],
        "by_actor": [
            {
                "actor_key": actor,
                "total": int(total_count or 0),
                "up": int(up_votes or 0),
                "down": int(down_votes or 0),
                "timeline": [
                    {"date": day, **values}
                    for day, values in sorted(timeline_by_actor.get(str(actor or "-"), {}).items())
                ],
            }
            for actor, total_count, up_votes, down_votes in actor_rows
        ],
        "topics": topics,
        "ranking_applied": False,
        "recommendations": [
            "تا رسیدن به حداقل نمونه، ranking و threshold خودکار تغییر نکند.",
            "سیگنال موضوعات با نمونه کافی برای بررسی مدیر اولویت‌بندی شود.",
        ],
    }


async def apply_feedback_ranking(*, idempotency_key: str | None = None, min_samples: int = 3, max_adjustment: float = 0.05) -> dict[str, object]:
    """Apply the approved, bounded feedback signal to topic scores.

    Only topics with at least ``min_samples`` distinct feedback records are
    changed. The adjustment is bounded and the original score is retained in
    the returned audit payload, making the operation reviewable and safe to
    rerun with a new explicit idempotency key.
    """
    key = idempotency_key or f"feedback-ranking:{_utcnow().date().isoformat()}"
    job_id, claim = await _claim_job(key, "feedback_ranking")
    if job_id is None:
        return {"status": "duplicate", "idempotency_key": key, "existing_status": claim}
    changed: list[dict[str, object]] = []
    score_changes: list[dict[str, object]] = []
    try:
        async with SessionLocal() as session:
            rows = (await session.execute(
                select(
                    Topic.id,
                    Topic.name,
                    func.count(distinct(Feedback.id)).label("samples"),
                    func.sum(case((Feedback.value == "up", 1), else_=0)).label("up_votes"),
                    func.sum(case((Feedback.value == "down", 1), else_=0)).label("down_votes"),
                )
                .join(ArticleTopic, ArticleTopic.topic_id == Topic.id)
                .join(ArticleAnalysis, ArticleAnalysis.article_id == ArticleTopic.article_id)
                .join(Feedback, Feedback.analysis_id == ArticleAnalysis.id)
                .group_by(Topic.id, Topic.name)
            )).all()
            for topic_id, topic_name, samples, up_votes, down_votes in rows:
                samples = int(samples or 0)
                if samples < min_samples:
                    continue
                up_votes, down_votes = int(up_votes or 0), int(down_votes or 0)
                adjustment = max(-max_adjustment, min(max_adjustment, ((up_votes - down_votes) / samples) * max_adjustment))
                scores = (await session.execute(select(ArticleTopic.id, ArticleTopic.combined_score).where(ArticleTopic.topic_id == topic_id))).all()
                for score_id, before in scores:
                    after = max(0.0, min(1.0, float(before) + adjustment))
                    await session.execute(update(ArticleTopic).where(ArticleTopic.id == score_id).values(combined_score=after))
                    score_changes.append({"score_id": str(score_id), "before": float(before), "after": after})
                changed.append({"topic_id": str(topic_id), "topic": topic_name, "samples": samples, "up": up_votes, "down": down_votes, "adjustment": round(adjustment, 6), "scores_changed": len(scores)})
            await session.commit()
        result = {"status": "applied", "idempotency_key": key, "min_samples": min_samples, "max_adjustment": max_adjustment, "topics_changed": len(changed), "changes": changed, "score_changes": score_changes}
        await _finish_job(job_id, status="succeeded", result=result)
        return result
    except Exception as exc:
        await _finish_job(job_id, status="failed", result={}, error=f"{type(exc).__name__}: {exc}")
        raise


async def list_publications(*, status: str | None = None, limit: int = 50, assistant_id: uuid.UUID | None = None, query: str | None = None) -> list[dict[str, object]]:
    statement = (
        select(Publication, ArticleAnalysis, NormalizedArticle, SourceItem, Source)
        .join(ArticleAnalysis, ArticleAnalysis.id == Publication.analysis_id)
        .join(NormalizedArticle, NormalizedArticle.id == ArticleAnalysis.article_id)
        .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
        .join(Source, Source.id == SourceItem.source_id)
        .order_by(Publication.created_at.desc())
        .limit(limit)
    )
    if status:
        statement = statement.where(Publication.status == status)
    if assistant_id is not None:
        statement = statement.where(Publication.assistant_id == assistant_id)
    if query and query.strip():
        needle = f"%{query.strip()}%"
        statement = statement.where(
            or_(
                Publication.message_text.ilike(needle),
                Source.name.ilike(needle),
                Source.source_key.ilike(needle),
            )
        )
    async with SessionLocal() as session:
        rows = (await session.execute(statement)).all()
        decisions = await _article_decisions(session, [r[2] for r in rows], get_settings())
    return [
        {
            "id": str(publication.id),
            "analysis_id": str(publication.analysis_id),
            "status": publication.status,
            "message_id": publication.message_id,
            "message_text": publication.message_text,
            "created_at": publication.created_at,
            "published_at": publication.published_at,
            # Keep the source article date separate from the Telegram delivery
            # timestamp.  The review queue needs both values so operators can
            # distinguish news freshness from channel publication time.
            "article_published_at": _article.published_at,
            "error_message": publication.error_message,
            "source_name": source.name,
            "source_key": source.source_key,
            **decisions[_article.id],
            "analysis_ready": _analysis.status == "succeeded",
            "can_approve": decisions[_article.id]["can_approve"] and _analysis.status == "succeeded" and publication.status == "preview",
            "approval_state": ((publication.audit or {}).get("approval") or {}).get("state", "unmanaged"),
            "approval": (publication.audit or {}).get("approval") or None,
            "bulk_label": (publication.audit or {}).get("label"),
        }
        for publication, _analysis, _article, _item, source in rows
    ]


async def list_relevance_assessments(*, assistant_id: uuid.UUID, limit: int = 200, offset: int = 0, state: str | None = None, query: str | None = None) -> dict[str, object]:
    """Paginate a disclosed recent 500-item window using current AI decisions.

    Search is performed before the window is bounded. Decision filters never
    reuse historical selected flags. This GET cannot create paid reports.
    """
    settings = await settings_for_assistant(get_settings(), assistant_id)
    async with SessionLocal() as session:
        statement = (select(NormalizedArticle, Source.name)
                .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
                .join(Source, Source.id == SourceItem.source_id)
                .where(NormalizedArticle.assistant_id == assistant_id, Source.assistant_id == assistant_id,
                       _freshness_condition(NormalizedArticle.published_at, settings)))
        if query and query.strip():
            term = "%" + query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            statement = statement.where(or_(NormalizedArticle.title.ilike(term, escape="\\"), Source.name.ilike(term, escape="\\")))
        available = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
        rows = (await session.execute(statement.order_by(NormalizedArticle.extracted_at.desc(), NormalizedArticle.id).limit(500))).all()
        decisions = await _article_decisions(session, [r[0] for r in rows], settings)
    counts = {state: sum(d["relevance_state"] == state for d in decisions.values()) for state in ("selected", "borderline", "rejected", "pending")}
    filtered = [r for r in rows if not state or decisions[r[0].id]["relevance_state"] == state]
    page_rows = filtered[max(0, offset):max(0, offset) + min(max(limit, 1), 200)]
    return {"revision": SCORER_REVISION, "counts": counts, "counts_scope": "recent_search_window", "window_limit": 500,
            "window_capped": available > 500, "total_available": available, "total": len(filtered),
            "offset": offset, "limit": limit, "no_external_request": True, "articles": [
        {"id": str(article.id), "title": article.title, "source_name": source_name,
         "source_url": article.canonical_url, "published_at": article.published_at, **decisions[article.id]} for article, source_name in page_rows]}


async def generate_weekly_report(*, now: datetime | None = None, assistant_id: uuid.UUID | None = None) -> dict[str, object]:
    assistant_id = assistant_id or DEFAULT_ASSISTANT_ID
    now = now or _utcnow()
    period_start = now - timedelta(days=7)
    async with SessionLocal() as session:
        articles = (await session.scalars(select(NormalizedArticle).join(ArticleAnalysis, ArticleAnalysis.article_id == NormalizedArticle.id).where(
            NormalizedArticle.assistant_id == assistant_id, ArticleAnalysis.assistant_id == assistant_id,
            ArticleAnalysis.status == "succeeded", ArticleAnalysis.created_at >= period_start, ArticleAnalysis.created_at < now,
        ))).all()
        decisions = await _article_decisions(session, articles, await settings_for_assistant(get_settings(), assistant_id))
        names = {t.topic_key: t.name for t in (await session.scalars(select(Topic).where(Topic.assistant_id == assistant_id, Topic.enabled.is_(True)))).all()}
        trend_counts: dict[str, int] = {}
        for decision in decisions.values():
            key = decision.get("relevance_topic")
            if decision["publishable"] and key in names:
                name = names[key]
                trend_counts[name] = trend_counts.get(name, 0) + 1
        topic_rows = sorted(trend_counts.items(), key=lambda row: (-row[1], row[0]))
        profile = await _profile_for_assistant(session, assistant_id)
        analysis_count = (
            await session.execute(
                select(func.count(ArticleAnalysis.id)).where(
                    ArticleAnalysis.created_at >= period_start,
                    ArticleAnalysis.created_at < now,
                    ArticleAnalysis.status == "succeeded",
                )
                .where(ArticleAnalysis.assistant_id == assistant_id if assistant_id is not None else true())
            )
        ).scalar_one()
        feedback_rows = (
            await session.execute(
                select(Feedback.value, func.count(Feedback.id))
                .where(Feedback.created_at >= period_start, Feedback.created_at < now)
                .where(Feedback.assistant_id == assistant_id if assistant_id is not None else true())
                .group_by(Feedback.value)
            )
        ).all()
        trends = [{"topic": name, "articles": count} for name, count in topic_rows]
        competitor_mentions: list[dict[str, object]] = []
        if profile:
            for competitor in profile.competitors:
                mentions = (
                    await session.execute(
                        select(func.count(NormalizedArticle.id)).where(
                            NormalizedArticle.extracted_at >= period_start,
                            NormalizedArticle.extracted_at < now,
                            NormalizedArticle.normalized_text.ilike(f"%{competitor}%"),
                        )
                        .where(NormalizedArticle.assistant_id == assistant_id if assistant_id is not None else true())
                    )
                ).scalar_one()
                competitor_mentions.append(
                    {"competitor": competitor, "mentions": int(mentions)}
                )
        feedback_metrics = {value: count for value, count in feedback_rows}
        digest_lines = [
            "گزارش هفتگی پایش بازار",
            f"تعداد تحلیل‌ها: {analysis_count}",
            "موضوعات پرتکرار: "
            + ("، ".join(f"{name} ({count})" for name, count in topic_rows) or "داده کافی نیست"),
            "بازخورد: "
            + ("، ".join(f"{key}={value}" for key, value in feedback_metrics.items()) or "ثبت نشده"),
        ]
        report_id = uuid.uuid4()
        statement = (
            postgresql_insert(WeeklyReport)
            .values(
                id=report_id,
                assistant_id=assistant_id,
                period_start=period_start,
                period_end=now,
                status="preview",
                digest="\n".join(digest_lines),
                trends=trends,
                competitor_mentions=competitor_mentions,
                metrics={"analyses": analysis_count, "feedback": feedback_metrics, "trend_basis": "current_ai_evidence"},
            )
            .on_conflict_do_nothing(
                index_elements=[WeeklyReport.assistant_id, WeeklyReport.period_start, WeeklyReport.period_end]
            )
            .returning(WeeklyReport.id)
        )
        inserted = (await session.execute(statement)).scalar_one_or_none()
        if inserted is None:
            inserted = await session.scalar(select(WeeklyReport.id).where(WeeklyReport.assistant_id == assistant_id, WeeklyReport.period_start == period_start, WeeklyReport.period_end == now))
        await session.commit()
    return {
        "report_id": str(inserted or report_id),
        "status": "preview",
        "analyses": analysis_count,
        "trends": trends,
        "competitor_mentions": competitor_mentions,
    }


async def apply_retention(settings: Settings) -> dict[str, object]:
    """Enforce raw-HTML expiry and each workspace's article retention.

    Every workspace uses its own privacy ``retention_days`` when one was
    saved, otherwise the deployment ``normalized_retention_days``.  Deleting
    an article cascades to its topic scores, cluster memberships, analyses,
    publications and feedback.  The originating source item is kept only as
    a content-free tombstone: its fingerprint must survive so ingestion does
    not rediscover and republish the same item, while title, URL and
    excerpt are erased.  Clusters left without members are removed too.
    """
    now = _utcnow()
    raw_cutoff = now - timedelta(days=settings.raw_html_retention_days)
    async with SessionLocal() as session:
        raw_result = await session.execute(
            update(NormalizedArticle)
            .where(
                NormalizedArticle.extracted_at < raw_cutoff,
                NormalizedArticle.raw_html.is_not(None),
            )
            .values(raw_html=None)
        )
        await session.commit()
        workspaces = (await session.execute(select(AssistantWorkspace.id, AssistantWorkspace.config))).all()
    totals = {"normalized_articles_deleted": 0, "source_items_purged": 0, "clusters_deleted": 0}
    per_workspace: list[dict[str, object]] = []
    for assistant_id, config in workspaces:
        days, policy_source = effective_retention_days(config)
        cutoff = now - timedelta(days=days)
        # One transaction per workspace keeps locks short and isolates a
        # failure to the workspace that caused it.
        async with SessionLocal() as session:
            deleted = await session.execute(
                delete(NormalizedArticle).where(
                    NormalizedArticle.assistant_id == assistant_id,
                    NormalizedArticle.extracted_at < cutoff,
                )
            )
            purged = await session.execute(
                update(SourceItem)
                .where(
                    SourceItem.assistant_id == assistant_id,
                    SourceItem.discovered_at < cutoff,
                    ~SourceItem.raw_metadata.has_key("retention_purged_at"),
                    ~exists().where(NormalizedArticle.source_item_id == SourceItem.id),
                )
                .values(title="", url="", excerpt="", raw_metadata={"retention_purged_at": now.isoformat()})
            )
            clusters = await session.execute(
                delete(EventCluster).where(
                    EventCluster.assistant_id == assistant_id,
                    EventCluster.updated_at < cutoff,
                    ~exists().where(ClusterMember.cluster_id == EventCluster.id),
                )
            )
            await session.commit()
        counts = {
            "normalized_articles_deleted": int(deleted.rowcount or 0),
            "source_items_purged": int(purged.rowcount or 0),
            "clusters_deleted": int(clusters.rowcount or 0),
        }
        for key, value in counts.items():
            totals[key] += value
        if any(counts.values()):
            per_workspace.append({"assistant_id": str(assistant_id), "retention_days": days, "policy": policy_source, **counts})
    return {
        "raw_html_cleared": int(raw_result.rowcount or 0),
        **totals,
        "workspaces": per_workspace,
    }


async def pipeline_metrics(*, assistant_id: uuid.UUID | None = None) -> dict[str, object]:
    active_settings = await settings_for_assistant(get_settings(), assistant_id)
    local_now = _utcnow().astimezone(ZoneInfo(active_settings.timezone))
    today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    async with SessionLocal() as session:
        counts: dict[str, int] = {}
        for label, model in (
            ("source_items", SourceItem),
            ("normalized_articles", NormalizedArticle),
            ("selected_topic_scores", ArticleTopic),
            ("clusters", EventCluster),
            ("analyses", ArticleAnalysis),
            ("publications", Publication),
            ("feedback", Feedback),
        ):
            statement = select(func.count(model.id))
            if model is ArticleTopic:
                statement = statement.where(ArticleTopic.selected.is_(True))
            if assistant_id is not None:
                statement = statement.where(model.assistant_id == assistant_id)
            counts[label] = int((await session.execute(statement)).scalar_one())
        active_sources_statement = select(func.count(Source.id)).where(Source.enabled.is_(True))
        if assistant_id is not None:
            active_sources_statement = active_sources_statement.where(Source.assistant_id == assistant_id)
        counts["active_sources"] = int((await session.execute(active_sources_statement)).scalar_one())
        daily_statements = (
            (
                "analyses_today",
                ArticleAnalysis,
                select(func.count(ArticleAnalysis.id)).where(
                    ArticleAnalysis.created_at >= today_start,
                    ArticleAnalysis.status.in_(("succeeded", "fallback")),
                ),
            ),
            (
                "published_today",
                Publication,
                select(func.count(Publication.id)).where(
                    Publication.status.in_(("published", "edited")),
                    func.coalesce(Publication.published_at, Publication.created_at) >= today_start,
                ),
            ),
            (
                "feedback_today",
                Feedback,
                select(func.count(Feedback.id)).where(Feedback.created_at >= today_start),
            ),
            (
                "pending_previews",
                Publication,
                select(func.count(Publication.id)).where(Publication.status == "preview"),
            ),
        )
        for label, model, statement in daily_statements:
            if assistant_id is not None:
                statement = statement.where(model.assistant_id == assistant_id)
            counts[label] = int((await session.execute(statement)).scalar_one())
        # Compatibility for older clients; this now means actual deliveries,
        # not preview/failed publication rows created today.
        counts["publications_today"] = counts["published_today"]
        source_health: dict[str, int] = {
            str(status): int(count)
            for status, count in (
                await session.execute(
                    select(Source.health_status, func.count(Source.id)).where(
                        Source.assistant_id == assistant_id if assistant_id is not None else true()
                    ).group_by(
                        Source.health_status
                    )
                )
            ).all()
        }
        publication_status: dict[str, int] = {
            str(status): int(count)
            for status, count in (
                await session.execute(
                    select(Publication.status, func.count(Publication.id)).where(
                        Publication.assistant_id == assistant_id if assistant_id is not None else true()
                    ).group_by(
                        Publication.status
                    )
                )
            ).all()
        }
        model_requests, input_chars = await _model_budget(active_settings, assistant_id=assistant_id)
        if assistant_id is not None:
            workspace = await session.get(AssistantWorkspace, assistant_id)
            topics = (await session.scalars(select(Topic).where(Topic.assistant_id == assistant_id, Topic.enabled.is_(True)).order_by(Topic.topic_key))).all()
            profile = await _profile_for_assistant(session, assistant_id)
            current_hash = _relevance_hash(active_settings, workspace, topics, profile)
            counts["pending_ai_articles"] = int(await session.scalar(select(func.count(NormalizedArticle.id)).where(
                NormalizedArticle.assistant_id == assistant_id,
                NormalizedArticle.extraction_status.in_(["complete", "partial"]),
                _freshness_condition(NormalizedArticle.published_at, active_settings),
                true() if not topics else select(func.count(ArticleTopic.id)).where(
                    ArticleTopic.article_id == NormalizedArticle.id,
                    ArticleTopic.ai_score.is_not(None), ArticleTopic.context_hash == current_hash,
                    ArticleTopic.topic_id.in_([t.id for t in topics]),
                    ArticleTopic.scored_at >= NormalizedArticle.extracted_at,
                ).correlate(NormalizedArticle).scalar_subquery() < len(topics),
            )) or 0)
            counts["relevance_model_requests_today"] = int(await session.scalar(select(func.count(JobRun.id)).where(
                JobRun.assistant_id == assistant_id, JobRun.job_type == "relevance_model",
                JobRun.created_at >= _local_day_start_utc(_utcnow(), active_settings.timezone),
            )) or 0)
    return {
        **counts,
        "source_health": source_health,
        "publication_status": publication_status,
        "daily_model_requests": model_requests,
        "daily_model_input_chars": input_chars,
    }


async def run_pipeline(
    *,
    source_keys: list[str] | None = None,
    force_ingestion: bool = False,
    publish: bool | None = None,
    max_candidates: int | None = None,
    idempotency_key: str | None = None,
    assistant_id: uuid.UUID | None = None,
    publish_limit: int | None = None,
) -> dict[str, object]:
    # A pipeline invocation without an explicit workspace is legacy shorthand
    # for the stable default workspace.  Never let a nullable scope propagate
    # into operational records such as EventCluster.assistant_id.
    assistant_id = assistant_id or DEFAULT_ASSISTANT_ID
    base_settings = get_settings()
    settings = await settings_for_assistant(base_settings, assistant_id)
    requested_limit = max_candidates or settings.pipeline_max_candidates_per_run
    already_processed_today = await _daily_processing_count(assistant_id, settings.timezone)
    processing_limit = min(
        requested_limit,
        max(0, settings.processing_max_items_per_day - already_processed_today),
    )
    idempotency_key = idempotency_key or f"manual:{uuid.uuid4()}"
    job_id, claim_status = await _claim_job(
        idempotency_key,
        "market_pipeline",
        assistant_id=assistant_id,
    )
    if job_id is None:
        return {
            "status": "duplicate",
            "idempotency_key": idempotency_key,
            "existing_status": claim_status,
        }
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    lock_name = pipeline_lock_key(assistant_id, settings=settings)
    lock_token = uuid.uuid4().hex
    acquired = False
    result: dict[str, object] = {}
    try:
        acquired = bool(
            await redis.set(lock_name, lock_token, nx=True, ex=max(600, settings.fetch_lock_ttl_seconds))
        )
        if not acquired:
            result = {"status": "skipped_locked", "idempotency_key": idempotency_key}
            await _finish_job(job_id, status="cancelled", result=result)
            return result
        # Keep the legacy call path byte-for-byte compatible for an unmodified
        # workspace; configured workspaces receive the effective per-assistant
        # limits so collection and analysis never fall back to global values.
        if settings == base_settings:
            ingestion = await run_ingestion(source_keys, force=force_ingestion, assistant_id=assistant_id)
        else:
            ingestion = await run_ingestion(
                source_keys,
                force=force_ingestion,
                assistant_id=assistant_id,
                settings=settings,
            )
        extraction = await extract_pending_articles(settings, limit=processing_limit, assistant_id=assistant_id) if processing_limit else {"attempted": 0, "complete": 0, "partial": 0, "failed": 0, "daily_processing_cap_reached": True}
        # The collection/extraction quota must not permanently freeze the
        # already-collected backlog. AI and publication have their own caps.
        analysis_limit = min(requested_limit, settings.pipeline_max_candidates_per_run)
        relevance = await score_pending_articles(settings, limit=analysis_limit, assistant_id=assistant_id)
        clustering = await cluster_pending_articles(settings, limit=analysis_limit, assistant_id=assistant_id)
        analysis = await analyze_pending_articles(settings, limit=analysis_limit, assistant_id=assistant_id)
        previews = await create_publication_previews(settings, limit=analysis_limit, assistant_id=assistant_id)
        should_publish = (
            bool(publish) if publish is not None else settings.auto_publish and not settings.pilot_mode
        )
        if should_publish:
            # An explicit publish_limit (manual "publish one now") sends the
            # newest eligible items only; the scheduler keeps oldest-first.
            delivery = await publish_ready_previews(
                settings.model_copy(update={"auto_publish": True, "pilot_mode": False}),
                limit=min(publish_limit, settings.max_items_per_run) if publish_limit else settings.max_items_per_run,
                assistant_id=assistant_id,
                newest_first=publish_limit is not None,
            )
        else:
            delivery = {"published": 0, "status": "dry_run_gate"}
        result = {
            "status": "completed",
            "version": settings.version,
            "idempotency_key": idempotency_key,
            "ingestion": ingestion,
            "extraction": extraction,
            "relevance": relevance,
            "clustering": clustering,
            "analysis": analysis,
            "previews": previews,
            "processing_budget": {
                "requested": requested_limit,
                "processed_before_run": already_processed_today,
                "allowed_this_run": processing_limit,
                "daily_limit": settings.processing_max_items_per_day,
                "publication_limit_per_run": settings.max_items_per_run,
            },
            "delivery": delivery,
        }
        await _finish_job(job_id, status="succeeded", result=result)
        return result
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"[:2000]
        result = {"status": "failed", "idempotency_key": idempotency_key, "error": error}
        await _finish_job(job_id, status="failed", result=result, error=error)
        raise
    finally:
        if acquired:
            try:
                await redis.eval(
                    "if redis.call('get', KEYS[1]) == ARGV[1] then "
                    "return redis.call('del', KEYS[1]) else return 0 end",
                    1,
                    lock_name,
                    lock_token,
                )
            except RedisError:
                pass
        await redis.aclose()
