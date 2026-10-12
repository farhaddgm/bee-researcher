from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch
import uuid
from fastapi import HTTPException
from pydantic import ValidationError
from app.token_quotas import api, service
from app.token_quotas.schemas import Limits, SaveLimit


class TokenQuotaTests(TestCase):
    def test_strict_counts_reject_boolean_fraction_negative_and_extra(self):
        for value in (True, -1, 1.5, '100', 1_000_000_000_001):
            with self.assertRaises(ValidationError):
                Limits(daily=value)
        with self.assertRaises(ValidationError):
            Limits(hourly=12)
        self.assertEqual(Limits(daily=0).daily, 0)
        self.assertIsNone(Limits().daily)

    def test_scope_cannot_target_user_without_project_or_inherit_global(self):
        for data in ({'user_id': uuid.uuid4()}, {'inherit': True}):
            with self.assertRaises(ValidationError):
                SaveLimit(limits=Limits(), version=0, **data)

    def test_tehran_day_month_and_year_boundary(self):
        at = datetime(2026, 12, 31, 21, 15, tzinfo=timezone.utc)
        boundaries = service.boundaries(at)
        self.assertEqual(boundaries['six_hours'][0], at-timedelta(hours=6))
        self.assertEqual(boundaries['daily'][0], datetime(2026,12,31,20,30,tzinfo=timezone.utc))
        self.assertEqual(boundaries['monthly'][1], datetime(2027,1,31,20,30,tzinfo=timezone.utc))
        self.assertEqual(boundaries['total'], (None, None))

    def test_raw_cache_tokens_are_separate_from_cost_weighting(self):
        self.assertEqual(service.actual_usage({'input_tokens':14, 'quota_input_tokens':12, 'output_tokens':5}), (12,5))
        for usage in ({}, {'input_tokens':True,'output_tokens':1}, {'input_tokens':1,'output_tokens':-1}, {'input_tokens':1,'output_tokens':None}):
            self.assertIsNone(service.actual_usage(usage))

    def test_private_request_text_never_appears_in_usage(self):
        row = SimpleNamespace(id=uuid.uuid4(), created_at=datetime.now(timezone.utc), status='completed',
            model={'provider':'openai','label':'Test'}, input_tokens=4, output_tokens=7, reserved_tokens=100,
            question='PRIVATE_QUESTION',answer='PRIVATE_ANSWER',session_hash='SECRET')
        result=api.usage_view(row)
        self.assertEqual(result['reserved_tokens'],0)
        self.assertNotIn('PRIVATE',str(result))
        self.assertNotIn('SECRET',str(result))


class TokenQuotaAsyncTests(IsolatedAsyncioTestCase):
    async def test_owner_is_email_identity_in_each_portal(self):
        actor=SimpleNamespace(email='not-the-owner@gmail.com',role='admin',username='owner')
        for path in ('/admin/api/token-quotas','/user/api/token-quotas/owner'):
            with patch.object(api.admin,'current_admin',AsyncMock(return_value=actor)),patch.object(api.admin,'current_reader',AsyncMock(return_value=actor)):
                with self.assertRaises(HTTPException) as exc:
                    await api.owner(SimpleNamespace(url=SimpleNamespace(path=path)), 'admin','user')
                self.assertEqual(exc.exception.status_code,403)

    async def test_all_four_windows_enforced_and_output_reduced(self):
        for window in service.WINDOWS:
            counts={k:{'actual_tokens':20,'reserved_tokens':30} for k in service.WINDOWS}
            limits=Limits(**{window:500})
            with patch.object(service,'effective',AsyncMock(return_value=(limits,'user'))),patch.object(service,'counters',AsyncMock(return_value=counts)):
                self.assertEqual(await service.admission(None,None,None,100,1200,datetime.now(timezone.utc)),350)
                with self.assertRaises(HTTPException) as exc:
                    await service.admission(None,None,None,300,1200,datetime.now(timezone.utc))
                self.assertEqual(exc.exception.detail['window'],window)
                self.assertEqual(exc.exception.status_code,429)

    async def test_unlimited_skips_aggregate_but_zero_blocks(self):
        at=datetime.now(timezone.utc)
        with patch.object(service,'effective',AsyncMock(return_value=(Limits(),'default'))),patch.object(service,'counters',AsyncMock()) as counts:
            self.assertEqual(await service.admission(None,None,None,100,1200,at),1200)
            counts.assert_not_awaited()
        with patch.object(service,'effective',AsyncMock(return_value=(Limits(total=0),'default'))),patch.object(service,'counters',AsyncMock(return_value={w:{'actual_tokens':0,'reserved_tokens':0} for w in service.WINDOWS})):
            with self.assertRaises(HTTPException):
                await service.admission(None,None,None,1,1200,at)

    async def test_inheritance_and_unlimited_override(self):
        aid,uid=uuid.uuid4(),uuid.uuid4()
        rows=[SimpleNamespace(id=service.key(),limits={'daily':10},inherit=False),
              SimpleNamespace(id=service.key(aid),limits={'daily':20},inherit=False),
              SimpleNamespace(id=service.key(aid,uid),limits={'daily':None},inherit=False)]
        session=SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda:rows)))
        limits,origin=await service.effective(session,aid,uid)
        self.assertEqual((limits.daily,origin),(None,'user'))
        rows[-1].inherit=True
        limits,origin=await service.effective(session,aid,uid)
        self.assertEqual((limits.daily,origin),(20,'project'))
        rows[1].inherit=True
        limits,origin=await service.effective(session,aid,uid)
        self.assertEqual((limits.daily,origin),(10,'default'))
