import base64
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1]))
spec = importlib.util.spec_from_file_location('report_provenance', Path(__file__).parents[1] / 'verify_provenance.py')
provenance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provenance)

REV = 'a' * 40
DIGEST = 'b' * 64
IMAGE = 'ghcr.io/farhaddgm/bee-researcher-market-intelligence@sha256:' + DIGEST


def result(document):
    return Mock(returncode=0, stdout=json.dumps(document))


def attestation(predicate):
    statement = {'subject': [{'digest': {'sha256': DIGEST}}], 'predicate': predicate}
    return result({'payload': base64.b64encode(json.dumps(statement).encode()).decode()})


class ProvenanceTests(unittest.TestCase):
    def test_all_signed_claims_are_required_and_no_checks_are_bypassed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'market-intelligence-release-trace.json').write_text(json.dumps({'image': IMAGE, 'commit': REV}))
            results = [result([{'critical': {'image': {'docker-manifest-digest': 'sha256:' + DIGEST}}}]),
                attestation({'Data': json.dumps({'source_repository': 'farhaddgm/bee-researcher', 'source_commit': REV, 'image_digest': 'sha256:' + DIGEST})}),
                attestation({'bomFormat': 'CycloneDX'})]
            with patch.object(provenance.subprocess, 'run', side_effect=results) as run, patch.object(provenance, 'save') as save:
                proof = provenance.verify(root, REV, '3.41.0', Path('/synthetic/cosign'))
            self.assertTrue(all(proof[key] for key in ('signature', 'build_binding', 'sbom')))
            self.assertFalse(proof['verification_bypass_used'])
            self.assertEqual(run.call_count, 3)
            for call in run.call_args_list:
                command = call.args[0]
                self.assertIn('--certificate-github-workflow-sha', command)
                self.assertIn(REV, command)
                self.assertFalse(any('ignore' in str(arg) or 'insecure' in str(arg) for arg in command))
            save.assert_called_once()

    def test_failed_certificate_or_wrong_repository_never_records_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / 'market-intelligence-release-trace.json'
            for image in (IMAGE, IMAGE.replace('bee-researcher', 'bee-consultant')):
                trace.write_text(json.dumps({'image': image, 'commit': REV}))
                with patch.object(provenance.subprocess, 'run', return_value=Mock(returncode=1)) as run, patch.object(provenance, 'save') as save:
                    with self.assertRaises(RuntimeError):
                        provenance.verify(root, REV, '3.41.0', Path('/synthetic/cosign'))
                    save.assert_not_called()
                    self.assertEqual(run.call_count, 1 if image == IMAGE else 0)
