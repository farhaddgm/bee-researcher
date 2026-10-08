import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import urllib.error
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("release_controller", Path(__file__).parents[1] / "deploy.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
REV = "a" * 40
REF = "ghcr.io/farhaddgm/bee-researcher-market-intelligence@sha256:" + "b" * 64


class ScopedReleaseTests(unittest.TestCase):
    def test_rejects_other_repositories_and_mutable_tags_before_docker(self):
        for ref in ("latest", REF.replace("bee-researcher", "bee-consultant"), REF.split("@")[0] + ":latest"):
            with patch.object(release, "inspect") as inspect:
                with self.assertRaises(ValueError):
                    release.candidate(ref, REV, "3.39.1")
                inspect.assert_not_called()

    def test_image_revision_and_version_must_both_match(self):
        for revision, version in (("c" * 40, "3.39.1"), (REV, "3.39.0")):
            image = {"Id": "image-id", "Config": {"Labels": {
                "org.opencontainers.image.revision": revision, "org.opencontainers.image.version": version}}}
            with patch.object(release, "inspect", return_value=image):
                with self.assertRaises(RuntimeError):
                    release.candidate(REF, REV, "3.39.1")

    def test_verified_image_is_returned(self):
        image = {"Id": "image-id", "Config": {"Labels": {
            "org.opencontainers.image.revision": REV, "org.opencontainers.image.version": "3.39.1"}}}
        with patch.object(release, "inspect", return_value=image):
            self.assertEqual(release.candidate(REF, REV, "3.39.1"), "image-id")

    def test_compose_is_scoped_and_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "base.yml", root / "existing.json"
            first.touch()
            second.touch()
            current = {"Config": {"Labels": {"com.docker.compose.project": "ai-assistant",
                "com.docker.compose.project.config_files": f"{first},{second}"}}}
            with patch.object(release, "ROOT", root):
                command = release.compose_command(current, root / "candidate.json")
                self.assertEqual(command.count("-f"), 3)
                self.assertIn(str(second), command)
                current["Config"]["Labels"]["com.docker.compose.project.config_files"] = "/etc/passwd"
                with self.assertRaises(RuntimeError):
                    release.compose_command(current)

    def test_receipts_cannot_overwrite_and_private_files_are_0600(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "runtime.env"
            release.save(target, "synthetic", private=True)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                release.save(target, "replacement", private=True)
            self.assertEqual(target.read_text(), "synthetic")

    def test_subprocess_failure_never_echoes_private_output(self):
        result = Mock(returncode=1, stdout="private runtime", stderr="private secret")
        with patch.object(release.subprocess, "run", return_value=result):
            with self.assertRaises(RuntimeError) as error:
                release.run(["docker", "inspect"])
            self.assertNotIn("private", str(error.exception))

    def test_health_checks_public_version_and_running_commit(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({"version": "3.39.1"}).encode()
        container = {"State": {"Health": {"Status": "healthy"}}, "Config": {"Labels": {"org.opencontainers.image.revision": REV}}}
        with patch.object(release, "inspect", return_value=container), patch.object(release.urllib.request, "urlopen", return_value=response):
            release.wait_health(REV, "3.39.1")
            with self.assertRaises(RuntimeError):
                release.wait_health("d" * 40, "3.39.1")

    def test_transient_starting_readiness_is_retried_not_rolled_back(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({"version": "3.39.1"}).encode()
        container = {"State": {"Health": {"Status": "healthy"}}, "Config": {"Labels": {"org.opencontainers.image.revision": REV}}}
        starting = urllib.error.HTTPError("https://researcher.beeproject.ir/ready", 503, "starting", {}, None)
        with patch.object(release, "inspect", return_value=container), patch.object(release.time, "sleep"), \
                patch.object(release.urllib.request, "urlopen", side_effect=[response, starting, response, response]) as request:
            release.wait_health(REV, "3.39.1", timeout=5)
            self.assertEqual(request.call_count, 4)

    def test_liveness_only_gate_does_not_require_a_blocked_scheduler_heartbeat(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({"version": "3.39.1"}).encode()
        container = {"State": {"Health": {"Status": "healthy"}}, "Config": {"Labels": {"org.opencontainers.image.revision": REV}}}
        with patch.object(release, "inspect", return_value=container), patch.object(release.urllib.request, "urlopen", return_value=response) as request:
            release.wait_health(REV, "3.39.1", ready_required=False)
            request.assert_called_once_with("https://researcher.beeproject.ir/health", timeout=15)

    def test_atomic_cutover_releases_admission_before_full_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ops/bee-researcher-direct/artifacts").mkdir(parents=True)
            (root / "ops/bee-researcher-direct/private").mkdir(parents=True)
            current = {"Image": "old-image", "Config": {"User": "market-intelligence", "Labels": {
                "org.opencontainers.image.version": "3.39.0", "org.opencontainers.image.revision": REV}, "Env": [
                "MARKET_INTELLIGENCE_POSTGRES_USER=bee_researcher_runtime", "MARKET_INTELLIGENCE_DEPLOYMENT_DRAIN_ENABLED=true"]},
                "HostConfig": {"ReadonlyRootfs": True, "CapDrop": ["ALL"]}}
            live = {"Image": "new-image", "Config": {"User": "market-intelligence"}}
            controller = Mock(returncode=0)
            controller.stdout.readline.return_value = "RESEARCHER_DRAINED\n"
            controller.poll.return_value = 0
            gate = {"closed": True}
            observations = []

            def released(*args, **kwargs):
                gate["closed"] = False

            def readiness(*args, ready_required=True, **kwargs):
                observations.append((ready_required, gate["closed"]))
                if ready_required and gate["closed"]:
                    raise AssertionError("scheduler heartbeat cannot succeed while admission is closed")

            controller.communicate.side_effect = released
            args = SimpleNamespace(image=REF, revision=REV, version="3.39.1", expected_current_revision=REV)
            with patch.object(release, "ROOT", root), patch.object(release, "candidate", return_value="new-image"), \
                    patch.object(release, "inspect", side_effect=[current, {"State": {"ExitCode": 0}}, live]), \
                    patch.object(release, "compose_command", return_value=["docker", "compose"]), \
                    patch.object(release, "run", return_value=""), patch.object(release, "wait_health", side_effect=readiness), \
                    patch.object(release.subprocess, "Popen", return_value=controller), \
                    patch.object(release.select, "select", return_value=([controller.stdout], [], [])):
                release.deploy(args)
            self.assertEqual(observations, [(False, True), (True, False)])
            controller.communicate.assert_called_once_with("release\n", timeout=30)


if __name__ == "__main__":
    unittest.main()
