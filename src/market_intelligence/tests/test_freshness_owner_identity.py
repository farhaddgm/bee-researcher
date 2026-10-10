from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from app.freshness_notifications import deliver_freshness_notifications


class CanonicalOwnerDeliveryTest(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, configured_email, *, active=True, locked_email='syntheticowner@gmail.com'):
        uid = uuid.uuid4()
        owner = SimpleNamespace(id=uid, active=True, email='syntheticowner@gmail.com')
        account = SimpleNamespace(id=uid, active=active, email=locked_email,
                                  role='admin', username='owner', preferences={'theme': 'honey'})
        read, write = MagicMock(), MagicMock()
        for session in (read, write):
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=False)
        read.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: [owner]))
        write.get = AsyncMock(return_value=account)
        write.commit = AsyncMock()
        incidents = AsyncMock(return_value={'incidents': [
            {'assistant_id': 'synthetic-project', 'status': 'open', 'is_freshness_alert': True}]})
        with patch('app.freshness_notifications.SessionLocal', side_effect=[read, write]), \
                patch('app.admin.get_settings', return_value=SimpleNamespace(owner_email=configured_email)), \
                patch('app.admin.list_admin_incidents', incidents):
            # Admission/leases are independently integration-tested. Isolate
            # canonical selection and the locked authorization recheck here.
            count = await deliver_freshness_notifications.__wrapped__()
        bound = read.scalars.await_args.args[0].compile().params.values()
        self.assertIn('syntheticowner@gmail.com', bound)
        return count, account, write

    async def test_gmail_dots_plus_and_googlemail_use_login_canonical_identity(self):
        count, account, write = await self.exercise('Synthetic.Owner+Alerts@googlemail.com')
        self.assertEqual(1, count)
        self.assertEqual('honey', account.preferences['theme'])
        self.assertEqual(1, len(account.preferences['global_notifications']))
        write.commit.assert_awaited_once()

    async def test_already_canonical_owner_delivers_normally(self):
        count, _, write = await self.exercise('syntheticowner@gmail.com')
        self.assertEqual(1, count)
        write.commit.assert_awaited_once()

    async def test_deactivation_after_selection_is_rechecked_under_lock(self):
        count, account, write = await self.exercise('Synthetic.Owner@gmail.com', active=False)
        self.assertEqual(0, count)
        self.assertEqual({'theme': 'honey'}, account.preferences)
        write.commit.assert_not_awaited()

    async def test_reassigned_email_or_legacy_owner_username_never_grants_ownership(self):
        count, account, write = await self.exercise('Synthetic.Owner@gmail.com', locked_email='other@example.test')
        self.assertEqual(0, count)
        self.assertEqual({'theme': 'honey'}, account.preferences)
        write.commit.assert_not_awaited()
