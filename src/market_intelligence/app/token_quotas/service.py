"""SQL aggregates and conservative reservations share chat's admission lock.

Windows are attributed to admission time. Active work carries its reservation
across a boundary; missing provider usage stays estimated, never forgiven by
closing/deleting a conversation. Prices are independent of token counts.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import case, func, or_, select
from app.news_chat.models import ChatGeneration
from app.token_quotas.models import TokenLimit
from app.token_quotas.schemas import Limits

TIMEZONE = 'Asia/Tehran'
WINDOWS = ('six_hours', 'daily', 'monthly', 'total')
MAX_USAGE = 1_000_000_000_000


def key(aid=None, uid=None):
    return 'default' if aid is None else f'user:{aid}:{uid}' if uid is not None else f'project:{aid}'


def boundaries(at: datetime):
    local = at.astimezone(ZoneInfo(TIMEZONE))
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    next_month = month.replace(year=month.year + 1, month=1) if month.month == 12 else month.replace(month=month.month + 1)
    def utc(value):
        return value.astimezone(timezone.utc)
    return {'six_hours': (at - timedelta(hours=6), None), 'daily': (utc(day), utc(day + timedelta(days=1))),
            'monthly': (utc(month), utc(next_month)), 'total': (None, None)}


def row_view(row, aid=None, uid=None):
    return {'assistant_id': str(aid) if aid else None, 'user_id': str(uid) if uid else None,
            'inherit': row.inherit if row else aid is not None,
            'limits': Limits.model_validate(row.limits if row else {}).model_dump(),
            'version': row.version if row else 0, 'updated_at': row.updated_at.isoformat() if row else None}


async def effective(s, aid, uid):
    ids = [key(), key(aid), key(aid, uid)]
    rows = {r.id: r for r in (await s.scalars(select(TokenLimit).where(TokenLimit.id.in_(ids)))).all()}
    result, origin = Limits(), 'default'
    for scope, identity in zip(('default', 'project', 'user'), ids):
        row = rows.get(identity)
        if row and not row.inherit:
            result, origin = Limits.model_validate(row.limits), scope
    return result, origin


def actual_usage(usage):
    values = (usage.get('quota_input_tokens', usage.get('input_tokens')), usage.get('output_tokens'))
    if all(type(v) is int and 0 <= v <= MAX_USAGE for v in values):
        return values
    return None


def settle(row, usage):
    counts = actual_usage(usage)
    if counts is not None:
        row.input_tokens, row.output_tokens = counts


async def counters(s, aid, uid, at):
    g = ChatGeneration
    measured = g.input_tokens.is_not(None) & g.output_tokens.is_not(None)
    actual = case((measured, g.input_tokens + g.output_tokens), else_=0)
    reserved = case((~measured, g.reserved_tokens), else_=0)
    expressions = []
    for window, (start, _) in boundaries(at).items():
        inside = or_((g.created_at > start if window == 'six_hours' else g.created_at >= start), g.status.in_(('queued', 'running'))) if start else g.created_at <= at
        inside = inside & (g.created_at <= at)
        expressions.extend(func.coalesce(func.sum(value).filter(inside), 0) for value in (
            actual, reserved, func.coalesce(g.input_tokens, 0), func.coalesce(g.output_tokens, 0)))
        expressions.append(func.count().filter(inside))
    row = (await s.execute(select(*expressions).where(g.user_id == uid, g.assistant_id == aid))).one()
    return {window: {'actual_tokens': int(row[i*5]), 'reserved_tokens': int(row[i*5+1]),
                     'input_tokens': int(row[i*5+2]), 'output_tokens': int(row[i*5+3]), 'requests': int(row[i*5+4])}
            for i, window in enumerate(WINDOWS)}


async def admission(s, aid, uid, input_bound, max_output, at):
    limits, _ = await effective(s, aid, uid)
    if all(getattr(limits, window) is None for window in WINDOWS):
        return max_output
    counts = await counters(s, aid, uid, at)
    output = max_output
    for window in WINDOWS:
        ceiling = getattr(limits, window)
        if ceiling is None:
            continue
        available = ceiling - counts[window]['actual_tokens'] - counts[window]['reserved_tokens'] - input_bound
        output = min(output, available)
        if output < 200:
            raise HTTPException(429, {'code': 'token_quota_exhausted', 'window': window,
                                      'report_url': '/user/settings?section=report'})
    return output


async def report(s, aid, uid, at):
    limits, origin = await effective(s, aid, uid)
    counts = await counters(s, aid, uid, at)
    windows = []
    for window, (start, end) in boundaries(at).items():
        count = counts[window]
        ceiling = getattr(limits, window)
        charged = count['actual_tokens'] + count['reserved_tokens']
        windows.append({'window': window, **count, 'charged_tokens': charged, 'limit': ceiling,
                        'remaining_tokens': max(0, ceiling - charged) if ceiling is not None else None,
                        'start_at': start.isoformat() if start else None, 'reset_at': end.isoformat() if end else None})
    return {'assistant_id': str(aid), 'user_id': str(uid), 'as_of': at.isoformat(), 'timezone': TIMEZONE,
            'limit_source': origin, 'windows': windows}
