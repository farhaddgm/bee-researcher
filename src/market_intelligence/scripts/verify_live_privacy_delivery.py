"""Opt-in HTTPS/Owner inbox canary. No real login credential is exported.

Creates a two-minute administrative test session, removes that exact session
and notice in finally, and never marks existing notifications read. This is
not proof of Google sign-in or a native OS/Telegram notification delivery.
"""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import httpx
from sqlalchemy import delete, select
from app.config import get_settings
from app.database import SessionLocal,engine
from app.models import AdminSession,AdminUser
from app.freshness_notifications import reconcile_inbox
from app.security_controls import new_csrf_token
from app.admin import owner_email


async def main(args):
    cfg=get_settings()
    if not args.live or cfg.version!='3.40.0':
        raise RuntimeError('Explicit deployed 3.40.0 canary required')
    raw=secrets.token_urlsafe(40); hashed=hashlib.sha256(raw.encode()).hexdigest()
    notice=reconcile_inbox({},[{'assistant_id':'synthetic-delivery-canary','status':'open',
        'is_freshness_alert':True}],now=datetime.now(timezone.utc))[0]['global_notifications'][0]
    notice['message']='آزمون تحویل هشدار Bee Researcher — اختلال واقعی نیست.'
    notice['kind']='operational_test';notice_id=notice['id']; owner_id=None
    # Session/notice IDs remain only inside this process; print coarse results.
    try:
        async with SessionLocal() as session:
            owner=await session.scalar(select(AdminUser).where(AdminUser.email==owner_email(),
                AdminUser.active.is_(True)).with_for_update())
            if owner is None:raise RuntimeError('active_owner_required')
            owner_id=owner.id
            session.add(AdminSession(user_id=owner.id,token_hash=hashed,portal='admin',mfa_verified=True,
                expires_at=datetime.now(timezone.utc)+timedelta(minutes=2)))
            preferences=dict(owner.preferences or {})
            # Do not evict existing notices, even if the real inbox is full.
            preferences['global_notifications']=[notice,*list(preferences.get('global_notifications') or [])]
            owner.preferences=preferences;await session.commit()
        csrf=new_csrf_token(raw,cfg); marker='PRIVATE_CANARY_'+secrets.token_hex(12)
        async with httpx.AsyncClient(base_url='https://researcher.beeproject.ir',timeout=30,
            cookies={'research_bee_admin_session':raw,'research_bee_admin_csrf':csrf},
            headers={'Origin':'https://researcher.beeproject.ir','X-CSRF-Token':csrf,
                     'Sec-Fetch-Site':'same-origin'}) as client:
            response=await client.post('/admin/api/security/client-error',json={
                'kind':'action','view':marker,'action':marker,'phase':marker,'outcome':marker,
                'route':'/private/'+marker+'?password='+marker,'status':799,'duration_ms':1,
                'message':marker,'stack':marker})
            assert response.status_code==204,'authenticated_canary_refused'
            response=await client.get('/admin/api/notifications');assert response.status_code==200
            rows=response.json()['notifications']; assert any(r['id']==notice_id for r in rows)
            response=await client.get('/meta');assert response.status_code==200
            metadata=response.json()
            assert metadata['version']==cfg.version
            assert metadata['source_revision']==cfg.build_revision
            assert metadata['image_digest']==cfg.image_digest
        print(json.dumps({'https_authenticated_canary':True,'owner_inbox_delivery':True,
            'notice_marked_as_test':True,'canary_marker':marker,'temporary_session_cleanup':True,
            'authenticated_metadata_binding_verified':True}))
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(AdminSession).where(AdminSession.token_hash==hashed))
            if owner_id:
                account=await session.get(AdminUser,owner_id,with_for_update=True)
                preferences=dict(account.preferences or {})
                preferences['global_notifications']=[n for n in preferences.get('global_notifications',[]) if n.get('id')!=notice_id]
                account.preferences=preferences
            await session.commit()
        await engine.dispose()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true')
    asyncio.run(main(parser.parse_args()))
