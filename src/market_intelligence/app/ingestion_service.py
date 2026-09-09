from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Iterable, TypeVar

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from app.config import Settings, get_settings
from app.database import SessionLocal
from app.fetchers import FetchFailure, FetchResult, SourceFetcher, SourceSpec, item_fingerprint
from app.models import ArticleAnalysis, NormalizedArticle, Source, SourceFetchRun, SourceItem, Topic
from app.queue_names import queue_key
from app.relevance import combine_topic_score, lexical_topic_score


T = TypeVar("T")
R = TypeVar("R")
DEFAULT_ASSISTANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@dataclass(frozen=True, slots=True)
class SourceRunResult:
    source_key: str
    status: str
    items_seen: int = 0
    items_inserted: int = 0
    attempts: int = 0
    status_code: int | None = None
    error: str | None = None


async def run_sources_independently(
    sources: Iterable[T],
    handler: Callable[[T], Awaitable[R]],
    *,
    concurrency: int,
    on_error: Callable[[T, Exception], R],
) -> list[R]:
    semaphore = asyncio.Semaphore(concurrency)

    async def guarded(source: T) -> R:
        async with semaphore:
            try:
                return await handler(source)
            except Exception as exc:  # Isolation boundary: one source cannot stop peers.
                return on_error(source, exc)

    return list(await asyncio.gather(*(guarded(source) for source in sources)))


def _source_spec(source: Source) -> SourceSpec:
    return SourceSpec(
        source_key=source.source_key,
        name=source.name,
        homepage_url=source.homepage_url,
        fetch_url=source.fetch_url,
        adapter=source.adapter,
        access_policy=source.access_policy,
        credential_ref=source.credential_ref,
        account_ref=source.account_ref,
        item_url_pattern=source.item_url_pattern,
        item_title_class_pattern=source.item_title_class_pattern,
        robots_policy=source.robots_policy,
        etag=source.etag,
        last_modified=source.last_modified,
        request_timeout_seconds=source.request_timeout_seconds,
        max_retries=source.max_retries,
    )


async def list_sources(*, assistant_id: uuid.UUID | None = None) -> list[dict[str, object]]:
    async with SessionLocal() as session:
        statement = select(Source).order_by(Source.display_order.asc(), Source.source_key)
        if assistant_id is not None:
            statement = statement.where(Source.assistant_id == assistant_id)
        rows = (await session.execute(statement)).scalars().all()
        source_ids = [source.id for source in rows]
        item_counts: dict[uuid.UUID, int] = {}
        analyzed_counts: dict[uuid.UUID, int] = {}
        if source_ids:
            item_rows = await session.execute(
                select(SourceItem.source_id, func.count(SourceItem.id))
                .where(SourceItem.source_id.in_(source_ids))
                .group_by(SourceItem.source_id)
            )
            item_counts = {source_id: int(count or 0) for source_id, count in item_rows}
            analyzed_rows = await session.execute(
                select(SourceItem.source_id, func.count(ArticleAnalysis.id))
                .join(NormalizedArticle, NormalizedArticle.source_item_id == SourceItem.id)
                .join(ArticleAnalysis, ArticleAnalysis.article_id == NormalizedArticle.id)
                .where(SourceItem.source_id.in_(source_ids))
                .group_by(SourceItem.source_id)
            )
            analyzed_counts = {source_id: int(count or 0) for source_id, count in analyzed_rows}
    return [
        {
            "id": str(source.id),
            "source_key": source.source_key,
            "name": source.name,
            "homepage_url": source.homepage_url,
            "fetch_url": source.fetch_url,
            "adapter": source.adapter,
            "item_url_pattern": source.item_url_pattern,
            "item_title_class_pattern": source.item_title_class_pattern,
            "enabled": source.enabled,
            "priority": source.priority,
            "display_order": source.display_order,
            "access_policy": source.access_policy,
            "access_notes": source.access_notes,
            "credential_ref": source.credential_ref,
            "account_ref": source.account_ref,
            "robots_policy": source.robots_policy,
            "health_status": source.health_status,
            "consecutive_failures": source.consecutive_failures,
            "last_attempt_at": source.last_attempt_at,
            "last_success_at": source.last_success_at,
            "last_status_code": source.last_status_code,
            "last_error": source.last_error,
            "last_crawl_at": source.last_attempt_at,
            "next_crawl_at": source.next_allowed_at,
            "items_received": item_counts.get(source.id, 0),
            "items_analyzed": analyzed_counts.get(source.id, 0),
        }
        for source in rows
    ]


