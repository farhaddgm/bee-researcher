"""Deterministic signals explicitly describe their bounded, published corpus."""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import func, select
from app import admin
from app.models import Publication
from app.news_chat.context import context_for, reader_report_text
from app.news_chat.models import ChatConversation, ChatGeneration
from app.reader_research.models import ResearchProfile
from app.report_language import LANGUAGES, report_copy

LOCK = 71394002


async def project(user, aid):
    available = await admin.reader_assistants(user)
    if str(aid) not in {str(a['id']) for a in available['assistants']}:
        raise HTTPException(404, 'news_unavailable')


def normalize(value):
    return re.sub(r'\s+', ' ', str(value).casefold().replace('ي', 'ی').replace('ك', 'ک')).strip()


def duplicate_key(text):
    # Publisher labels/source URLs do not make identical substantive text a
    # new report. Paraphrases are not claimed to be independent evidence.
    headings = {report_copy(lang)['source'] for lang in LANGUAGES}
    source_line = re.compile(r'^[^\w]*(?:'+'|'.join(re.escape(v) for v in headings)+r')\s*[:：]',re.I)
    lines = str(text).splitlines()
    substantive = '\n'.join(line for i,line in enumerate(lines) if not i or not source_line.match(line))
    substantive = re.sub(r'https?://\S+', '', substantive)
    return hashlib.sha256(normalize(substantive).encode()).hexdigest()


def priority(row, profile, at):
    weights = profile.weights
    stamp = datetime.fromisoformat(row.get('article_published_at') or row['published_at'])
    age = max(0, (at - stamp).total_seconds() / 3600)
    freshness = 2 ** (-age / 72)
    relevance = max(0, min(1, row.get('relevance', 0) or 0))
    matching = [v for v in profile.interests if normalize(v) in normalize(row['text'])]
    interests = min(1, len(matching) / max(1, len(profile.interests)))
    total = weights.freshness + weights.relevance + weights.interests
    score = (freshness * weights.freshness + relevance * weights.relevance + interests * weights.interests) / total
    return {'score': round(score, 6), 'age_hours': round(age, 1), 'freshness': round(freshness, 4),
            'relevance': relevance, 'matched_interests': matching, 'weights': weights.model_dump()}


def feed_signals(rows, profile, at):
    seen = {}
    result = []
    for row in rows:
        key = duplicate_key(row['text'])
        repeats = seen.get(key)
        seen.setdefault(key, row['id'])
        reasons = [v for v in profile.muted_terms if normalize(v) in normalize(row['text'])]
        result.append({**row, 'fingerprint': key, 'priority': priority(row, profile, at), 'duplicate_of': repeats,
                       'muted_terms': reasons, 'hidden': bool(reasons or (profile.hide_duplicates and repeats))})
    return result


STOP = set('the and for with from this that news report source http https www com یک این برای از به در با و را می خبر منبع'.split())


def trends(rows):
    at = datetime.now(timezone.utc)
    groups = {}
    for row in rows:
        words = set(re.findall(r'[^\W\d_]{4,}', normalize(row['title']))) - STOP
        for word in sorted(words):
            groups.setdefault(word, []).append(row)
    results = []
    for term, matches in groups.items():
        unique = {duplicate_key(r['text']): r for r in matches}
        if len(unique) < 2:
            continue
        dated = sorted(unique.values(), key=lambda r: r['published_at'])
        recent = sum(datetime.fromisoformat(r['published_at']) >= at - timedelta(days=7) for r in unique.values())
        previous = sum(at - timedelta(days=14) <= datetime.fromisoformat(r['published_at']) < at - timedelta(days=7) for r in unique.values())
        results.append({'term': term, 'mentions': len(matches), 'distinct_reports': len(unique),
                        'recent_week': recent, 'previous_week': previous,
                        'signal': 'newSignal' if recent >= 2 and previous == 0 else 'growing' if recent >= 2 and recent > previous else 'stable',
                        'sources': sorted({r['source'] for r in unique.values() if r['source']}),
                        'first_seen': dated[0]['published_at'], 'last_seen': dated[-1]['published_at'],
                        'publication_ids': [r['id'] for r in dated[-5:]],
                        'repeats': len(matches) - len(unique)})
    return sorted(results, key=lambda r: (-r['distinct_reports'], -len(r['sources']), r['term']))[:20]


