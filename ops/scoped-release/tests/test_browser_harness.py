import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('browser_harness', Path(__file__).parents[1] / 'verify_news_chat.py')
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


class BrowserHarnessTests(unittest.TestCase):
    def test_real_startup_fixture_reproduces_compose_ready_bound_healthcheck(self):
        options=harness.startup_healthcheck_options()
        command=options[options.index('--health-cmd')+1]
        self.assertIn('/ready',command)
        self.assertNotIn('/health',command)
        self.assertEqual(options[options.index('--health-interval')+1],'15s')
        self.assertEqual(options[options.index('--health-retries')+1],'10')

    def test_dependency_mount_is_sibling_not_child_of_readonly_source(self):
        arguments = harness.browser_mounts(Path('/tmp/synthetic-tools/node_modules'))
        self.assertEqual(arguments[1], '/harness/source')
        self.assertIn('/tmp/synthetic-tools/node_modules:/harness/node_modules:ro', arguments)
        self.assertNotIn('/tmp/synthetic-tools/node_modules:/harness/source/node_modules:ro', arguments)

    def test_installer_uses_callers_uid_gid_without_credentials(self):
        with patch.object(harness.os, 'getuid', return_value=1234), patch.object(harness.os, 'getgid', return_value=5678):
            options = harness.installer_options('/tmp/synthetic-tools')
        self.assertEqual(options[:2], ['--user', '1234:5678'])
        self.assertIn('npm_config_cache=/tmp/bee-npm-cache', options)
        self.assertIn('/tmp/synthetic-tools:/tools', options)