async def _record_result(
    source_id: uuid.UUID,
    started_at: datetime,
    result: FetchResult | None,
    *,
    status: str,
    inserted: int = 0,
    error: str | None = None,
    status_code: int | None = None,
    attempts: int = 0,
    content_extraction_ok: bool = True,
) -> None:
    finished_at = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        source = await session.get(Source, source_id, with_for_update=True)
        if source is None:
            return
        seen = len(result.items) if result is not None else 0
        actual_code = result.status_code if result is not None else status_code
        actual_attempts = result.attempts if result is not None else attempts
        session.add(
            SourceFetchRun(
                assistant_id=source.assistant_id,
                source_id=source_id,
                started_at=started_at,
                finished_at=finished_at,
                status=status,
                status_code=actual_code,
                attempt_count=actual_attempts,
                items_seen=seen,
                items_inserted=inserted,
                error_message=error,
                details=(
                    {
                        "response_url": result.response_url,
                        "robots_status": result.robots_status,
                        "extraction_status": "ok" if content_extraction_ok else "empty",
                    }
                    if result is not None
                    else {}
                ),
            )
        )
        source.last_attempt_at = started_at
        if status != "rate_limited":
            source.next_allowed_at = finished_at + timedelta(
                seconds=source.rate_limit_seconds
            )
        source.last_status_code = actual_code
        source.updated_at = finished_at
        if status in {"succeeded", "not_modified"} and content_extraction_ok:
            source.last_success_at = finished_at
            source.health_status = "healthy"
            source.consecutive_failures = 0
            source.last_error = None
            if result is not None:
                source.etag = result.etag or source.etag
                source.last_modified = result.last_modified or source.last_modified
        elif status in {"succeeded", "not_modified"} and not content_extraction_ok:
            # HTTP/robots connectivity succeeded, but the adapter could not
            # extract any analyzable item (for example a Telegram page with no
            # ``tgme_widget_message_text``).  Keep the fetch run transport
            # status as succeeded for observability, while making the source
            # visibly degraded and actionable for the operator.
            source.health_status = "degraded"
            source.consecutive_failures += 1
            source.last_error = (error or "No extractable content was found")[:2000]
        elif status == "rate_limited":
            pass
        else:
            source.health_status = "degraded"
            source.consecutive_failures += 1
            source.last_error = (error or status)[:2000]
        await session.commit()


async def _store_items(
    source_id: uuid.UUID,
    assistant_id: uuid.UUID,
    result: FetchResult,
) -> int:
    if not result.items:
        return 0
    rows = [
        {
            "id": uuid.uuid4(),
            "assistant_id": assistant_id,
            "source_id": source_id,
            "fingerprint": item_fingerprint(item.title, item.url),
            "title": item.title,
            "url": item.url,
            "excerpt": item.excerpt,
            "published_at": item.published_at,
            "raw_metadata": item.raw_metadata,
        }
        for item in result.items
    ]
    statement = (
        postgresql_insert(SourceItem)
        .values(rows)
        .on_conflict_do_nothing(index_elements=[SourceItem.fingerprint])
        .returning(SourceItem.id)
    )
    async with SessionLocal() as session:
        inserted = (await session.execute(statement)).scalars().all()
        await session.commit()
    return len(inserted)


