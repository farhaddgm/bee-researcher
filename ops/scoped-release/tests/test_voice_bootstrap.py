import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import provision_voice
import deploy


class VoiceBootstrapTests(unittest.TestCase):
    def test_only_new_independent_researcher_paths_with_private_modes(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(provision_voice,'ROOT',Path(temp)),patch.object(provision_voice.os,'chown') as chown:
            root=Path(temp)/'voice-bootstrap-synthetic';result=provision_voice.provision(root)
            key=Path(result['keyring_file']);state=Path(result['state_dir'])
            self.assertEqual(0o600,key.stat().st_mode&0o777);self.assertEqual(0o700,state.stat().st_mode&0o777)
            self.assertEqual(32,len(base64.b64decode(json.loads(key.read_text())['keys']['v1'])))
            self.assertFalse(result['api_key_provisioned']);self.assertEqual(3,chown.call_count)
            before=key.read_bytes()
            with self.assertRaises(FileExistsError):provision_voice.provision(root)
            self.assertEqual(before,key.read_bytes())

    def test_broad_nested_and_other_service_targets_rejected(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(provision_voice,'ROOT',Path(temp)):
            for target in [Path(temp),Path(temp)/'report',Path(temp)/'nested'/'voice-bootstrap-new',Path('/tmp/voice-bootstrap-outside')]:
                with self.assertRaises(ValueError):provision_voice.provision(target)

    def test_voice_mounts_are_independent_and_report_validation_is_reused(self):
        with patch.object(deploy,'report_volumes',return_value=[{'target':'/app/private/report-key','source':'/private/voice-ring','read_only':True},{'target':'/app/report-state','source':'/private/voice-state'}]) as check:
            mounts=deploy.voice_volumes('/private/voice-ring','/private/voice-state')
        self.assertEqual('/app/private/voice-keyring.json',mounts[0]['target']);self.assertEqual('/app/voice-state',mounts[1]['target']);check.assert_called_once()
