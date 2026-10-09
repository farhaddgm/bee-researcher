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
