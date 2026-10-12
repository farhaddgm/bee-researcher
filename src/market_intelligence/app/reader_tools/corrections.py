"""Bounded public-source rechecks; immutable changes never rewrite a report."""
import asyncio
import hashlib
import logging
import uuid
from datetime import timedelta
import re
from fastapi import HTTPException
from sqlalchemy import func, select, text
from app import admin
from app.article_extraction import ArticleFetcher
from app.config import get_settings
from app.database import SessionLocal
from app.deployment_drain import protected_work
from app.models import AdminUser, ArticleAnalysis, NormalizedArticle, Publication, Source, SourceItem
from app.news_chat import service as chat
from app.news_chat.context import context_for, reader_report_text
from app.reader_tools.models import NewsMonitor, NewsRevision, NewsWatch

LOCK = 71394003
BOUND = 24000
LOGGER = logging.getLogger(__name__)


def fingerprint(title, body):
    clean = re.sub(r'\s+', ' ', str(title) + '\n' + str(body)).strip()
    return hashlib.sha256(clean.encode()).hexdigest()


def source_notice(title, body):
    value = (title + '\n' + body[:1500]).casefold()
    if re.search(r'(?m)^\s*(?:retraction|retracted|تکذیبیه|سحب المقال|geri çekme|retractación|ritrattazione|rücknahme|rétractation)\s*[:：\-]', value):
        return 'retraction_notice'
    if re.search(r'(?m)^\s*(?:correction|corrected|اصلاحیه|تصحيح|düzeltme|corrección|correzione|korrektur|rectification)\s*[:：\-]', value):
        return 'correction_notice'
    return 'changed'


async def source_row(s, pid):
    return (await s.execute(select(Publication, NormalizedArticle, SourceItem, Source).join(ArticleAnalysis,
        (ArticleAnalysis.id == Publication.analysis_id) & (ArticleAnalysis.assistant_id == Publication.assistant_id))
        .join(NormalizedArticle, (NormalizedArticle.id == ArticleAnalysis.article_id) &
              (NormalizedArticle.assistant_id == Publication.assistant_id))
        .join(SourceItem, (SourceItem.id == NormalizedArticle.source_item_id) &
              (SourceItem.assistant_id == Publication.assistant_id))
        .join(Source, (Source.id == SourceItem.source_id) & (Source.assistant_id == Publication.assistant_id))
        .where(Publication.id == pid, Publication.status == 'published'))).one_or_none()


async def ensure_watch(s, user, pub, *, enabled=None):
    """Called only after publication ACL; explicit saves attach dependencies."""
    await s.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': LOCK})
    monitor = await s.get(NewsMonitor, pub.id, with_for_update=True)
    if monitor is None:
        row = await source_row(s, pub.id)
        clean = reader_report_text(pub.message_text)
        original = row[1] if row else None
        monitor = NewsMonitor(publication_id=pub.id, assistant_id=pub.assistant_id, version=0,
            report_hash=context_for(pub.message_text, None)['version'], report_text=clean[:BOUND],
            report_complete=len(clean)<=BOUND, source_complete=False,
            # Retain only a hash of the ingestion baseline, never disclose or
            # send stored internal original prose. Future text comes from a
            # fresh public fetch governed by the existing public transport.
            source_hash=fingerprint(original.title, original.normalized_text) if original and
                        original.extraction_status == 'complete' and original.normalized_text else None,
            source_text='', source_title='', next_check_at=chat.now(), check_status='pending')
        s.add(monitor)
        await s.flush()
    visible = reader_report_text(pub.message_text)
    current_hash = context_for(pub.message_text, None)['version']
    if monitor.report_hash != current_hash:
        append_revision(s, monitor, 'report', monitor.report_hash, current_hash,
            monitor.report_text, visible, visible.splitlines()[0] if visible else '', monitor.report_complete and len(visible)<=BOUND)
        monitor.report_hash, monitor.report_text, monitor.report_complete = current_hash, visible[:BOUND], len(visible)<=BOUND
    watch = await s.get(NewsWatch, (user.id, pub.id))
    if watch is None:
        count = await s.scalar(select(func.count()).select_from(NewsWatch).where(NewsWatch.user_id == user.id))
        if count >= 10000:
            raise HTTPException(429, 'watch_limit')
        watch = NewsWatch(user_id=user.id, publication_id=pub.id, assistant_id=pub.assistant_id,
                          enabled=enabled is not False, seen_version=monitor.version)
        s.add(watch)
    elif enabled is not None:
        watch.enabled = enabled
    return monitor.version


