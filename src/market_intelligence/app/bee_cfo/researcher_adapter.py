from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any

from sqlalchemy import select

from app.article_extraction import ArticleFetcher
from app.config import Settings
from app.database import SessionLocal
from app.ingestion_service import run_ingestion, run_sources_independently
from app.models import (
    BeeCFOSource,
    BeeCFOWatch,
    NormalizedArticle,
    Source,
    SourceItem,
)
from app.pipeline_service import extract_pending_articles
from app.relevance import jaccard_similarity


@dataclass(frozen=True, slots=True)
class MarketEvidence:
    title: str
    text: str
    source_key: str
    source_name: str
    source_url: str
    source_origin: str
    source_authority: str
    discovery_path: str
    published_at: datetime | None
    discovered_at: datetime | None
    extraction_status: str
    quality_score: float
    provenance: dict[str, object]

    def prompt_payload(self) -> dict[str, object]:
        return {
            "title": self.title,
            "text": self.text,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "source_origin": self.source_origin,
            "source_authority": self.source_authority,
            "discovery_path": self.discovery_path,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "discovered_at": self.discovered_at.isoformat() if self.discovered_at else None,
            "extraction_status": self.extraction_status,
            "quality_score": self.quality_score,
        }


_GENERIC_WATCH_TERMS = {
    "market",
    "بازار",
    "free",
    "iran",
    "iranian",
    "irr",
    "price",
    "currency",
    "exchange",
    "local",
    "داخلی",
    "ارز",
    "change",
    "daily",
    "high",
    "low",
    "watch",
    "ir",
    "short",
    "long",
    "term",
    "کوتاه",
    "مدت",
    "میان",
    "چگونه",
    "تغییر",
    "نقش",
    "اصلی",
    "محرک",
}
_NAVIGATION_PATH_PARTS = {
    "about",
    "advertising",
    "api",
    "applications",
    "contact",
    "disclaimer",
    "login",
    "privacy",
    "webmaster",
}
_FOREIGN_CURRENCY_MARKERS = {
    "سنگاپور",
    "استرالیا",
    "کانادا",
    "نیوزلند",
    "انگلیس",
    "ترکیه",
    "امارات",
    "پاکستان",
    "فرانک",
    "کرون",
    "یوان",
    "روپیه",
    "رینگیت",
    "لاری",
    "منات",
    "دینار",
    "درهم",
}


def _normalized_tokens(value: object) -> set[str]:
    text = str(value or "").lower()
    text = text.replace("ي", "ی").replace("ك", "ک").replace("‌", " ")
    return {
        token
        for token in re.findall(r"[0-9a-z\u0600-\u06ff]+", text)
        if token and token not in _GENERIC_WATCH_TERMS
    }


def _watch_relevance_terms(watch: BeeCFOWatch) -> set[str]:
    """Return specific market identifiers, excluding generic navigation terms."""
    values = (watch.name, watch.market, watch.asset_class, watch.currency, watch.watch_key)
    terms = set().union(*(_normalized_tokens(value) for value in values))
    joined = " ".join(str(value or "").lower() for value in values)
    if "gold" in joined or "طلا" in joined:
        # A bare number such as ``18`` occurs in unrelated news titles and
        # dates. Retain only identifiers that actually name the gold market.
        terms.update({"طلا", "طلای", "gold", "gold-chart", "18k", "عیار", "اونس", "geram18"})
    if "usd" in joined or "دلار" in joined:
        terms.update({"دلار", "usd", "dollar", "قیمت-دلار", "price_usd"})
    return {term for term in terms if term not in _GENERIC_WATCH_TERMS and len(term) > 1}