async def selected_context(s, pub, user, source_ids, memory_ids, include_business, revision_ids=()):
    """Resolve selections on server; neither browser text nor hidden business data is accepted."""
    sources = source_ids or [pub.id]
    if pub.id not in sources or len(set(sources)) != len(sources):
        raise HTTPException(422, 'invalid_selection')
    pubs = list((await s.scalars(select(Publication).where(Publication.id.in_(sources),
        Publication.assistant_id == pub.assistant_id, Publication.status == 'published'))).all())
    if len(pubs) != len(sources):
        raise HTTPException(404, 'news_unavailable')
    by_id = {p.id: p for p in pubs}
    segments = []
    source_versions = {}
    complete = True
    for pid in sources:
        item = by_id[pid]
        ctx = context_for(item.message_text, item.published_at.isoformat() if item.published_at else None)
        source_versions[str(pid)] = ctx['version']
        complete = complete and ctx['complete']
        for seg in ctx['segments']:
            segments.append({'id': 'report-' + str(len(segments)), 'text': seg['text'],
                             'publication_id': str(pid), 'scope': 'published_report',
                             'published_at': (item.published_at or item.created_at).isoformat()})
    from app.reader_tools.models import NewsMonitor, NewsRevision
    correction_versions = {}
    for pid in sources:
        monitor = await s.get(NewsMonitor, pid)
        correction_versions[str(pid)] = monitor.version if monitor else 0
    evidence_versions = {}
    for pid in sources:
        matched = await s.scalar(select(func.max(NewsRevision.version)).where(NewsRevision.publication_id == pid, NewsRevision.channel == 'report', NewsRevision.after_hash == source_versions[str(pid)]))
        evidence_versions[str(pid)] = {'report': matched or 0, 'source': 0, 'report_hash': source_versions[str(pid)]}
    revision_versions = {}
    for rid in revision_ids:
        revision = await s.get(NewsRevision, rid)
        if revision is None or revision.assistant_id != pub.assistant_id or revision.publication_id not in sources:
            raise HTTPException(404, 'news_unavailable')
        revision_versions[str(rid)] = revision.after_hash
        entry=evidence_versions[str(revision.publication_id)]
        entry[revision.channel] = max(entry[revision.channel], revision.version)
        complete = complete and revision.complete
        for label, value in [('Before', revision.before_text), ('After', revision.after_text)]:
            if value:
                segments.append({'id': 'report-' + str(len(segments)),
                    'text': label + ' (observed ' + revision.created_at.isoformat() + '): ' + value[:6000],
                    'publication_id': str(revision.publication_id), 'scope': 'selected_public_source_revision' if revision.channel=='source' else 'selected_published_report_revision',
                    'published_at': revision.created_at.isoformat()})
                complete = complete and len(value) <= 6000
    memory_versions = {}
    for cid in memory_ids:
        c = await s.scalar(select(ChatConversation).where(ChatConversation.id == cid, ChatConversation.user_id == user.id,
             ChatConversation.assistant_id == pub.assistant_id, ChatConversation.saved_at.is_not(None), ChatConversation.deleted_at.is_(None)))
        if c is None or not await s.scalar(select(Publication.id).where(Publication.id == c.publication_id,
                Publication.assistant_id == pub.assistant_id, Publication.status == 'published')):
            raise HTTPException(404, 'news_unavailable')
        if c.context.get('source_ids'):
            import uuid
            visible = await s.scalar(select(func.count()).select_from(Publication).where(
                Publication.id.in_([uuid.UUID(v) for v in c.context['source_ids']]),
                Publication.assistant_id == pub.assistant_id, Publication.status == 'published'))
            if visible != len(c.context['source_ids']):
                raise HTTPException(404, 'news_unavailable')
        # Explicit bounded recent turns; disclose omitted older material.
        turns = list((await s.scalars(select(ChatGeneration).where(ChatGeneration.conversation_id == cid,
            ChatGeneration.status == 'completed').order_by(ChatGeneration.created_at.desc(), ChatGeneration.id.desc()).limit(6))).all())
        text = '\n'.join('Question: ' + t.question + '\nAnswer: ' + t.answer for t in reversed(turns))
        memory_versions[str(cid)] = hashlib.sha256(text.encode()).hexdigest()
        if len(text) > 6000 or len(turns) > 5:
            complete = False
        bounded = '\n'.join('Question: ' + t.question + '\nAnswer: ' + t.answer for t in reversed(turns[:5]))[:6000]
        if c.context.get('scope')=='voice_brief':
            text='\n'.join(str(seg.get('text','')) for seg in c.context.get('segments',[]))
            bounded=text[:6000];complete=False
            memory_versions[str(cid)]=hashlib.sha256(text.encode()).hexdigest()
        segments.append({'id': 'report-' + str(len(segments)), 'text': bounded,
                         'memory_id': str(cid), 'scope': 'selected_private_memory'})
    business = ''
    if include_business:
        profile = await s.get(ResearchProfile, (user.id, pub.assistant_id))
        business = str((profile.settings if profile else {}).get('business_context', ''))
        if not business.strip():
            raise HTTPException(422, 'business_context_required')
        segments.append({'id': 'report-' + str(len(segments)), 'text': business, 'scope': 'user_business_context'})
    data = {'scope': 'selected_research', 'complete': complete, 'published_at': None, 'segments': segments,
            'source_ids': [str(v) for v in sources], 'memory_ids': [str(v) for v in memory_ids],
            'include_business': include_business, 'source_versions': source_versions, 'memory_versions': memory_versions,
            'revision_ids': [str(v) for v in revision_ids], 'revision_versions': revision_versions, 'correction_versions': correction_versions, 'evidence_versions': evidence_versions}
    data['version'] = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return data


async def validate_context(s, c, pub, user):
    if c.context.get('scope') != 'selected_research':
        return
    import uuid
    current = await selected_context(s, pub, user, [uuid.UUID(x) for x in c.context['source_ids']],
        [uuid.UUID(x) for x in c.context['memory_ids']], c.context['include_business'], [uuid.UUID(x) for x in c.context.get('revision_ids', [])])
    if current['version'] != c.context['version']:
        raise HTTPException(409, 'context_changed')
