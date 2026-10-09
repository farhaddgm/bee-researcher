import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))
spec = importlib.util.spec_from_file_location('scoped_migration', Path(__file__).parents[1] / 'migrate_news_chat.py')
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class MigrationScopeTests(unittest.TestCase):
    def identities(self):
        prefix='MARKET_INTELLIGENCE_POSTGRES_'
        base={prefix+'HOST':'synthetic-researcher-db',prefix+'DB':'assistant',prefix+'PORT':'5432'}
        return ({**base,prefix+'USER':'bee_researcher_migrator',prefix+'PASSWORD':'synthetic-migrator'},
                {**base,prefix+'USER':'bee_researcher_runtime',prefix+'PASSWORD':'synthetic-reader',
                 'UNRELATED_APP_PASSWORD':'never-read-this'})

    def test_backup_uses_existing_runtime_reader_not_ddl_or_other_app_credentials(self):
        migrator,runtime=self.identities()
        actual=migration.scoped_backup_values(migrator,runtime)
        self.assertEqual(actual,{'PGHOST':'synthetic-researcher-db','PGDATABASE':'assistant',
                                'PGPORT':'5432','PGUSER':'bee_researcher_runtime','PGPASSWORD':'synthetic-reader'})
        del migrator['MARKET_INTELLIGENCE_POSTGRES_PORT']
        del runtime['MARKET_INTELLIGENCE_POSTGRES_PORT']
        self.assertEqual(migration.scoped_backup_values(migrator,runtime)['PGPORT'],'5432')

    def test_backup_refuses_administrator_foreign_database_host_or_port(self):
        migrator,runtime=self.identities()
        for suffix,value in [('USER','postgres'),('DB','contenter'),('HOST','other-app-db'),('PORT','5433')]:
            with self.subTest(suffix=suffix):
                with self.assertRaises(RuntimeError):
                    migration.scoped_backup_values(migrator,{**runtime,'MARKET_INTELLIGENCE_POSTGRES_'+suffix:value})

    def test_backup_refuses_missing_or_multiline_values_without_disclosing_them(self):
        migrator,runtime=self.identities()
        for value in ('','PRIVATE_BACKUP_CANARY\nOTHER_PASSWORD=injected','PRIVATE_BACKUP_CANARY\rtest'):
            with self.subTest(value=value):
                with self.assertRaises(RuntimeError) as error:
                    migration.scoped_backup_values(migrator,{**runtime,'MARKET_INTELLIGENCE_POSTGRES_PASSWORD':value})
                self.assertNotIn('PRIVATE_BACKUP_CANARY',str(error.exception))

    def test_only_private_researcher_migrator_and_database_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.env'
            for role, database in [('other_project', 'assistant'), ('bee_researcher_migrator', 'contenter')]:
                path.write_text(f'MARKET_INTELLIGENCE_POSTGRES_USER={role}\nMARKET_INTELLIGENCE_POSTGRES_DB={database}\n')
                path.chmod(0o600)
                with self.assertRaisesRegex(RuntimeError, 'Researcher-only'):
                    migration.migration_values(path)
            path.write_text('MARKET_INTELLIGENCE_POSTGRES_USER=bee_researcher_migrator\nMARKET_INTELLIGENCE_POSTGRES_DB=assistant\n')
            self.assertEqual(migration.migration_values(path)['MARKET_INTELLIGENCE_POSTGRES_DB'], 'assistant')

    def test_shared_readable_or_missing_credentials_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.env'
            with self.assertRaisesRegex(RuntimeError, 'private migrator'):
                migration.migration_values(path)
            path.write_text('synthetic=fixture\n')
            path.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError, 'private migrator'):
                migration.migration_values(path)