def is_relevant_to_watch(*, watch: BeeCFOWatch, title: str, url: str) -> bool:
    """Reject source navigation and unrelated instruments before model analysis.

    The shared HTML fetcher intentionally discovers public links broadly. Bee CFO
    must narrow those links at its own boundary so a gold watch cannot cite a CHF
    page or a disclaimer page simply because it appeared on the same homepage.
    """
    path_tokens = _normalized_tokens(url)
    if path_tokens.intersection(_NAVIGATION_PATH_PARTS):
        return False
    evidence_tokens = _normalized_tokens(f"{title} {url}")
    terms = _watch_relevance_terms(watch)
    watch_text = " ".join(
        str(getattr(watch, field, "") or "").lower()
        for field in ("name", "market", "asset_class", "watch_key")
    )
    if "usd" in watch_text or "دلار" in watch_text:
        if not evidence_tokens.intersection({"دلار", "usd", "dollar", "price_usd", "آزاد"}):
            return False
        has_usd_identifier = bool(evidence_tokens.intersection({"usd", "dollar", "price_usd"}))
        if evidence_tokens.intersection(_FOREIGN_CURRENCY_MARKERS) and not has_usd_identifier:
            return False
    return bool(evidence_tokens.intersection(terms))


def cluster_evidence(evidence: list[MarketEvidence], *, threshold: float = 0.58) -> list[list[MarketEvidence]]:
    """Cluster near-identical event narratives while retaining all sources."""
    clusters: list[list[MarketEvidence]] = []
    for item in evidence:
        best: list[MarketEvidence] | None = None
        best_similarity = 0.0
        for cluster in clusters:
            similarity = jaccard_similarity(item.title, cluster[0].title)
            if similarity > best_similarity:
                best_similarity = similarity
                best = cluster
        if best is not None and best_similarity >= threshold:
            best.append(item)
        else:
            clusters.append([item])
    return clusters