async def _ingest_source(
    source_id: uuid.UUID,
    *,
    settings: Settings,
    force: bool,
    store_items: bool = True,
) -> SourceRunResult:
    started_at = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        source = await session.get(Source, source_id)
        if source is None or not source.enabled:
            return SourceRunResult(str(source_id), "disabled")
        source_key = source.source_key
        if not force and source.next_allowed_at and source.next_allowed_at > started_at:
            await _record_result(source_id, started_at, None, status="rate_limited")
            return SourceRunResult(source_key, "rate_limited")
        spec = _source_spec(source)

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    lock_segment = f"ingest_lock_{source_key.lower().replace('-', '_')}"
    lock_name = queue_key(lock_segment, settings=settings)
    lock_token = uuid.uuid4().hex
    acquired = False
    try:
        acquired = bool(
            await redis.set(
                lock_name,
                lock_token,
                nx=True,
                ex=settings.fetch_lock_ttl_seconds,
            )
        )
        if not acquired:
            return SourceRunResult(source_key, "skipped_locked")
        fetcher = SourceFetcher(settings)
        result = await fetcher.fetch(spec)
        if result.status == "robots_denied":
            await _record_result(
                source_id,
                started_at,
                result,
                status="robots_denied",
                error="robots.txt denied the configured fetch URL",
            )
            return SourceRunResult(source_key, "robots_denied")
        # A health probe deliberately fetches and records the source outcome
        # without adding content to the ingest queue or triggering analysis.
        inserted = (
            await _store_items(source_id, source.assistant_id, result)
            if store_items
            else 0
        )
        extraction_ok = result.status == "not_modified" or bool(result.items)
        await _record_result(
            source_id,
            started_at,
            result,
            # ``source_fetch_runs.status`` intentionally models transport
            # outcomes and does not accept a synthetic degraded value.  The
            # source health field above carries extraction quality instead.
            status="succeeded" if result.status == "degraded" else result.status,
            inserted=inserted,
            content_extraction_ok=extraction_ok,
        )
        return SourceRunResult(
            source_key,
            "degraded" if not extraction_ok else result.status,
            items_seen=len(result.items),
            items_inserted=inserted,
            attempts=result.attempts,
            status_code=result.status_code,
        )
    except FetchFailure as exc:
        error = f"FetchFailure: {exc}"
        await _record_result(
            source_id,
            started_at,
            None,
            status="failed",
            error=error,
            status_code=exc.status_code,
            attempts=exc.attempts,
        )
        return SourceRunResult(
            source_key,
            "failed",
            attempts=exc.attempts,
            status_code=exc.status_code,
            error=error,
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"[:2000]
        await _record_result(
            source_id,
            started_at,
            None,
            status="failed",
            error=error,
        )
        return SourceRunResult(source_key, "failed", error=error)
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


async def run_ingestion(
    source_keys: list[str] | None = None,
    *,
    force: bool = False,
    assistant_id: uuid.UUID | None = None,
    settings: Settings | None = None,
) -> dict[str, object]:
    settings = settings or get_settings()
    effective_assistant_id = assistant_id or DEFAULT_ASSISTANT_ID
    async with SessionLocal() as session:
        statement = select(Source.id, Source.source_key).where(
            Source.enabled.is_(True), Source.assistant_id == effective_assistant_id
        )
        if source_keys:
            statement = statement.where(Source.source_key.in_(source_keys))
        rows = (
            await session.execute(
                statement.order_by(Source.priority.desc(), Source.source_key)
            )
        ).all()
    known_keys = {row.source_key for row in rows}
    missing = sorted(set(source_keys or ()) - known_keys)

    def on_error(row: object, exc: Exception) -> SourceRunResult:
        key = getattr(row, "source_key", "unknown")
        return SourceRunResult(key, "failed", error=f"{type(exc).__name__}: {exc}")

    results = await run_sources_independently(
        rows,
        lambda row: _ingest_source(row.id, settings=settings, force=force),
        concurrency=settings.fetch_concurrency,
        on_error=on_error,
    )
    return {
        "status": "completed",
        "requested_sources": source_keys or "all_enabled",
        "missing_sources": missing,
        "source_count": len(results),
        "succeeded": sum(
            result.status in {"succeeded", "not_modified"} for result in results
        ),
        "failed": sum(result.status in {"failed", "robots_denied"} for result in results),
        "degraded": sum(result.status == "degraded" for result in results),
        "items_seen": sum(result.items_seen for result in results),
        "items_inserted": sum(result.items_inserted for result in results),
        "results": [asdict(result) for result in results],
    }


async def run_source_health_probe(
    *,
    assistant_id: uuid.UUID | None = None,
    degraded_only: bool = False,
    force: bool = True,
) -> dict[str, object]:
    """Probe sources and persist the result without ingesting or publishing.

    The backoffice action is a real ``check all`` action, so newly-created
    sources with ``unknown`` health must be included. The scheduler keeps its
    cheaper degraded-only behavior through the wrapper below.
    """
    settings = get_settings()
    async with SessionLocal() as session:
        conditions = [Source.enabled.is_(True)]
        if assistant_id is not None:
            conditions.append(Source.assistant_id == assistant_id)
        if degraded_only:
            conditions.append(Source.health_status == "degraded")
        rows = (await session.execute(
            select(Source.id, Source.source_key)
            .where(*conditions)
            .order_by(Source.priority.desc(), Source.source_key)
        )).all()

    def on_error(row: object, exc: Exception) -> SourceRunResult:
        key = getattr(row, "source_key", "unknown")
        return SourceRunResult(key, "failed", error=f"{type(exc).__name__}: {exc}")

    results = await run_sources_independently(
        rows,
        lambda row: _ingest_source(
            row.id, settings=settings, force=force, store_items=False
        ),
        concurrency=settings.fetch_concurrency,
        on_error=on_error,
    )
    return {
        "status": "completed",
        "source_count": len(results),
        "healthy": sum(result.status in {"succeeded", "not_modified"} for result in results),
        "failed": sum(result.status in {"failed", "robots_denied"} for result in results),
        "degraded": sum(result.status == "degraded" for result in results),
        "results": [asdict(result) for result in results],
    }


async def run_source_probe(
    source_id: uuid.UUID,
    *,
    assistant_id: uuid.UUID,
    limit: int = 20,
    settings: Settings | None = None,
) -> dict[str, object]:
    """Fetch and score one source without publishing anything.

    This is the bounded, operator-facing smoke test used immediately after a
    source is saved.  It deliberately reuses the production ingestion lock,
    parser and item store, then applies the same lexical relevance contract
    as the pipeline.  No normalized article, publication or Telegram send is
    created here; the result is only a reviewable diagnostic.
    """
    bounded_limit = min(max(int(limit), 10), 20)
    base_settings = settings or get_settings()
    # Resolve project-level limits (including its relevance threshold), while
    # overriding only the probe fetch size. The import is local to avoid the
    # pipeline_service <-> ingestion_service import cycle at module load.
    from app.pipeline_service import settings_for_assistant

    effective = await settings_for_assistant(base_settings, assistant_id)
    probe_settings = effective.model_copy(
        update={"fetch_max_items_per_source": bounded_limit}
    )
    async with SessionLocal() as session:
        source = await session.get(Source, source_id)
        if source is None or source.assistant_id != assistant_id:
            raise ValueError("source not found for this project")
        source_key = source.source_key
        source_name = source.name

    run = await _ingest_source(
        source_id,
        settings=probe_settings,
        force=True,
        store_items=True,
    )
    if run.status == "degraded":
        return {
            "status": "degraded",
            "source_id": str(source_id),
            "source_key": source_key,
            "source_name": source_name,
            "connection": "connected_no_extractable_text",
            "posts_found": run.items_seen,
            "texts_extractable": 0,
            "related": 0,
            "near_threshold": 0,
            "top_results": [],
            "error": "No extractable content was found in the latest response",
            "no_publish": True,
        }
    if run.status in {"failed", "robots_denied", "disabled", "skipped_locked"}:
        return {
            "status": "failed" if run.status != "disabled" else "disabled",
            "source_id": str(source_id),
            "source_key": source_key,
            "source_name": source_name,
            "connection": "failed",
            "posts_found": run.items_seen,
            "texts_extractable": 0,
            "related": 0,
            "near_threshold": 0,
            "top_results": [],
            "error": run.error or run.status,
            "no_publish": True,
        }

    async with SessionLocal() as session:
        topics = (
            await session.execute(
                select(Topic)
                .where(Topic.assistant_id == assistant_id, Topic.enabled.is_(True))
                .order_by(Topic.importance.desc(), Topic.display_order, Topic.topic_key)
            )
        ).scalars().all()
        items = (
            await session.execute(
                select(SourceItem)
                .where(
                    SourceItem.source_id == source_id,
                    SourceItem.assistant_id == assistant_id,
                )
                .order_by(
                    SourceItem.published_at.desc().nullslast(),
                    SourceItem.discovered_at.desc(),
                )
                .limit(bounded_limit)
            )
        ).scalars().all()
        current_source = await session.get(Source, source_id)

    thresholds = [
        max(float(topic.threshold), float(probe_settings.relevance_threshold))
        for topic in topics
    ]
    default_threshold = min(thresholds) if thresholds else float(probe_settings.relevance_threshold)
    results: list[dict[str, object]] = []
    for item in items:
        text = f"{item.title}\n{item.excerpt or ''}".strip()
        best: tuple[float, str, float, tuple[str, ...], tuple[str, ...]] | None = None
        for topic in topics:
            lexical, positive, negative = lexical_topic_score(
                title=item.title,
                text=text,
                positive_terms=list(topic.positive_terms or []),
                negative_terms=list(topic.negative_terms or []),
            )
            threshold = max(float(topic.threshold), float(probe_settings.relevance_threshold))
            score = combine_topic_score(
                lexical=lexical,
                semantic=None,
                threshold=threshold,
                positive_matches=positive,
                negative_matches=negative,
            )
            candidate = (
                float(score.combined_score),
                topic.name,
                threshold,
                score.positive_matches,
                score.negative_matches,
            )
            if best is None or candidate[0] > best[0]:
                best = candidate
        score_value = best[0] if best else 0.0
        threshold = best[2] if best else default_threshold
        if score_value >= threshold:
            state = "related"
        elif score_value >= max(0.0, threshold - 0.10):
            state = "near_threshold"
        else:
            state = "not_related"
        results.append(
            {
                "title": item.title,
                "url": item.url,
                "published_at": item.published_at,
                "relevance_score": round(score_value, 4),
                "threshold": round(threshold, 4),
                "state": state,
                "topic": best[1] if best else None,
                "matched_terms": list(best[3]) if best else [],
            }
        )
    results.sort(key=lambda row: float(row["relevance_score"]), reverse=True)
    related = sum(row["state"] == "related" for row in results)
    near = sum(row["state"] == "near_threshold" for row in results)
    error = current_source.last_error if current_source is not None else None
    return {
        "status": "degraded" if run.status == "degraded" else "completed",
        "source_id": str(source_id),
        "source_key": source_key,
        "source_name": source_name,
        "connection": "connected" if run.status != "degraded" else "connected_no_extractable_text",
        "posts_found": run.items_seen,
        "texts_extractable": len(items),
        "related": related,
        "near_threshold": near,
        "top_results": results[:5],
        "error": error,
        "no_publish": True,
    }


async def run_degraded_source_health_probe() -> dict[str, object]:
    """Check degraded public sources once per scheduler day."""
    return await run_source_health_probe(degraded_only=True, force=False)