async def dependency_versions(s, user, aid, ids):
    versions = {}
    for pid in ids:
        pid = uuid.UUID(str(pid))
        pub = await s.scalar(select(Publication).where(Publication.id == pid, Publication.assistant_id == aid,
                                                      Publication.status == 'published'))
        if pub is None:
            raise HTTPException(404, 'news_unavailable')
        versions[str(pid)] = await ensure_watch(s, user, pub)
    return versions


async def context_evidence_versions(s, context, ids):
    if context.get('evidence_versions'):
        return {str(pid): context['evidence_versions'].get(str(pid), 0) for pid in ids}
    versions = {}
    hashes = context.get('source_versions') or {str(pid): context.get('version') for pid in ids}
    for pid in ids:
        matched = await s.scalar(select(func.max(NewsRevision.version)).where(
            NewsRevision.publication_id == uuid.UUID(str(pid)), NewsRevision.channel == 'report',
            NewsRevision.after_hash == hashes.get(str(pid))))
        versions[str(pid)] = {'report': matched or 0, 'source': 0, 'report_hash': hashes.get(str(pid))}
    return versions


async def retain_report_history(s, context, ids):
    """Use only server-captured published segments, never private memory/data."""
    hashes = context.get('source_versions') or {str(pid): context.get('version') for pid in ids}
    for pid in ids:
        pid = uuid.UUID(str(pid))
        monitor = await s.get(NewsMonitor, pid, with_for_update=True)
        before_hash = hashes.get(str(pid))
        if not monitor or not before_hash or before_hash == monitor.report_hash:
            continue
        existed = await s.scalar(select(NewsRevision.id).where(NewsRevision.publication_id == pid,
            NewsRevision.channel == 'report', NewsRevision.before_hash == before_hash,
            NewsRevision.after_hash == monitor.report_hash).limit(1))
        if existed:
            continue
        before = '\n'.join(seg['text'] for seg in context.get('segments', []) if
            seg.get('scope', 'published_report') == 'published_report' and
            (str(seg.get('publication_id', pid)) == str(pid)))
        if before:
            append_revision(s, monitor, 'report', before_hash, monitor.report_hash, before,
                monitor.report_text, monitor.report_text.splitlines()[0] if monitor.report_text else '', False)


async def stale_sources(s, aid, ids, versions, created_at=None):
    if not ids:
        return []
    monitors = list((await s.scalars(select(NewsMonitor).where(NewsMonitor.assistant_id == aid,
        NewsMonitor.publication_id.in_([uuid.UUID(str(v)) for v in ids])))).all())
    changed = []
    for m in monitors:
        key = str(m.publication_id)
        pub = await s.get(Publication, m.publication_id)
        current_hash = context_for(pub.message_text,None)['version'] if pub else None
        if key in (versions or {}):
            baseline=versions[key]
            if isinstance(baseline, dict):
                latest=(await s.execute(select(NewsRevision.channel,func.max(NewsRevision.version)).where(NewsRevision.publication_id==m.publication_id).group_by(NewsRevision.channel))).all()
                stale=bool(baseline.get('report_hash') and baseline['report_hash']!=current_hash) or any(version>baseline.get(channel,0) for channel,version in latest)
            else:
                stale = m.version > int(baseline) or bool(current_hash and current_hash!=m.report_hash)
        else:
            stale = bool(created_at and await s.scalar(select(NewsRevision.id).where(
                NewsRevision.publication_id == m.publication_id, NewsRevision.created_at > created_at).limit(1)))
        if stale:
            changed.append(key)
    return changed


async def watchers_active(s, pub):
    users = list((await s.scalars(select(AdminUser).join(NewsWatch, NewsWatch.user_id == AdminUser.id)
        .where(NewsWatch.publication_id == pub.id, NewsWatch.enabled.is_(True), AdminUser.active.is_(True)))).all())
    for user in users:
        if not admin.user_portal_access_allowed(user):
            continue
        if str(pub.assistant_id) in {a['id'] for a in (await admin.reader_assistants(user))['assistants']}:
            return True
    return False


def append_revision(s, monitor, channel, before_hash, after_hash, before_text, after_text, title, complete=True):
    monitor.version += 1
    s.add(NewsRevision(publication_id=monitor.publication_id, assistant_id=monitor.assistant_id,
        version=monitor.version, channel=channel, before_hash=before_hash, after_hash=after_hash,
        before_text=before_text[:BOUND], after_text=after_text[:BOUND], title=title[:500],
        complete=complete, notice=source_notice(title, after_text) if channel == 'source' else 'changed'))


