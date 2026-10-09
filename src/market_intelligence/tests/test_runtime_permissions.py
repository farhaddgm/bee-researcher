from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from app import runtime_permissions as preflight


class RuntimePermissionTests(unittest.IsolatedAsyncioTestCase):
    async def check(self, *, revision='0045_news_chat', admin=False, create=False,
                    journal_write=False, missing=None, environment='production'):
        connection=MagicMock()
        connection.execute=AsyncMock(return_value=SimpleNamespace(one=lambda:(admin,False,False,False,False)))
        async def scalar(statement, params=None):
            sql=str(statement)
            if 'has_schema_privilege' in sql:return create
            if 'version_num' in sql:return revision
            if 'security_events' in sql:return journal_write
            return (params['table'],params['permission'])!=missing
        connection.scalar=AsyncMock(side_effect=scalar)
        engine=MagicMock()
        engine.connect.return_value.__aenter__=AsyncMock(return_value=connection)
        engine.connect.return_value.__aexit__=AsyncMock(return_value=False)
        engine.dispose=AsyncMock()
        with patch.object(preflight,'get_settings',return_value=SimpleNamespace(environment=environment)), \
                patch.object(preflight,'engine',engine):
            try:
                await preflight.check_runtime_permissions()
            finally:
                if environment=='production':engine.dispose.assert_awaited_once()
        return connection

    def test_packaged_head_is_derived_from_actual_image_migrations(self):
        self.assertEqual(preflight.packaged_schema_head(),'0045_news_chat')

    async def test_restricted_production_with_all_individual_grants_starts(self):
        connection=await self.check()
        checks=[call.args[1] for call in connection.scalar.await_args_list if len(call.args)>1 and 'table' in call.args[1]]
        self.assertEqual(len(checks),12)
        self.assertEqual({p['permission'] for p in checks},{'SELECT','INSERT','UPDATE','DELETE'})

    async def test_old_or_unknown_schema_is_refused(self):
        for revision in ('0044_security_events','unknown',None):
            with self.assertRaisesRegex(RuntimeError,'separate migration'):
                await self.check(revision=revision)

    async def test_admin_or_schema_owner_is_refused(self):
        for kwargs in ({'admin':True},{'create':True}):
            with self.assertRaises(RuntimeError):await self.check(**kwargs)

    async def test_security_history_cannot_be_rewritten(self):
        with self.assertRaisesRegex(RuntimeError,'append security'):
            await self.check(journal_write=True)

    async def test_any_missing_chat_grant_is_refused(self):
        for table in ('news_chat_policy','news_chat_conversations','news_chat_generations'):
            for permission in ('SELECT','INSERT','UPDATE','DELETE'):
                with self.assertRaisesRegex(RuntimeError,'chat table privileges'):
                    await self.check(missing=('market_intelligence.'+table,permission))

    async def test_synthetic_unit_environment_does_not_require_live_database(self):
        connection=await self.check(environment='test')
        connection.scalar.assert_not_awaited()
