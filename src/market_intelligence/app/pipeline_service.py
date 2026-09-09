from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import re
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import and_, case, delete, distinct, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from app.article_extraction import ArticleDocument, ArticleFetcher
from app.config import Settings, get_settings
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
)
from app.openai_client import (
    OpenAIClient,
    StructuredAnalysis,
    calibrated_semantic_score,
    cosine_similarity,
    sanitize_untrusted_source,
)
from app.queue_names import pipeline_lock_key
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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _render_publication_message(
    *,
    analysis: ArticleAnalysis,
    article: NormalizedArticle,
    source: Source,
    business_name: str = "داتین",
    template_blocks: list[dict[str, object]] | None = None,
) -> str:
    """Render one Telegram message from canonical article data.

    The source title is deliberately the only title passed to the renderer.
    Model-generated headlines remain useful for analysis, but must never
    replace the title shown to readers in a published message.
    """
    return render_analysis_message(
        headline=article.title,
        summary=analysis.news_summary,
        business_connection=analysis.business_connection,
        opportunity=analysis.opportunity,
        risk=analysis.risk,
        action=analysis.suggested_action,
        confidence=analysis.confidence,
        source_name=source.name,
        source_url=article.canonical_url,
        published_at=article.published_at.isoformat() if article.published_at else None,
        incomplete=article.extraction_status == "partial",
        business_name=business_name or "داتین",
        template_blocks=template_blocks,
    )


def _template_has_image(blocks: list[dict[str, object]] | None) -> bool:
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
        active_profile = None
        if isinstance(assistant, AssistantWorkspace):
            selected_id = (assistant.config or {}).get("active_business_id")
            profile_query = select(BusinessProfile).where(BusinessProfile.assistant_id == assistant_id)
            if selected_id:
                profile_query = profile_query.where(BusinessProfile.id == int(selected_id))
            active_profile = (await session.execute(profile_query.order_by(BusinessProfile.id))).scalars().first()
    if assistant is None:
        return settings
    telegram = (assistant.config or {}).get("telegram") or {}
    runtime = (assistant.config or {}).get("runtime") or {}
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
    # The message renderer must use the active workspace's business name; the
    # deployment default is only a backwards-compatible fallback for the
    # legacy workspace.
    if active_profile is not None and str(active_profile.business_name).strip():
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


def _freshness_condition(column, settings: Settings):
    """Accept undated feed items, but reject dated items older than the window."""
    cutoff = _utcnow() - timedelta(days=settings.freshness_window_days)
    return or_(column.is_(None), column >= cutoff)


async def _profile_for_assistant(session, assistant_id: uuid.UUID | None) -> BusinessProfile | None:
    statement = select(BusinessProfile).order_by(BusinessProfile.id)
    if assistant_id is not None:
        statement = statement.where(BusinessProfile.assistant_id == assistant_id)
        assistant = await session.get(AssistantWorkspace, assistant_id)
        if assistant is not None:
            selected = (assistant.config or {}).get("active_business_id")
            if selected:
                selected_statement = select(BusinessProfile).where(
                    BusinessProfile.id == int(selected), BusinessProfile.assistant_id == assistant_id
                )
                chosen = (await session.execute(selected_statement)).scalar_one_or_none()
                if chosen is not None:
                    return chosen
    return (await session.execute(statement)).scalars().first()


def _general_market_profile(assistant: AssistantWorkspace | None) -> SimpleNamespace:
    """Return a read-only profile-shaped context for business-free workspaces.

    The analysis contract expects the same fields whether a business profile
    exists or not.  A small in-memory namespace keeps the pipeline path
    uniform without inserting a fake profile into the database or leaking the
    legacy deployment business into a new assistant.
    """
    name = str(getattr(assistant, "name", "") or "").strip() or "این دستیار"
    return SimpleNamespace(
        business_name=name,
        description="تمرکز بر پایش عمومی بازار و اخبار موضوعات انتخاب‌شده.",
        products_services="",
        target_customers="",
        markets="",
        revenue_model="",
        strategic_goals="",
        competitors=[],
        sensitivities=[],
        output_language="fa",
        output_tone="کوتاه، تحلیلی و اجرایی",
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
    result: dict[str, object],
    error: str | None = None,
) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(JobRun)
            .where(JobRun.id == job_id)
            .values(
                status=status,
                finished_at=_utcnow(),
                result=result,
                error_message=error,
            )
        )
        await session.commit()