class SharedResearcherAdapter:
    """Read-only reuse boundary for fetch/extraction infrastructure.

    The adapter writes only Bee CFO-owned catalog rows and uses the existing
    market-intelligence operational source/article tables for bounded public
    ingestion. No Consultant or legacy Researcher module is imported here.
    """

    capabilities = frozenset({"public_fetch", "robots", "retries", "extraction", "provenance"})

    async def sync_source(self, assistant_id, source: BeeCFOSource) -> Source:
        if len(source.source_key) > 16:
            raise ValueError("Bee CFO source_key cannot exceed the shared operational key limit")
        async with SessionLocal() as session:
            operational = (
                await session.execute(
                    select(Source).where(
                        Source.assistant_id == assistant_id,
                        Source.source_key == source.source_key,
                    )
                )
            ).scalar_one_or_none()
            if operational is None:
                operational = Source(
                    assistant_id=assistant_id,
                    source_key=source.source_key,
                    name=source.name,
                    homepage_url=source.homepage_url,
                    fetch_url=source.fetch_url,
                    adapter=source.adapter,
                    language=source.language,
                    region=source.region[:16],
                    priority=source.priority,
                    enabled=source.status == "active",
                    access_policy="public_only",
                    robots_policy="respect",
                    rate_limit_seconds=60,
                    request_timeout_seconds=20,
                    max_retries=2,
                    access_notes=f"Bee CFO origin={source.origin}; authority={source.authority}; path={source.discovery_path}",
                )
                session.add(operational)
            else:
                operational.name = source.name
                operational.homepage_url = source.homepage_url
                operational.fetch_url = source.fetch_url
                operational.adapter = source.adapter
                operational.language = source.language
                operational.region = source.region[:16]
                operational.priority = source.priority
                operational.enabled = source.status == "active"
                operational.access_notes = f"Bee CFO origin={source.origin}; authority={source.authority}; path={source.discovery_path}"
            await session.commit()
            await session.refresh(operational)
            return operational

    async def collect_for_watch(
        self,
        *,
        assistant_id,
        watch: BeeCFOWatch,
        settings: Settings,
        force: bool = False,
        limit: int | None = None,
    ) -> dict[str, object]:
        async with SessionLocal() as session:
            source_query = select(BeeCFOSource).where(
                BeeCFOSource.assistant_id == assistant_id,
                BeeCFOSource.status == "active",
            )
            if watch.source_keys:
                source_query = source_query.where(BeeCFOSource.source_key.in_(watch.source_keys))
            cfo_sources = (await session.execute(source_query.order_by(BeeCFOSource.priority.desc()))).scalars().all()
        if not cfo_sources:
            return {"status": "no_active_sources", "ingestion": None, "extraction": None, "source_keys": []}
        for source in cfo_sources:
            await self.sync_source(assistant_id, source)
        source_keys = [source.source_key for source in cfo_sources]
        ingestion = await run_ingestion(source_keys, force=force, assistant_id=assistant_id)
        extraction = await extract_pending_articles(
            settings,
            limit=limit or settings.pipeline_max_candidates_per_run,
            assistant_id=assistant_id,
        )
        refresh = await self._refresh_relevant_articles(
            assistant_id=assistant_id,
            watch=watch,
            settings=settings,
            limit=max(limit or settings.pipeline_max_candidates_per_run, 24),
        )
        return {
            "status": "completed",
            "ingestion": ingestion,
            "extraction": extraction,
            "relevance_refresh": refresh,
            "source_keys": source_keys,
        }

    async def _refresh_relevant_articles(
        self,
        *,
        assistant_id,
        watch: BeeCFOWatch,
        settings: Settings,
        limit: int,
    ) -> dict[str, int]:
        """Refresh Bee CFO's relevant pages without mutating other workspaces.

        The shared ingestion table fingerprints a discovered URL once, which is
        correct for article feeds but insufficient for dynamic market pages whose
        URL stays constant while the price changes. Re-fetch only the current
        watch's relevant pages and update only Bee CFO-owned normalized rows.
        """
        async with SessionLocal() as session:
            source_query = select(BeeCFOSource).where(
                BeeCFOSource.assistant_id == assistant_id,
                BeeCFOSource.status == "active",
            )
            if watch.source_keys:
                source_query = source_query.where(BeeCFOSource.source_key.in_(watch.source_keys))
            cfo_sources = (await session.execute(source_query.order_by(BeeCFOSource.priority.desc()))).scalars().all()
            if not cfo_sources:
                return {"candidates": 0, "refreshed": 0, "failed": 0}
            registry = {source.source_key: source for source in cfo_sources}
            rows = (
                await session.execute(
                    select(SourceItem, Source)
                    .join(Source, Source.id == SourceItem.source_id)
                    .where(
                        SourceItem.assistant_id == assistant_id,
                        Source.assistant_id == assistant_id,
                        Source.source_key.in_(list(registry)),
                    )
                    .order_by(SourceItem.discovered_at.desc())
                    .limit(max(limit * 2, limit))
                )
            ).all()
        candidates = [
            (item, source, registry[source.source_key])
            for item, source in rows
            if is_relevant_to_watch(watch=watch, title=item.title, url=item.url)
        ][:limit]
        if not candidates:
            return {"candidates": 0, "refreshed": 0, "failed": 0}

        fetcher = ArticleFetcher(settings)

        async def handler(row):
            item, source, cfo_source = row
            document = await fetcher.fetch(
                url=item.url,
                source_key=source.source_key,
                source_name=source.name,
                fallback_title=item.title,
                fallback_published_at=item.published_at,
                robots_policy=source.robots_policy,
                max_retries=source.max_retries,
            )
            return row, document

        def on_error(row, exc):
            return row, None

        results = await run_sources_independently(
            candidates,
            handler,
            concurrency=settings.extraction_concurrency,
            on_error=on_error,
        )
        refreshed = 0
        failed = 0
        now = datetime.now(timezone.utc)
        async with SessionLocal() as session:
            item_ids = [item.id for item, _, _ in candidates]
            existing_rows = (
                await session.execute(
                    select(NormalizedArticle).where(
                        NormalizedArticle.assistant_id == assistant_id,
                        NormalizedArticle.source_item_id.in_(item_ids),
                    )
                )
            ).scalars().all()
            existing = {article.source_item_id: article for article in existing_rows}
            for (item, source, cfo_source), document in results:
                if document is None or document.extraction_status not in {"complete", "partial"}:
                    failed += 1
                    continue
                article = existing.get(item.id)
                if article is None:
                    article = NormalizedArticle(
                        id=uuid.uuid4(),
                        assistant_id=assistant_id,
                        source_item_id=item.id,
                    )
                    session.add(article)
                article.canonical_url = document.canonical_url
                article.title = document.title
                article.author = document.author
                article.language = document.language
                article.published_at = document.published_at
                article.raw_html = document.raw_html
                article.normalized_text = document.text
                article.content_hash = document.content_hash
                article.extraction_status = document.extraction_status
                article.extraction_method = document.extraction_method
                article.quality_score = document.quality_score
                article.provenance = {
                    **(document.provenance or {}),
                    "bee_cfo_refresh": True,
                    "cfo_source_id": str(cfo_source.id),
                    "cfo_origin": cfo_source.origin,
                    "cfo_authority": cfo_source.authority,
                }
                article.last_error = document.error
                article.extracted_at = now
                refreshed += 1
            await session.commit()
        return {"candidates": len(candidates), "refreshed": refreshed, "failed": failed}

    async def load_evidence(
        self,
        *,
        assistant_id,
        watch: BeeCFOWatch,
        limit: int = 50,
    ) -> list[MarketEvidence]:
        async with SessionLocal() as session:
            source_query = select(BeeCFOSource).where(
                BeeCFOSource.assistant_id == assistant_id,
                BeeCFOSource.status == "active",
            )
            if watch.source_keys:
                source_query = source_query.where(BeeCFOSource.source_key.in_(watch.source_keys))
            source_rows = (await session.execute(source_query)).scalars().all()
            registry = {source.source_key: source for source in source_rows}
            if not registry:
                return []
            rows = (
                await session.execute(
                    select(NormalizedArticle, SourceItem, Source)
                    .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
                    .join(Source, Source.id == SourceItem.source_id)
                    .where(
                        NormalizedArticle.assistant_id == assistant_id,
                        Source.assistant_id == assistant_id,
                        Source.source_key.in_(list(registry)),
                        NormalizedArticle.extraction_status.in_(("complete", "partial")),
                    )
                    .order_by(NormalizedArticle.extracted_at.desc())
                    .limit(limit)
                )
            ).all()
        now = datetime.now(timezone.utc)
        evidence: list[MarketEvidence] = []
        for article, item, source in rows:
            cfo_source = registry.get(source.source_key)
            if cfo_source is None:
                continue
            # A feed title can become stale or generic while the fetched page
            # is unrelated. The canonical extracted title is the public
            # evidence title, so it is also the final relevance boundary.
            relevance_title = (article.title or item.title or "").strip()
            if not is_relevant_to_watch(
                watch=watch,
                title=relevance_title,
                url=article.canonical_url,
            ):
                continue
            timestamp = article.published_at or article.extracted_at or item.discovered_at
            if timestamp and timestamp < now - timedelta(hours=cfo_source.freshness_hours):
                continue
            evidence.append(
                MarketEvidence(
                    title=relevance_title,
                    text=article.normalized_text,
                    source_key=source.source_key,
                    source_name=source.name,
                    source_url=article.canonical_url,
                    source_origin=cfo_source.origin,
                    source_authority=cfo_source.authority,
                    discovery_path=cfo_source.discovery_path,
                    published_at=article.published_at,
                    discovered_at=item.discovered_at,
                    extraction_status=article.extraction_status,
                    quality_score=article.quality_score,
                    provenance={
                        **(article.provenance or {}),
                        "author": article.author,
                        "cfo_source_id": str(cfo_source.id),
                        "cfo_origin": cfo_source.origin,
                        "cfo_authority": cfo_source.authority,
                        "cfo_discovery_path": cfo_source.discovery_path,
                        "watch_relevance": "title_or_url_match",
                    },
                )
            )
        return evidence
