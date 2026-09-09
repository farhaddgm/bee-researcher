"""Small, review-first insight projections for the back-office.

The insight layer deliberately derives its values from the existing article,
source, cluster, topic and feedback tables.  It does not mutate ranking or
publication state.  This keeps the new quality/priority/trend views safe to
enable for existing workspaces and makes every result explainable.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import distinct, func, select

from app.config import Settings
from app.database import SessionLocal
from app.models import (
    ArticleAnalysis,
    ArticleTopic,
    AssistantWorkspace,
    ClusterMember,
    EventCluster,
    NormalizedArticle,
    Source,
    SourceFetchRun,
    SourceItem,
    Topic,
)
from app.openai_client import OpenAIClient


_WORD_RE = re.compile(r"[\wآ-ی]{3,}", re.UNICODE)


def _tokens(value: str) -> set[str]:
    return set(_WORD_RE.findall((value or "").lower()))


def classify_priority(analysis: ArticleAnalysis, relevance_score: float | None) -> str:
    """Classify a publication as urgent or digest without changing delivery."""
    score = float(relevance_score or 0)
    urgent_words = ("فوری", "بحرانی", "هشدار", "تهدید", "تحریم", "اختلال")
    risk = str(analysis.risk or "")
    if analysis.time_horizon == "فوری" or (score >= 0.75 and any(word in risk for word in urgent_words)):
        return "urgent"
    return "digest"


def quality_projection(article: NormalizedArticle, source: Source, corroboration: int = 1) -> dict[str, Any]:
    extraction = max(0.0, min(1.0, float(article.quality_score or 0)))
    completeness = max(0.0, min(1.0, len(article.normalized_text or "") / 2500))
    reliability = {"healthy": 1.0, "unknown": 0.65, "degraded": 0.35, "disabled": 0.0}.get(source.health_status, 0.5)
    corroboration_score = max(0.4, min(1.0, int(corroboration or 1) / 3))
    overall = round(extraction * 0.45 + reliability * 0.25 + completeness * 0.2 + corroboration_score * 0.1, 4)
    return {
        "score": overall,
        "extraction": round(extraction, 4),
        "source_reliability": round(reliability, 4),
        "completeness": round(completeness, 4),
        "corroboration": round(corroboration_score, 4),
    }


def _conflict_state(titles: list[str]) -> dict[str, Any]:
    unique = [title for title in dict.fromkeys(titles) if title]
    if len(unique) < 2:
        return {"state": "single_source", "source_count": len(unique), "similarity": 1.0}
    sets = [_tokens(title) for title in unique]
    pairs: list[float] = []
    for index, left in enumerate(sets):
        for right in sets[index + 1 :]:
            union = left | right
            pairs.append(len(left & right) / len(union) if union else 1.0)
    similarity = round(sum(pairs) / len(pairs), 4) if pairs else 1.0
    return {
        "state": "review" if similarity < 0.42 else "aligned",
        "source_count": len(unique),
        "similarity": similarity,
        "titles": unique[:5],
    }


async def _cluster_titles(session, assistant_id: uuid.UUID) -> dict[uuid.UUID, dict[str, Any]]:
    rows = (await session.execute(
        select(ClusterMember.article_id, EventCluster.id, NormalizedArticle.title)
        .join(EventCluster, EventCluster.id == ClusterMember.cluster_id)
        .join(NormalizedArticle, NormalizedArticle.id == ClusterMember.article_id)
        .where(ClusterMember.assistant_id == assistant_id)
        .order_by(EventCluster.updated_at.desc())
    )).all()
    grouped: dict[uuid.UUID, list[str]] = defaultdict(list)
    for article_id, _cluster_id, title in rows:
        grouped[article_id].append(str(title or ""))
    return {article_id: _conflict_state(titles) for article_id, titles in grouped.items()}


async def source_health_summary(*, assistant_id: uuid.UUID) -> dict[str, Any]:
    async with SessionLocal() as session:
        sources = (await session.execute(
            select(Source).where(Source.assistant_id == assistant_id).order_by(Source.priority.desc(), Source.name)
        )).scalars().all()
        runs = (await session.execute(
            select(SourceFetchRun)
            .where(SourceFetchRun.assistant_id == assistant_id)
            .order_by(SourceFetchRun.source_id, SourceFetchRun.started_at.desc())
            .limit(5000)
        )).scalars().all()
        failure_rows = (await session.execute(
            select(SourceFetchRun.source_id, func.count(SourceFetchRun.id))
            .where(SourceFetchRun.assistant_id == assistant_id, SourceFetchRun.status == "failed", SourceFetchRun.started_at >= datetime.now(timezone.utc) - timedelta(days=30))
            .group_by(SourceFetchRun.source_id)
        )).all()
    latest: dict[uuid.UUID, SourceFetchRun] = {}
    for run in runs:
        latest.setdefault(run.source_id, run)
    failures = {source_id: int(count or 0) for source_id, count in failure_rows}
    now = datetime.now(timezone.utc)

    def freshness(last_success: datetime | None) -> str:
        if last_success is None:
            return "unknown"
        age = (now - last_success).total_seconds()
        return "fresh" if age <= 86400 else "stale" if age <= 604800 else "missing"

    def metrics(source: Source) -> dict[str, Any]:
        run = latest.get(source.id)
        latency = None
        if run is not None and run.started_at and run.finished_at:
            started = run.started_at if run.started_at.tzinfo else run.started_at.replace(tzinfo=timezone.utc)
            finished = run.finished_at if run.finished_at.tzinfo else run.finished_at.replace(tzinfo=timezone.utc)
            latency = max(0.0, round((finished - started).total_seconds(), 3))
        return {
            "id": str(source.id),
            "source_key": source.source_key,
            "name": source.name,
            "status": source.health_status,
            "enabled": bool(source.enabled),
            "last_error": source.last_error,
            "last_attempt_at": source.last_attempt_at,
            "last_success_at": source.last_success_at,
            "latest_run_at": run.finished_at if run else None,
            "latest_run_status": run.status if run else None,
            "latency_seconds": latency,
            "failure_count_30d": failures.get(source.id, 0),
            "freshness_state": freshness(source.last_success_at),
            "fallback_candidate": source.homepage_url if source.homepage_url and source.homepage_url != source.fetch_url else None,
        }
    counts = Counter(source.health_status for source in sources)
    all_metrics = [metrics(source) for source in sources]
    degraded = [item for item in all_metrics if item["status"] == "degraded"]
    return {
        "total": len(sources),
        "enabled": sum(bool(source.enabled) for source in sources),
        "healthy": int(counts.get("healthy", 0)),
        "degraded": int(counts.get("degraded", 0)),
        "unknown": int(counts.get("unknown", 0)),
        "disabled": int(counts.get("disabled", 0)),
        "sources": degraded,
        "source_metrics": all_metrics,
        "measured_at": now,
    }


async def trend_radar(*, assistant_id: uuid.UUID, days: int = 7) -> list[dict[str, Any]]:
    days = max(1, min(int(days), 30))
    now = datetime.now(timezone.utc)
    current_start = now - timedelta(days=days)
    previous_start = current_start - timedelta(days=days)
    # A second simple pass is clearer than relying on database-specific FILTER
    # syntax and works on the project's PostgreSQL test fixture as well.
    result: list[dict[str, Any]] = []
    async with SessionLocal() as session:
        current = (await session.execute(
            select(Topic.name, func.count(distinct(ArticleTopic.article_id)))
            .join(ArticleTopic, ArticleTopic.topic_id == Topic.id)
            .join(ArticleAnalysis, ArticleAnalysis.article_id == ArticleTopic.article_id)
            .where(ArticleTopic.assistant_id == assistant_id, ArticleTopic.selected.is_(True), ArticleAnalysis.created_at >= current_start, ArticleAnalysis.created_at < now)
            .group_by(Topic.name)
        )).all()
        previous = (await session.execute(
            select(Topic.name, func.count(distinct(ArticleTopic.article_id)))
            .join(ArticleTopic, ArticleTopic.topic_id == Topic.id)
            .join(ArticleAnalysis, ArticleAnalysis.article_id == ArticleTopic.article_id)
            .where(ArticleTopic.assistant_id == assistant_id, ArticleTopic.selected.is_(True), ArticleAnalysis.created_at >= previous_start, ArticleAnalysis.created_at < current_start)
            .group_by(Topic.name)
        )).all()
    current_map = {str(name): int(count or 0) for name, count in current}
    previous_map = {str(name): int(count or 0) for name, count in previous}
    names = sorted(set(current_map) | set(previous_map), key=lambda name: current_map.get(name, 0), reverse=True)
    for name in names[:12]:
        now_count, old_count = current_map.get(name, 0), previous_map.get(name, 0)
        result.append({"topic": name, "current": now_count, "previous": old_count, "delta": now_count - old_count, "direction": "up" if now_count > old_count else "down" if now_count < old_count else "flat"})
    return result


async def insights_snapshot(*, assistant_id: uuid.UUID, days: int = 7) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, min(int(days), 30)))
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(ArticleAnalysis, NormalizedArticle, SourceItem, Source)
            .join(NormalizedArticle, NormalizedArticle.id == ArticleAnalysis.article_id)
            .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
            .join(Source, Source.id == SourceItem.source_id)
            .where(ArticleAnalysis.assistant_id == assistant_id, ArticleAnalysis.created_at >= cutoff)
            .order_by(ArticleAnalysis.created_at.desc()).limit(100)
        )).all()
        clusters = await _cluster_titles(session, assistant_id)
        cluster_rows = (await session.execute(
            select(EventCluster).where(EventCluster.assistant_id == assistant_id).order_by(EventCluster.updated_at.desc()).limit(100)
        )).scalars().all()
        cluster_members = (await session.execute(
            select(ClusterMember.cluster_id, NormalizedArticle.title, Source.name)
            .join(NormalizedArticle, NormalizedArticle.id == ClusterMember.article_id)
            .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
            .join(Source, Source.id == SourceItem.source_id)
            .where(ClusterMember.assistant_id == assistant_id, ClusterMember.cluster_id.in_([row.id for row in cluster_rows]))
        )).all() if cluster_rows else []
        topic_rows = (await session.execute(
            select(ArticleTopic.article_id, ArticleTopic.topic_id, ArticleAnalysis.id, NormalizedArticle.title, Source.name, ArticleAnalysis.created_at)
            .join(ArticleAnalysis, ArticleAnalysis.article_id == ArticleTopic.article_id)
            .join(NormalizedArticle, NormalizedArticle.id == ArticleTopic.article_id)
            .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
            .join(Source, Source.id == SourceItem.source_id)
            .where(ArticleTopic.assistant_id == assistant_id, ArticleTopic.selected.is_(True))
            .order_by(ArticleAnalysis.created_at.desc())
        )).all()
    articles: list[dict[str, Any]] = []
    topic_members: dict[uuid.UUID, list[dict[str, Any]]] = defaultdict(list)
    article_topic_ids: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for article_id, topic_id, related_analysis_id, title, source_name, created_at in topic_rows:
        article_topic_ids[article_id].add(topic_id)
        topic_members[topic_id].append({"analysis_id": str(related_analysis_id), "article_id": str(article_id), "title": title, "source": source_name, "created_at": created_at})
    for analysis, article, _item, source in rows:
        conflict = clusters.get(article.id, {"state": "single_source", "source_count": 1, "similarity": 1.0})
        quality = quality_projection(article, source, conflict.get("source_count", 1))
        relevance = max((float(value) for value in (analysis.topic_scores or {}).values()), default=0.0)
        related: list[dict[str, Any]] = []
        seen_related: set[str] = set()
        for topic_id in article_topic_ids.get(article.id, set()):
            for candidate in topic_members.get(topic_id, []):
                if candidate["article_id"] == str(article.id) or candidate["article_id"] in seen_related:
                    continue
                seen_related.add(candidate["article_id"])
                related.append(candidate)
        related.sort(key=lambda item: item.get("created_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        articles.append({
            "analysis_id": str(analysis.id),
            "article_id": str(article.id),
            "title": article.title,
            "source": source.name,
            "language": article.language,
            "priority": classify_priority(analysis, relevance),
            "relevance_score": round(relevance, 4),
            "quality": quality,
            "conflict": conflict,
            "translation_available": article.language.lower() not in {"fa", "fas", "persian"},
            "related_articles": related[:5],
            "related_count": len(related),
            "created_at": analysis.created_at,
        })
    return {
        "status": "ok",
        "assistant_id": str(assistant_id),
        "period_days": days,
        "urgent_count": sum(item["priority"] == "urgent" for item in articles),
        "review_conflicts": sum(item["conflict"]["state"] == "review" for item in articles),
        "articles": articles,
        "trends": await trend_radar(assistant_id=assistant_id, days=days),
        "source_health": await source_health_summary(assistant_id=assistant_id),
        "event_clusters": [
            {
                "id": str(row.id),
                "headline": row.headline,
                "source_count": int(row.source_count or 0),
                "updated_at": row.updated_at,
                "members": [{"title": title, "source": source} for cluster_id, title, source in cluster_members if cluster_id == row.id][:10],
                "publish_once": True,
            }
            for row in cluster_rows
        ],
    }


async def activate_official_fallback(*, source_id: uuid.UUID, assistant_id: uuid.UUID) -> dict[str, Any]:
    """Switch a degraded source to its configured public homepage after review."""
    async with SessionLocal() as session:
        source = (await session.execute(select(Source).where(Source.id == source_id, Source.assistant_id == assistant_id).with_for_update())).scalar_one_or_none()
        if source is None:
            raise ValueError("source not found")
        if source.health_status != "degraded":
            raise ValueError("only degraded sources can use the official fallback")
        if not source.homepage_url or source.homepage_url == source.fetch_url:
            raise ValueError("this source has no distinct official fallback URL")
        previous = source.fetch_url
        source.fetch_url = source.homepage_url
        source.adapter = "html"
        source.health_status = "unknown"
        source.consecutive_failures = 0
        source.last_error = "official homepage fallback selected; health probe pending"
        source.updated_at = datetime.now(timezone.utc)
        await session.commit()
    return {"status": "fallback_selected", "source_id": str(source_id), "previous_fetch_url": previous, "fetch_url": source.homepage_url, "adapter": "html"}


async def translate_analysis(*, settings: Settings, analysis_id: uuid.UUID, assistant_id: uuid.UUID, target_language: str = "fa") -> dict[str, Any]:
    target = target_language.lower().strip()
    if target not in {"fa", "en"}:
        raise ValueError("target_language must be fa or en")
    async with SessionLocal() as session:
        row = (await session.execute(
            select(ArticleAnalysis, NormalizedArticle, Source)
            .join(NormalizedArticle, NormalizedArticle.id == ArticleAnalysis.article_id)
            .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
            .join(Source, Source.id == SourceItem.source_id)
            .where(ArticleAnalysis.id == analysis_id, ArticleAnalysis.assistant_id == assistant_id)
        )).one_or_none()
    if row is None:
        raise ValueError("analysis not found")
    analysis, article, source = row
    client = OpenAIClient(settings)
    translated = await client.draft_json(
        system_prompt="Translate the supplied market-intelligence fields faithfully. Preserve facts, uncertainty and proper names. Do not add information.",
        user_payload={"target_language": target, "source": source.name, "title": article.title, "summary": analysis.news_summary, "business_connection": analysis.business_connection, "risk": analysis.risk, "opportunity": analysis.opportunity, "action": analysis.suggested_action},
        schema_name="market_intelligence_translation",
        schema={
            "type": "object",
            "properties": {"title": {"type": "string"}, "summary": {"type": "string"}, "business_connection": {"type": "string"}, "risk": {"type": "string"}, "opportunity": {"type": "string"}, "action": {"type": "string"}, "ambiguity_note": {"type": "string"}},
            "required": ["title", "summary", "business_connection", "risk", "opportunity", "action", "ambiguity_note"],
            "additionalProperties": False,
        },
    )
    return {"status": "translated", "analysis_id": str(analysis_id), "source_language": article.language, "target_language": target, "translation": translated}
