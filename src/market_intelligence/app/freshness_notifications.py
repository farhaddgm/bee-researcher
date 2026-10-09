"""Durable Owner inbox delivery; one notice per outage, not per poll.

Uses the existing in-app notification channel. No unconfigured Telegram/email
destination is invented and no publication channel receives operational tests.
"""
from datetime import datetime, timezone
import uuid
from sqlalchemy import select
from app.config import get_settings
from app.database import SessionLocal
from app.models import AdminUser


def reconcile_inbox(preferences: dict, incidents: list[dict], *, now: datetime) -> tuple[dict, int]:
    preferences = dict(preferences)
    previous = dict(preferences.get('freshness_delivery') or {})
    current = {str(item['assistant_id']): str(item.get('last_success_at') or 'never')
               for item in incidents if item.get('is_freshness_alert') and item.get('status') == 'open'}
    inbox = list(preferences.get('global_notifications') or [])
    delivered = 0
    for aid, fingerprint in current.items():
        if previous.get(aid) == fingerprint:
            continue
        inbox.insert(0, {'id':str(uuid.uuid4()),'assistant_id':aid,'created_at':now.isoformat(),
                        'read':False,'message':'جمع‌آوری و تحلیل اخبار به تأخیر افتاده است.',
                        'message_key':'collection_stale','severity':'warning','suggested_action':'freshness'})
        delivered += 1
    for aid in previous.keys() - current.keys():
        inbox.insert(0, {'id':str(uuid.uuid4()),'assistant_id':aid,'created_at':now.isoformat(),
                        'read':False,'message':'جمع‌آوری و تحلیل اخبار دوباره برقرار شد.',
                        'message_key':'collection_recovered','severity':'info','suggested_action':'freshness'})
        delivered += 1
    preferences['freshness_delivery'] = current
    preferences['global_notifications'] = inbox[:100]
    return preferences, delivered


async def deliver_freshness_notifications() -> int:
    from app.admin import list_admin_incidents
    async with SessionLocal() as session:
        owners = (await session.scalars(select(AdminUser).where(
            AdminUser.active.is_(True), AdminUser.email == get_settings().owner_email))).all()
    total = 0
    for owner in owners:
        incidents = await list_admin_incidents(owner)
        rows = incidents.get('incidents')
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise RuntimeError('invalid_freshness_incidents')
        async with SessionLocal() as session:
            account = await session.get(AdminUser, owner.id, with_for_update=True)
            if account is None or not account.active or account.email != get_settings().owner_email:
                continue
            updated, count = reconcile_inbox(account.preferences or {}, rows, now=datetime.now(timezone.utc))
            if updated != (account.preferences or {}):
                account.preferences = updated
                await session.commit()
            total += count
    return total