async def extract_pending_articles(
    settings: Settings,
    *,
    limit: int,
    assistant_id: uuid.UUID | None = None,
) -> dict[str, object]:
    async with SessionLocal() as session:
        sources = (
            await session.execute(
                select(Source).where(Source.enabled.is_(True)).where(Source.assistant_id == assistant_id if assistant_id else True).order_by(
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
                        SourceItem.assistant_id == assistant_id if assistant_id else True,
                        _freshness_condition(SourceItem.published_at, settings),
                        NormalizedArticle.id.is_(None),
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
                    SourceItem.assistant_id == assistant_id if assistant_id else True,
                    _freshness_condition(SourceItem.published_at, settings),
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


async def score_pending_articles(
    settings: Settings,
    *,
    limit: int,
    rescore: bool = False,
    assistant_id: uuid.UUID | None = None,
) -> dict[str, object]:
    async with SessionLocal() as session:
        topics = (
            await session.execute(
                select(Topic).where(Topic.enabled.is_(True)).where(Topic.assistant_id == assistant_id if assistant_id else True).order_by(Topic.topic_key)
            )
        ).scalars().all()
        article_statement = (
            select(NormalizedArticle)
            .where(
                NormalizedArticle.extraction_status.in_(["complete", "partial"]),
                NormalizedArticle.assistant_id == assistant_id if assistant_id else True,
                _freshness_condition(NormalizedArticle.published_at, settings),
            )
            .order_by(NormalizedArticle.extracted_at.desc())
            .limit(limit)
        )
        if not rescore:
            article_statement = (
                article_statement
                .outerjoin(
                    ArticleTopic,
                    ArticleTopic.article_id == NormalizedArticle.id,
                )
                .where(ArticleTopic.id.is_(None))
            )
        articles = (await session.execute(article_statement)).scalars().all()
    if not topics or not articles:
        return {"articles": len(articles), "scores": 0, "semantic": "not_needed"}

    semantic: dict[tuple[uuid.UUID, uuid.UUID], float] = {}
    semantic_status = "disabled"
    client = OpenAIClient(settings)
    if client.configured:
        topic_texts = [f"{topic.name}: {topic.definition}" for topic in topics]
        article_texts = [
            f"{article.title}\n{article.normalized_text[:6000]}" for article in articles
        ]
        try:
            vectors = await client.embeddings(topic_texts + article_texts)
            topic_vectors = vectors[: len(topics)]
            article_vectors = vectors[len(topics) :]
            for article, article_vector in zip(articles, article_vectors, strict=True):
                for topic, topic_vector in zip(topics, topic_vectors, strict=True):
                    semantic[(article.id, topic.id)] = calibrated_semantic_score(
                        cosine_similarity(article_vector, topic_vector)
                    )
            semantic_status = "succeeded"
        except Exception as exc:
            semantic_status = f"fallback:{type(exc).__name__}"

    rows: list[dict[str, object]] = []
    selected_articles: set[uuid.UUID] = set()
    for article in articles:
        for topic in topics:
            lexical, positive, negative = lexical_topic_score(
                title=article.title,
                text=article.normalized_text,
                positive_terms=list(topic.positive_terms),
                negative_terms=list(topic.negative_terms),
            )
            score = combine_topic_score(
                lexical=lexical,
                semantic=semantic.get((article.id, topic.id)),
                threshold=max(topic.threshold, settings.relevance_threshold),
                positive_matches=positive,
                negative_matches=negative,
            )
            selected_articles.update([article.id] if score.selected else [])
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "assistant_id": article.assistant_id,
                    "article_id": article.id,
                    "topic_id": topic.id,
                    "lexical_score": score.lexical_score,
                    "semantic_score": score.semantic_score,
                    "combined_score": score.combined_score,
                    "matched_positive": list(score.positive_matches),
                    "matched_negative": list(score.negative_matches),
                    "explanation": score.explanation,
                    "selected": score.selected,
                }
            )
    async with SessionLocal() as session:
        insert_statement = postgresql_insert(ArticleTopic).values(rows)
        if rescore:
            excluded = insert_statement.excluded
            insert_statement = insert_statement.on_conflict_do_update(
                index_elements=[ArticleTopic.article_id, ArticleTopic.topic_id],
                set_={
                    "lexical_score": excluded.lexical_score,
                    "semantic_score": excluded.semantic_score,
                    "combined_score": excluded.combined_score,
                    "matched_positive": excluded.matched_positive,
                    "matched_negative": excluded.matched_negative,
                    "explanation": excluded.explanation,
                    "selected": excluded.selected,
                    "scored_at": _utcnow(),
                },
            )
        else:
            insert_statement = insert_statement.on_conflict_do_nothing(
                index_elements=[ArticleTopic.article_id, ArticleTopic.topic_id]
            )
        await session.execute(insert_statement)
        invalidated = 0
        if rescore:
            valid_articles = select(ArticleTopic.article_id).where(
                ArticleTopic.selected.is_(True)
            )
            invalid_analysis_ids = select(ArticleAnalysis.id).where(
                ArticleAnalysis.article_id.not_in(valid_articles)
            )
            invalidation = await session.execute(
                update(Publication)
                .where(
                    Publication.analysis_id.in_(invalid_analysis_ids),
                    Publication.status == "preview",
                )
                .values(
                    status="failed",
                    error_message="invalidated by relevance scorer revision",
                    updated_at=_utcnow(),
                )
            )
            invalidated = int(invalidation.rowcount or 0)
        await session.commit()
    return {
        "articles": len(articles),
        "scores": len(rows),
        "selected_articles": len(selected_articles),
        "semantic": semantic_status,
        "rescore": rescore,
        "previews_invalidated": invalidated,
    }


async def rescore_existing_articles(*, limit: int = 1000) -> dict[str, object]:
    return await score_pending_articles(get_settings(), limit=limit, rescore=True)


async def cluster_pending_articles(settings: Settings, *, limit: int, assistant_id: uuid.UUID | None = None) -> dict[str, int]:
    async with SessionLocal() as session:
        articles = (
            await session.execute(
                select(NormalizedArticle)
                .join(ArticleTopic, ArticleTopic.article_id == NormalizedArticle.id)
                .outerjoin(ClusterMember, ClusterMember.article_id == NormalizedArticle.id)
                .where(ArticleTopic.selected.is_(True), ClusterMember.id.is_(None), NormalizedArticle.assistant_id == assistant_id if assistant_id else True, _freshness_condition(NormalizedArticle.published_at, settings))
                .group_by(NormalizedArticle.id)
                .order_by(NormalizedArticle.extracted_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        existing = (
            await session.execute(
                select(EventCluster, NormalizedArticle)
                .join(
                    NormalizedArticle,
                    NormalizedArticle.id == EventCluster.representative_article_id,
                )
                .where(EventCluster.updated_at >= _utcnow() - timedelta(days=14), EventCluster.assistant_id == assistant_id if assistant_id else True)
            )
        ).all()

        new_clusters = 0
        joined_clusters = 0
        for article in articles:
            best_cluster: EventCluster | None = None
            best_similarity = 0.0
            for candidate, representative in existing:
                similarity = jaccard_similarity(article.title, representative.title)
                if similarity > best_similarity:
                    best_cluster = candidate
                    best_similarity = similarity
            if best_cluster is None or best_similarity < settings.clustering_threshold:
                best_cluster = EventCluster(
                    assistant_id=article.assistant_id,
                    cluster_key=cluster_key(article.title),
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


def _profile_payload(profile: BusinessProfile) -> dict[str, object]:
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
    profile: BusinessProfile,
    topic_rows: list[tuple[Topic, ArticleTopic]],
    source: Source,
    reason: str,
) -> dict[str, object]:
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
    connection = (
        f"این خبر به‌دلیل ارتباط با {topic_names or 'موضوعات مالی'} می‌تواند برای "
        f"{profile.business_name} و مشتریان بانکی آن قابل بررسی باشد."
    )
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


async def regenerate_fallback_analyses(*, limit: int = 200) -> dict[str, int]:
    async with SessionLocal() as session:
        profile = await session.get(BusinessProfile, 1)
        if profile is None:
            raise RuntimeError("approved business profile is missing")
        rows = (
            await session.execute(
                select(ArticleAnalysis, NormalizedArticle, SourceItem, Source, Publication)
                .join(NormalizedArticle, NormalizedArticle.id == ArticleAnalysis.article_id)
                .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
                .join(Source, Source.id == SourceItem.source_id)
                .outerjoin(Publication, Publication.analysis_id == ArticleAnalysis.id)
                .where(ArticleAnalysis.status == "fallback")
                .order_by(ArticleAnalysis.created_at.desc())
                .limit(limit)
            )
        ).all()
        updated = 0
        preview_updated = 0
        for analysis, article, item, source, publication in rows:
            topic_rows = (
                await session.execute(
                    select(Topic, ArticleTopic)
                    .join(ArticleTopic, ArticleTopic.topic_id == Topic.id)
                    .where(ArticleTopic.article_id == article.id)
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
            analysis.confidence = float(payload["confidence"])
            analysis.facts = payload["facts"]
            analysis.inferences = payload["inferences"]
            analysis.citations = payload["citations"]
            analysis.topic_scores = payload["topic_scores"]
            analysis.error_message = str(payload["error_message"])
            updated += 1
            if publication is not None and publication.status == "preview":
                publication.message_text = _render_publication_message(
                    analysis=analysis,
                    article=article,
                    source=source,
                    business_name=profile.business_name,
                )
                publication.updated_at = _utcnow()
                preview_updated += 1
        await session.commit()
    return {"analyses_updated": updated, "previews_updated": preview_updated}


async def _model_budget(settings: Settings) -> tuple[int, int]:
    day_start = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    async with SessionLocal() as session:
        count, chars = (
            await session.execute(
                select(
                    func.count(ArticleAnalysis.id),
                    func.coalesce(func.sum(ArticleAnalysis.input_chars), 0),
                ).where(
                    ArticleAnalysis.created_at >= day_start,
                    ArticleAnalysis.status == "succeeded",
                )
            )
        ).one()
    return int(count), int(chars)


def _local_day_start_utc(now: datetime, timezone_name: str | None) -> datetime:
    """Return the UTC instant of the current calendar day in a workspace TZ."""
    try:
        zone = ZoneInfo(timezone_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone = timezone.utc
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
) -> dict[str, object]:
    model_payload = result.payload
    inferences = list(model_payload["inferences"])
    source_safety = model_payload.get("_source_content_safety")
    if isinstance(source_safety, dict) and source_safety.get("detected"):
        inferences.append(
            "یادداشت ایمنی منبع: الگوهای دستوری مشکوک از محتوای خارجی حذف و برای تحلیل نادیده گرفته شد."
        )
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


async def analyze_pending_articles(settings: Settings, *, limit: int, assistant_id: uuid.UUID | None = None) -> dict[str, object]:
    daily_count, daily_chars = await _model_budget(settings)
    available_requests = max(0, settings.model_daily_request_cap - daily_count)
    request_limit = min(limit, settings.model_max_requests_per_run, available_requests)
    async with SessionLocal() as session:
        # Analyse both publishable scores and the narrow manual-review band.
        # The latter deliberately does not require an EventCluster: clustering
        # remains reserved for items that already passed the real threshold.
        reviewable_topic = exists(
            select(ArticleTopic.id)
            .join(Topic, Topic.id == ArticleTopic.topic_id)
            .where(
                ArticleTopic.article_id == NormalizedArticle.id,
                or_(
                    ArticleTopic.selected.is_(True),
                    ArticleTopic.combined_score
                    >= func.greatest(Topic.threshold, settings.relevance_threshold)
                    - REVIEW_MARGIN,
                ),
            )
        )
        rows = (
            await session.execute(
                select(NormalizedArticle, SourceItem, Source)
                .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
                .join(Source, Source.id == SourceItem.source_id)
                .outerjoin(
                    ArticleAnalysis,
                    ArticleAnalysis.article_id == NormalizedArticle.id,
                )
                .where(
                    ArticleAnalysis.id.is_(None),
                    NormalizedArticle.assistant_id == assistant_id if assistant_id else True,
                    reviewable_topic,
                )
                .where(_freshness_condition(NormalizedArticle.published_at, settings))
                .order_by(NormalizedArticle.extracted_at.desc())
                .limit(max(limit, settings.max_items_per_run))
            )
        ).all()
        assistant = await session.get(AssistantWorkspace, assistant_id) if assistant_id is not None else None
        profile = await _profile_for_assistant(session, assistant_id)
        # A missing business profile is valid for general market monitoring.
        # Keep the profile-shaped analysis payload stable with an in-memory
        # context rather than aborting the whole run.
        if profile is None:
            profile = _general_market_profile(assistant)
        assistant_config = dict(assistant.config or {}) if assistant is not None else {}
        knowledge_library = assistant_config.get("business_knowledge") if isinstance(assistant_config.get("business_knowledge"), dict) else {}
        topics = (
            await session.execute(select(Topic).where(Topic.enabled.is_(True)).where(Topic.assistant_id == assistant_id if assistant_id else True))
        ).scalars().all()

    client = OpenAIClient(settings)
    model_calls = 0
    fallback_calls = 0
    created = 0
    for article, item, source in rows[:limit]:
        async with SessionLocal() as session:
            topic_rows = (
                await session.execute(
                    select(Topic, ArticleTopic)
                    .join(ArticleTopic, ArticleTopic.topic_id == Topic.id)
                    .where(ArticleTopic.article_id == article.id)
                    .order_by(ArticleTopic.combined_score.desc())
                )
            ).all()
        payload: dict[str, object]
        can_call_model = (
            client.configured
            and model_calls < request_limit
            and daily_chars + len(article.normalized_text) <= settings.model_daily_input_char_cap
        )
        if can_call_model:
            try:
                result = await client.analyze(
                    article_title=article.title,
                    article_text=article.normalized_text,
                    source_name=source.name,
                    source_url=article.canonical_url,
                    published_at=(article.published_at.isoformat() if article.published_at else None),
                    business_profile={**_profile_payload(profile), "knowledge_library": knowledge_library, "message_template_guidance": _template_guidance(settings.message_templates)},
                    topics=[
                        {
                            "topic_key": topic.topic_key,
                            "name": topic.name,
                            "definition": topic.definition,
                            "current_score": score.combined_score,
                            "evidence": score.explanation,
                        }
                        for topic, score in topic_rows
                    ],
                    incomplete_text=article.extraction_status == "partial",
                )
                payload = _structured_analysis_payload(
                    result,
                    article=article,
                    source=source,
                )
                model_calls += 1
                daily_chars += len(article.normalized_text)
            except Exception as exc:
                payload = _fallback_analysis(
                    article,
                    profile=profile,
                    topic_rows=topic_rows,
                    source=source,
                    reason=f"model fallback: {type(exc).__name__}: {exc}",
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
                confidence=float(payload["confidence"]),
                facts=payload["facts"],
                inferences=payload["inferences"],
                citations=payload["citations"],
                topic_scores=payload["topic_scores"],
                model=str(payload["model"]),
                input_chars=len(article.normalized_text),
                input_tokens=int(payload["input_tokens"]),
                output_tokens=int(payload["output_tokens"]),
                estimated_cost_usd=float(payload["estimated_cost_usd"]),
                error_message=payload["error_message"],
            )
            .on_conflict_do_nothing(index_elements=[ArticleAnalysis.article_id])
            .returning(ArticleAnalysis.id)
        )
        async with SessionLocal() as session:
            inserted = (await session.execute(statement)).scalar_one_or_none()
            await session.commit()
            created += int(inserted is not None)
    return {
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
) -> dict[str, object]:
    client = OpenAIClient(settings)
    if not client.configured:
        raise RuntimeError(
            "OpenAI analysis requires both an API key and explicit external approval"
        )
    daily_count, daily_chars = await _model_budget(settings)
    available_requests = max(0, settings.model_daily_request_cap - daily_count)
    request_limit = min(limit, settings.model_max_requests_per_run, available_requests)
    async with SessionLocal() as session:
        profile = await session.get(BusinessProfile, 1)
        if profile is None:
            raise RuntimeError("approved business profile is missing")
        assistant = await session.get(AssistantWorkspace, profile.assistant_id)
        knowledge_library = ((assistant.config or {}).get("business_knowledge") if assistant is not None else {}) or {}
        rows = (
            await session.execute(
                select(ArticleAnalysis, NormalizedArticle, Source, Publication)
                .join(NormalizedArticle, NormalizedArticle.id == ArticleAnalysis.article_id)
                .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
                .join(Source, Source.id == SourceItem.source_id)
                .join(Publication, Publication.analysis_id == ArticleAnalysis.id)
                .where(
                    ArticleAnalysis.status == "fallback",
                    Publication.status == "preview",
                    NormalizedArticle.id.in_(
                        select(ArticleTopic.article_id).where(
                            ArticleTopic.selected.is_(True)
                        )
                    ),
                )
                .order_by(ArticleAnalysis.created_at.desc())
                .limit(request_limit)
            )
        ).all()

    succeeded = 0
    failed = 0
    analysis_ids: list[str] = []
    for analysis, article, source, publication in rows:
        if daily_chars + len(article.normalized_text) > settings.model_daily_input_char_cap:
            break
        async with SessionLocal() as session:
            topic_rows = (
                await session.execute(
                    select(Topic, ArticleTopic)
                    .join(ArticleTopic, ArticleTopic.topic_id == Topic.id)
                    .where(ArticleTopic.article_id == article.id)
                    .order_by(ArticleTopic.combined_score.desc())
                )
            ).all()
        try:
            result = await client.analyze(
                article_title=article.title,
                article_text=article.normalized_text,
                source_name=source.name,
                source_url=article.canonical_url,
                published_at=(
                    article.published_at.isoformat() if article.published_at else None
                ),
                business_profile={**_profile_payload(profile), "knowledge_library": knowledge_library, "message_template_guidance": _template_guidance(settings.message_templates)},
                topics=[
                    {
                        "topic_key": topic.topic_key,
                        "name": topic.name,
                        "definition": topic.definition,
                        "current_score": score.combined_score,
                        "evidence": score.explanation,
                    }
                    for topic, score in topic_rows
                ],
                incomplete_text=article.extraction_status == "partial",
            )
            payload = _structured_analysis_payload(
                result,
                article=article,
                source=source,
            )
            async with SessionLocal() as session:
                current_analysis = await session.get(
                    ArticleAnalysis, analysis.id, with_for_update=True
                )
                current_publication = await session.get(
                    Publication, publication.id, with_for_update=True
                )
                if current_analysis is None or current_publication is None:
                    raise RuntimeError("analysis or preview disappeared during reanalysis")
                current_analysis.status = str(payload["status"])
                current_analysis.headline = str(payload["headline"])[:2000]
                current_analysis.news_summary = str(payload["news_summary"])
                current_analysis.business_connection = str(payload["business_connection"])
                current_analysis.opportunity = str(payload["opportunity"])
                current_analysis.risk = str(payload["risk"])
                current_analysis.suggested_action = str(payload["suggested_action"])
                current_analysis.time_horizon = str(payload["time_horizon"])
                current_analysis.confidence = float(payload["confidence"])
                current_analysis.facts = payload["facts"]
                current_analysis.inferences = payload["inferences"]
                current_analysis.citations = payload["citations"]
                current_analysis.topic_scores = payload["topic_scores"]
                current_analysis.model = str(payload["model"])
                current_analysis.input_chars = len(article.normalized_text)
                current_analysis.input_tokens = int(payload["input_tokens"])
                current_analysis.output_tokens = int(payload["output_tokens"])
                current_analysis.estimated_cost_usd = float(
                    payload["estimated_cost_usd"]
                )
                current_analysis.error_message = None
                current_publication.message_text = _render_publication_message(
                    analysis=current_analysis,
                    article=article,
                    source=source,
                    business_name=profile.business_name,
                )
                current_publication.updated_at = _utcnow()
                current_publication.audit = {
                    **current_publication.audit,
                    "analysis_mode": "openai-approved",
                }
                await session.commit()
            daily_chars += len(article.normalized_text)
            succeeded += 1
            analysis_ids.append(str(analysis.id))
        except Exception as exc:
            async with SessionLocal() as session:
                current_analysis = await session.get(ArticleAnalysis, analysis.id)
                if current_analysis is not None:
                    current_analysis.error_message = (
                        f"approved model reanalysis failed: {type(exc).__name__}: {exc}"
                    )[:2000]
                    await session.commit()
            failed += 1
    return {
        "candidates": len(rows),
        "succeeded": succeeded,
        "failed": failed,
        "analysis_ids": analysis_ids,
        "daily_model_requests_before_run": daily_count,
        "daily_input_chars_after_run": daily_chars,
    }


async def create_publication_previews(settings: Settings, *, limit: int, assistant_id: uuid.UUID | None = None) -> dict[str, int]:
    settings = await settings_for_assistant(settings, assistant_id)
    async with SessionLocal() as session:
        has_selected_topic = exists(
            select(ArticleTopic.id).where(
                ArticleTopic.article_id == ArticleAnalysis.article_id,
                ArticleTopic.selected.is_(True),
            )
        )
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
                select(ArticleAnalysis, NormalizedArticle, SourceItem, Source, has_selected_topic.label("has_selected_topic"))
                .join(NormalizedArticle, NormalizedArticle.id == ArticleAnalysis.article_id)
                .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
                .join(Source, Source.id == SourceItem.source_id)
                .outerjoin(Publication, Publication.analysis_id == ArticleAnalysis.id)
                .where(
                    Publication.id.is_(None),
                    ~clustered_non_representative,
                    ArticleAnalysis.assistant_id == assistant_id if assistant_id else True,
                    _freshness_condition(NormalizedArticle.published_at, settings),
                )
                .order_by(ArticleAnalysis.created_at.desc())
                .limit(limit)
            )
        ).all()
    preview_settings = settings
    telegram = TelegramClient(preview_settings)
    feedback_template = (
        (preview_settings.message_templates.get("feedback") or {}).get("blocks")
        if isinstance(preview_settings.message_templates, dict)
        else None
    )
    created = 0
    for analysis, article, item, source, has_selected_topic in rows:
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
                    "review_only": not bool(has_selected_topic),
                    "relevance_state": "selected" if has_selected_topic else "borderline",
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


async def publish_publication(publication_id: uuid.UUID) -> dict[str, object]:
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
        observer_message_context = (
            await session.execute(
                select(ArticleAnalysis, NormalizedArticle, Source)
                .join(NormalizedArticle, NormalizedArticle.id == ArticleAnalysis.article_id)
                .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
                .join(Source, Source.id == SourceItem.source_id)
                .where(ArticleAnalysis.id == analysis_id)
            )
        ).one_or_none()
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
        }
        publication.audit = {
            **publication.audit,
            "published_by": "pipeline",
            "permission": asdict(permission),
        }
        publication.published_at = now
        publication.updated_at = now
        publication.error_message = None
        await session.commit()
    return {
        "publication_id": str(publication_id),
        "status": "published",
        "message_ids": message_ids,
        "observer_message_ids": observer_message_ids,
        "idempotent": False,
    }


async def approve_borderline_publication(publication_id: uuid.UUID) -> dict[str, object]:
    """Approve one borderline review item, enforcing a daily cap of ten."""
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    now = _utcnow()
    async with SessionLocal() as session:
        publication = await session.get(Publication, publication_id, with_for_update=True)
        if publication is None:
            raise KeyError("publication not found")
        audit = dict(publication.audit or {})
        if not audit.get("review_only"):
            raise RuntimeError("publication is not a borderline review item")
        approved = (await session.execute(
            select(Publication).where(
                Publication.updated_at >= day_start,
                Publication.status.in_(["published", "edited"]),
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
            Publication.assistant_id == assistant_id if assistant_id else True,
            _freshness_condition(NormalizedArticle.published_at, settings),
        ]
        if created_after is not None:
            filters.append(Publication.created_at >= created_after)
        candidates = (
            await session.execute(
                select(Publication)
                .join(ArticleAnalysis, ArticleAnalysis.id == Publication.analysis_id)
                .join(NormalizedArticle, NormalizedArticle.id == ArticleAnalysis.article_id)
                .where(*filters)
                .order_by(Publication.created_at)
            )
        ).scalars().all()
        # A borderline article is an operator signal, not an automatic
        # delivery candidate.  Filter after the freshness/scope query so a
        # large review queue cannot starve genuinely selected items.
        ids = [
            publication.id
            for publication in candidates
            if not bool((publication.audit or {}).get("review_only"))
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
    relevance_score = (
        select(func.max(ArticleTopic.combined_score))
        .where(ArticleTopic.article_id == ArticleAnalysis.article_id)
        .correlate(ArticleAnalysis)
        .scalar_subquery()
    )
    statement = (
        select(Publication, ArticleAnalysis, NormalizedArticle, SourceItem, Source, relevance_score.label("relevance_score"))
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
            "relevance_score": float(score) if score is not None else None,
            "review_only": bool((publication.audit or {}).get("review_only")),
            "relevance_state": (publication.audit or {}).get("relevance_state", "selected"),
            "approval_state": ((publication.audit or {}).get("approval") or {}).get("state", "unmanaged"),
            "approval": (publication.audit or {}).get("approval") or None,
            "bulk_label": (publication.audit or {}).get("label"),
        }
        for publication, _analysis, _article, _item, source, score in rows
    ]


async def generate_weekly_report(*, now: datetime | None = None, assistant_id: uuid.UUID | None = None) -> dict[str, object]:
    now = now or _utcnow()
    period_start = now - timedelta(days=7)
    async with SessionLocal() as session:
        topic_rows = (
            await session.execute(
                select(Topic.name, func.count(distinct(ArticleTopic.article_id)))
                .join(ArticleTopic, ArticleTopic.topic_id == Topic.id)
                .join(
                    ArticleAnalysis,
                    ArticleAnalysis.article_id == ArticleTopic.article_id,
                )
                .where(
                    ArticleTopic.selected.is_(True),
                    ArticleAnalysis.created_at >= period_start,
                    ArticleAnalysis.created_at < now,
                )
                .where(ArticleTopic.assistant_id == assistant_id if assistant_id else True)
                .group_by(Topic.name)
                .order_by(func.count(distinct(ArticleTopic.article_id)).desc())
            )
        ).all()
        profile = await _profile_for_assistant(session, assistant_id)
        analysis_count = (
            await session.execute(
                select(func.count(ArticleAnalysis.id)).where(
                    ArticleAnalysis.created_at >= period_start,
                    ArticleAnalysis.created_at < now,
                )
                .where(ArticleAnalysis.assistant_id == assistant_id if assistant_id else True)
            )
        ).scalar_one()
        feedback_rows = (
            await session.execute(
                select(Feedback.value, func.count(Feedback.id))
                .where(Feedback.created_at >= period_start, Feedback.created_at < now)
                .where(Feedback.assistant_id == assistant_id if assistant_id else True)
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
                        .where(NormalizedArticle.assistant_id == assistant_id if assistant_id else True)
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
                period_start=period_start,
                period_end=now,
                status="preview",
                digest="\n".join(digest_lines),
                trends=trends,
                competitor_mentions=competitor_mentions,
                metrics={"analyses": analysis_count, "feedback": feedback_metrics},
            )
            .on_conflict_do_nothing(
                index_elements=[WeeklyReport.period_start, WeeklyReport.period_end]
            )
            .returning(WeeklyReport.id)
        )
        inserted = (await session.execute(statement)).scalar_one_or_none()
        await session.commit()
    return {
        "report_id": str(inserted or report_id),
        "status": "preview",
        "analyses": analysis_count,
        "trends": trends,
        "competitor_mentions": competitor_mentions,
    }


async def apply_retention(settings: Settings) -> dict[str, int]:
    raw_cutoff = _utcnow() - timedelta(days=settings.raw_html_retention_days)
    normalized_cutoff = _utcnow() - timedelta(days=settings.normalized_retention_days)
    async with SessionLocal() as session:
        raw_result = await session.execute(
            update(NormalizedArticle)
            .where(
                NormalizedArticle.extracted_at < raw_cutoff,
                NormalizedArticle.raw_html.is_not(None),
            )
            .values(raw_html=None)
        )
        deleted_result = await session.execute(
            delete(NormalizedArticle).where(
                NormalizedArticle.extracted_at < normalized_cutoff
            )
        )
        await session.commit()
    return {
        "raw_html_cleared": int(raw_result.rowcount or 0),
        "normalized_articles_deleted": int(deleted_result.rowcount or 0),
    }


async def pipeline_metrics(*, assistant_id: uuid.UUID | None = None) -> dict[str, object]:
    active_settings = get_settings()
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
        source_health = dict(
            (
                await session.execute(
                    select(Source.health_status, func.count(Source.id)).where(
                        Source.assistant_id == assistant_id if assistant_id else True
                    ).group_by(
                        Source.health_status
                    )
                )
            ).all()
        )
        publication_status = dict(
            (
                await session.execute(
                    select(Publication.status, func.count(Publication.id)).where(
                        Publication.assistant_id == assistant_id if assistant_id else True
                    ).group_by(
                        Publication.status
                    )
                )
            ).all()
        )
        model_requests, input_chars = await _model_budget(active_settings)
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
        if processing_limit:
            extraction = await extract_pending_articles(settings, limit=processing_limit, assistant_id=assistant_id)
            relevance = await score_pending_articles(settings, limit=processing_limit, assistant_id=assistant_id)
            clustering = await cluster_pending_articles(settings, limit=processing_limit, assistant_id=assistant_id)
            analysis = await analyze_pending_articles(
                settings, limit=processing_limit, assistant_id=assistant_id
            )
            # Preview creation follows the processing budget; delivery below
            # is independently capped at max_items_per_run (the publish cap).
            previews = await create_publication_previews(
                settings, limit=processing_limit, assistant_id=assistant_id
            )
        else:
            extraction = {"attempted": 0, "complete": 0, "partial": 0, "failed": 0, "daily_processing_cap_reached": True}
            relevance = {"articles": 0, "scores": 0, "selected_articles": 0, "semantic": "daily_cap_reached", "rescore": False, "previews_invalidated": 0}
            clustering = {"articles": 0, "clusters": 0, "memberships": 0}
            analysis = {"candidates": 0, "succeeded": 0, "failed": 0, "analysis_ids": [], "daily_processing_cap_reached": True}
            previews = {"candidates": 0, "created": 0, "daily_processing_cap_reached": True}
        should_publish = (
            bool(publish) if publish is not None else settings.auto_publish and not settings.pilot_mode
        )
        if should_publish:
            delivery = await publish_ready_previews(
                settings.model_copy(update={"auto_publish": True, "pilot_mode": False}),
                limit=settings.max_items_per_run, assistant_id=assistant_id
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