@protected_work
async def recheck(pid, *, manual=False):
    lease = uuid.uuid4()
    async with SessionLocal() as s:
        row = await source_row(s, pid)
        monitor = await s.get(NewsMonitor, pid, with_for_update=True)
        if not row or not monitor or not row[3].enabled or not await watchers_active(s, row[0]):
            if monitor:
                monitor.next_check_at, monitor.check_status = chat.now()+timedelta(hours=1), 'unavailable'
                await s.commit()
            return {'status': 'unavailable'}
        at = chat.now()
        if monitor.lease_until and monitor.lease_until > at:
            return {'status': 'checking'}
        if manual and monitor.checked_at and monitor.checked_at > at - timedelta(minutes=5):
            return {'status': 'cooldown'}
        if not manual and monitor.next_check_at > at:
            return {'status': 'not_due'}
        monitor.lease_token, monitor.lease_until = lease, at + timedelta(minutes=5)
        monitor.next_check_at, monitor.check_status = at + timedelta(hours=1), 'checking'
        await s.commit()
        _, _article, item, source = row
        source_identity = (item.id, source.id, item.url)
        public_args = dict(url=item.url, source_key=source.source_key, source_name=source.name,
            fallback_title=item.title, fallback_published_at=item.published_at,
            robots_policy='respect', max_retries=0)
    document = None
    state = 'unavailable'
    try:
        document = await ArticleFetcher(get_settings()).fetch(**public_args)
        state = 'ok' if document.extraction_status == 'complete' and document.text.strip() else 'blocked' if document.extraction_status == 'blocked' else 'incomplete'
    except Exception:
        # Fetch failures contain URL/transport details; do not persist or log
        # them, and never interpret a failure, 404 or paywall as a retraction.
        state = 'unavailable'
    async with SessionLocal() as s:
        monitor = await s.get(NewsMonitor, pid, with_for_update=True)
        row = await source_row(s, pid)
        if monitor is None or monitor.lease_token != lease:
            return {'status': 'unavailable'}
        if row is None or not row[3].enabled or (row[2].id, row[3].id, row[2].url) != source_identity or not await watchers_active(s, row[0]):
            monitor.lease_until = None
            monitor.lease_token = None
            monitor.check_status = 'unavailable'
            await s.commit()
            return {'status': 'unavailable'}
        pub = row[0]
        report = reader_report_text(pub.message_text)
        report_hash = context_for(pub.message_text, None)['version']
        if report_hash != monitor.report_hash:
            append_revision(s, monitor, 'report', monitor.report_hash, report_hash,
                monitor.report_text, report, report.splitlines()[0] if report else '', monitor.report_complete and len(report) <= BOUND)
            monitor.report_hash, monitor.report_text, monitor.report_complete = report_hash, report[:BOUND], len(report)<=BOUND
        if state == 'ok' and document:
            source_hash = fingerprint(document.title, document.text)
            if monitor.source_hash and source_hash != monitor.source_hash:
                append_revision(s, monitor, 'source', monitor.source_hash, source_hash,
                    (monitor.source_title+'\n'+monitor.source_text).strip() if monitor.source_text else '', document.title+'\n'+document.text, document.title,
                    monitor.source_complete and len(document.title)+len(document.text)+1 <= BOUND)
            monitor.source_hash = source_hash
            monitor.source_text, monitor.source_title = document.text[:BOUND], document.title[:500]
            monitor.source_complete = len(document.title)+len(document.text)+1<=BOUND
        monitor.checked_at, monitor.check_status = chat.now(), state
        monitor.lease_token = monitor.lease_until = None
        await s.commit()
        return {'status': state, 'version': monitor.version, 'checked_at': monitor.checked_at.isoformat()}


async def run_due(limit=5):
    async with SessionLocal() as s:
        ids = list((await s.scalars(select(NewsMonitor.publication_id).join(Publication,
            Publication.id == NewsMonitor.publication_id).where(Publication.status == 'published',
                NewsMonitor.next_check_at <= chat.now(), NewsMonitor.publication_id.in_(
                    select(NewsWatch.publication_id).where(NewsWatch.enabled.is_(True))))
            .order_by(NewsMonitor.next_check_at, NewsMonitor.publication_id).limit(limit))).all())
    for pid in ids:
        await recheck(pid)
    return len(ids)


async def worker(stop):
    while not stop.is_set():
        try:
            if get_settings().scheduler_enabled:
                await run_due()
        except HTTPException as exc:
            if exc.status_code != 503:
                raise
        except Exception as exc:
            LOGGER.warning('reader_correction_tick_failed error_type=%s', type(exc).__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=60)
        except TimeoutError:
            pass
