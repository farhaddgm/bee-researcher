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
    def test_new_release_restores_verified_image_cmd_not_inherited_rollback(self):
        image={"Config":{"Cmd":["./start-service.sh"]}}
        with patch.object(release,'inspect',return_value=image) as inspect:
            service=release.production_service(REF,{"MARKET_INTELLIGENCE_VERSION":"3.40.0"})
        inspect.assert_called_once_with(REF)
        self.assertEqual(service['command'],['./start-service.sh'])
        self.assertEqual(service['image'],REF)
        self.assertEqual(service['environment']['MARKET_INTELLIGENCE_VERSION'],'3.40.0')

    def test_missing_candidate_cmd_is_refused_before_cutover(self):
        for command in (None,[],"./start-service.sh",[None],[""]):
            with patch.object(release,'inspect',return_value={"Config":{"Cmd":command}}):
                with self.assertRaisesRegex(RuntimeError,'explicit startup command'):
                    release.production_service(REF,{})

    def test_legacy_rollback_keeps_auth_and_forward_schema_without_migrating(self):
        current={"Image":"old-image","Config":{"Labels":{"org.opencontainers.image.version":"3.39.1"}}}
        service=release.rollback_service(current,{"MARKET_INTELLIGENCE_VERSION":"3.39.1"},"3.40.0")
        self.assertIn('python -m app.auth_deployment',service['command'][-1])
        self.assertIn('exec uvicorn',service['command'][-1])
        self.assertNotIn('alembic',service['command'][-1])
        self.assertNotIn('runtime_permissions',service['command'][-1])
        self.assertEqual(service['environment']['MARKET_INTELLIGENCE_VERSION'],'3.39.1')
        self.assertNotIn('command',release.rollback_service(current,{},'3.39.1'))

    def test_runtime_preflight_uses_verified_candidate_and_scoped_private_env(self):
        with patch.object(release,'run') as run:
            release.runtime_preflight(REF,Path('/private/synthetic.env'))
        command=run.call_args.args[0]
        self.assertIn(REF,command)
        self.assertIn('/private/synthetic.env',command)
        self.assertIn('app.runtime_permissions',command)
        self.assertIn('--read-only',command)
        self.assertIn('no-new-privileges:true',command)

    def test_compose_interpolation_uses_only_own_actual_runtime(self):
        current = {"Image": "sha256:previous", "Config": {"Env": [
            "MARKET_INTELLIGENCE_GOOGLE_CLIENT_SECRET=synthetic$literal",
            "MARKET_INTELLIGENCE_VERSION=3.39.0", "UNRELATED_SECRET=not-copied"]}}
        with patch.dict(release.os.environ, {"MARKET_INTELLIGENCE_VERSION": "wrong-shared-env"}, clear=True):
            environment = release.compose_environment(current)
        self.assertEqual(environment["MARKET_INTELLIGENCE_VERSION"], "3.39.0")
        self.assertEqual(environment["MARKET_INTELLIGENCE_GOOGLE_CLIENT_SECRET"], "synthetic$literal")
        self.assertEqual(environment["BEE_SCOPED_IMAGE"], "sha256:previous")
        self.assertNotIn("UNRELATED_SECRET", environment)

    def test_clean_uvicorn_sigterm_requires_both_completion_markers(self):
        stopped = {"Id": "synthetic-container", "State": {"Running": False, "OOMKilled": False, "ExitCode": 143}}
        result = Mock(returncode=0, stdout="", stderr="INFO:     Application shutdown complete.\nINFO:     Finished server process [1]\n")
        with patch.object(release.subprocess, "run", return_value=result) as process:
            self.assertEqual(release.verify_shutdown(stopped, "2026-10-08T00:00:00Z")["exit_code"], 143)
        self.assertIn("--since", process.call_args.args[0])
        self.assertIn(stopped["Id"], process.call_args.args[0])

    def test_zero_or_sigterm_without_shutdown_evidence_is_not_success(self):
        for code in (0, 143):
            for output in ("", "INFO:     Application shutdown complete.\n", "INFO:     Finished server process [1]\n"):
                stopped = {"Id": "synthetic", "State": {"ExitCode": code}}
                with patch.object(release.subprocess, "run", return_value=Mock(returncode=0, stdout=output, stderr="")):
                    with self.assertRaisesRegex(RuntimeError, "evidence missing"):
                        release.verify_shutdown(stopped, "2026-10-08T00:00:00Z")

    def test_sigkill_oom_and_other_failures_are_never_clean_shutdown(self):
        for state in ({"ExitCode": 137}, {"ExitCode": 1}, {"ExitCode": 143, "OOMKilled": True},
                      {"ExitCode": 0, "Running": True}, {"ExitCode": 143, "Error": "synthetic"}):
            with patch.object(release.subprocess, "run") as process:
                with self.assertRaisesRegex(RuntimeError, "did not finish"):
                    release.verify_shutdown({"Id": "synthetic", "State": state}, "2026-10-08T00:00:00Z")
                process.assert_not_called()

    def test_uvicorn_auto_lifespan_fallback_is_not_success_even_with_markers(self):
        markers = "INFO:     Application shutdown complete.\nINFO:     Finished server process [1]\n"
        for error in ("INFO:     ASGI 'lifespan' protocol appears unsupported.\n",
                      "ERROR:    Application shutdown failed.\n", "Traceback (most recent call last):\n"):
            result = Mock(returncode=0, stdout="", stderr=error + markers)
            with patch.object(release.subprocess, "run", return_value=result):
                with self.assertRaisesRegex(RuntimeError, "evidence missing"):
                    release.verify_shutdown({"Id": "synthetic", "State": {"ExitCode": 143}}, "2026-10-08T00:00:00Z")

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
        container = {"State": {"Running": True, "Health": {"Status": "healthy"}}, "Config": {"Labels": {"org.opencontainers.image.revision": REV}}}
        with patch.object(release, "inspect", return_value=container), patch.object(release.urllib.request, "urlopen", return_value=response):
            release.wait_health(REV, "3.39.1")
            with self.assertRaises(RuntimeError):
                release.wait_health("d" * 40, "3.39.1")

    def test_transient_starting_readiness_is_retried_not_rolled_back(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({"version": "3.39.1"}).encode()
        container = {"State": {"Running": True, "Health": {"Status": "healthy"}}, "Config": {"Labels": {"org.opencontainers.image.revision": REV}}}
        starting = urllib.error.HTTPError("https://researcher.beeproject.ir/ready", 503, "starting", {}, None)
        with patch.object(release, "inspect", return_value=container), patch.object(release.time, "sleep"), \
                patch.object(release.urllib.request, "urlopen", side_effect=[response, starting, response, response]) as request:
            release.wait_health(REV, "3.39.1", timeout=5)
            self.assertEqual(request.call_count, 4)

    def test_transient_reverse_proxy_errors_retry_liveness_and_final_readiness(self):
        container={"State":{"Running":True,"Health":{"Status":"healthy"}},"Config":{"Labels":{"org.opencontainers.image.revision":REV}}}
        response=Mock()
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=False)
        response.read.return_value=json.dumps({"version":"3.40.0"}).encode()
        for code in (502,503,504):
            for required in (False,True):
                failure=urllib.error.HTTPError('https://researcher.beeproject.ir/health',code,'synthetic gateway',{},None)
                with patch.object(release,'inspect',return_value=container),patch.object(release.time,'sleep') as sleep, \
                        patch.object(release.urllib.request,'urlopen',side_effect=[failure,response,response]) as request:
                    release.wait_health(REV,'3.40.0',timeout=5,ready_required=required)
                self.assertEqual(request.call_count,3 if required else 2)
                sleep.assert_called_once_with(2)

    def test_reverse_proxy_retry_uses_existing_deadline_not_an_unbounded_loop(self):
        container={"State":{"Running":True,"Health":{"Status":"healthy"}},"Config":{"Labels":{"org.opencontainers.image.revision":REV}}}
        failure=urllib.error.HTTPError('https://researcher.beeproject.ir/health',502,'synthetic gateway',{},None)
        with patch.object(release,'inspect',return_value=container),patch.object(release.time,'sleep'), \
                patch.object(release.time,'monotonic',side_effect=[0,0,2]),patch.object(release.urllib.request,'urlopen',side_effect=failure) as request:
            with self.assertRaises(TimeoutError):release.wait_health(REV,'3.40.0',timeout=1,ready_required=False)
        self.assertEqual(request.call_count,1)

    def test_auth_route_rate_limit_and_server_bug_are_not_transient_startup(self):
        container={"State":{"Running":True,"Health":{"Status":"healthy"}},"Config":{"Labels":{"org.opencontainers.image.revision":REV}}}
        for code in (401,403,404,429,500):
            failure=urllib.error.HTTPError('https://researcher.beeproject.ir/health',code,'synthetic failure',{},None)
            with patch.object(release,'inspect',return_value=container),patch.object(release.time,'sleep') as sleep, \
                    patch.object(release.urllib.request,'urlopen',side_effect=failure):
                with self.assertRaises(urllib.error.HTTPError):release.wait_health(REV,'3.40.0',ready_required=False)
            sleep.assert_not_called()

    def test_wrong_public_version_is_never_accepted_or_retried(self):
        container={"State":{"Running":True,"Health":{"Status":"healthy"}},"Config":{"Labels":{"org.opencontainers.image.revision":REV}}}
        response=Mock()
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=False)
        response.read.return_value=json.dumps({"version":"3.39.1"}).encode()
        with patch.object(release,'inspect',return_value=container),patch.object(release.time,'sleep') as sleep, \
                patch.object(release.urllib.request,'urlopen',return_value=response):
            with self.assertRaisesRegex(RuntimeError,'wrong version'):release.wait_health(REV,'3.40.0',ready_required=False)
        sleep.assert_not_called()

    def test_liveness_only_gate_does_not_require_a_blocked_scheduler_heartbeat(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({"version": "3.39.1"}).encode()
        container = {"State": {"Running": True, "Health": {"Status": "starting"}}, "Config": {"Labels": {"org.opencontainers.image.revision": REV},"Healthcheck":{"Test":["CMD","probe /ready"]}}}
        with patch.object(release, "inspect", return_value=container), patch.object(release.urllib.request, "urlopen", return_value=response) as request:
            release.wait_health(REV, "3.39.1", ready_required=False)
            request.assert_called_once_with("https://researcher.beeproject.ir/health", timeout=15)

    def test_final_readiness_still_requires_docker_healthy_and_public_ready(self):
        starting={"State":{"Running":True,"Health":{"Status":"starting"}},"Config":{"Labels":{"org.opencontainers.image.revision":REV}}}
        healthy={**starting,"State":{"Running":True,"Health":{"Status":"healthy"}}}
        response=Mock()
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=False)
        response.read.return_value=json.dumps({"version":"3.40.0"}).encode()
        with patch.object(release,'inspect',side_effect=[starting,healthy]) as inspect, \
                patch.object(release.time,'sleep'),patch.object(release.urllib.request,'urlopen',return_value=response) as request:
            release.wait_health(REV,'3.40.0',ready_required=True)
        self.assertEqual(inspect.call_count,2)
        self.assertEqual([call.args[0] for call in request.call_args_list],['https://researcher.beeproject.ir/health','https://researcher.beeproject.ir/ready'])

    def test_starting_liveness_never_accepts_another_source_commit(self):
        container={"State":{"Running":True,"Health":{"Status":"starting"}},"Config":{"Labels":{"org.opencontainers.image.revision":"c"*40}}}
        with patch.object(release,'inspect',return_value=container),patch.object(release.urllib.request,'urlopen') as request:
            with self.assertRaisesRegex(RuntimeError,'source binding'):
                release.wait_health(REV,'3.40.0',ready_required=False)
        request.assert_not_called()

    def test_stopped_container_never_passes_liveness(self):
        container={"State":{"Running":False,"Health":{"Status":"healthy"}}}
        with patch.object(release,'inspect',return_value=container), \
                patch.object(release.time,'monotonic',side_effect=[0,0,2]),patch.object(release.time,'sleep'), \
                patch.object(release.urllib.request,'urlopen') as request:
            with self.assertRaises(TimeoutError):release.wait_health(REV,'3.40.0',timeout=1,ready_required=False)
        request.assert_not_called()

    def test_atomic_cutover_releases_admission_before_full_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ops/bee-researcher-direct/artifacts").mkdir(parents=True)
            (root / "ops/bee-researcher-direct/private").mkdir(parents=True)
            current = {"Image": "old-image", "Config": {"User": "market-intelligence", "Labels": {
                "org.opencontainers.image.version": "3.39.0", "org.opencontainers.image.revision": REV}, "Env": [
                "MARKET_INTELLIGENCE_POSTGRES_USER=bee_researcher_runtime", "MARKET_INTELLIGENCE_DEPLOYMENT_DRAIN_ENABLED=true",
                "MARKET_INTELLIGENCE_POSTGRES_PASSWORD=synthetic$not-a-real-secret", "UNRELATED_SERVICE_TOKEN=not-copied"]},
                "HostConfig": {"ReadonlyRootfs": True, "CapDrop": ["ALL"]}}
            live = {"Image": "new-image", "Config": {"User": "market-intelligence", "Cmd": ["./start-service.sh"]}}
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
                    patch.object(release, "inspect", side_effect=[current, {"Config":{"Cmd":["./start-service.sh"]}}, {"State": {"ExitCode": 0}}, live]), \
                    patch.object(release, "compose_command", return_value=["docker", "compose"]), \
                    patch.object(release, "run", return_value=""), patch.object(release, "verify_shutdown", return_value={"exit_code": 143}), patch.object(release, "wait_health", side_effect=readiness), \
                    patch.object(release.subprocess, "Popen", return_value=controller), \
                    patch.object(release.select, "select", return_value=([controller.stdout], [], [])):
                release.deploy(args)
            self.assertEqual(observations, [(False, True), (True, False)])
            controller.communicate.assert_called_once_with("release\n", timeout=30)
            overrides = list((root / "ops/bee-researcher-direct/private").glob("*/production.override.json"))
            self.assertEqual(len(overrides), 1)
            self.assertEqual(json.loads(overrides[0].read_text())["services"]["market-intelligence"]["command"],["./start-service.sh"])
            self.assertEqual(overrides[0].stat().st_mode & 0o777, 0o600)
            env = json.loads(overrides[0].read_text())["services"]["market-intelligence"]["environment"]
            self.assertEqual(env["MARKET_INTELLIGENCE_POSTGRES_PASSWORD"], "synthetic$$not-a-real-secret")
            self.assertNotIn("UNRELATED_SERVICE_TOKEN", env)
            self.assertEqual(env["MARKET_INTELLIGENCE_VERSION"], "3.39.1")
            self.assertEqual(env["MARKET_INTELLIGENCE_IMAGE_DIGEST"],REF.split('@')[1])
            self.assertEqual(list((root / "ops/bee-researcher-direct/artifacts").glob("*/production.override.json")), [])
            rollback = json.loads(overrides[0].with_name("rollback.override.json").read_text())["services"]["market-intelligence"]
            self.assertEqual(rollback["image"], "old-image")
            self.assertEqual(rollback["environment"]["MARKET_INTELLIGENCE_POSTGRES_PASSWORD"], "synthetic$$not-a-real-secret")
            self.assertNotIn("MARKET_INTELLIGENCE_VERSION", rollback["environment"])

    def test_atomic_rollback_releases_admission_before_restored_scheduler_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ops/bee-researcher-direct/artifacts").mkdir(parents=True)
            (root / "ops/bee-researcher-direct/private").mkdir(parents=True)
            current = {"Image": "old-image", "Config": {"User": "market-intelligence", "Labels": {
                "org.opencontainers.image.version": "3.39.0", "org.opencontainers.image.revision": REV}, "Env": [
                "MARKET_INTELLIGENCE_POSTGRES_USER=bee_researcher_runtime", "MARKET_INTELLIGENCE_DEPLOYMENT_DRAIN_ENABLED=true"]},
                "HostConfig": {"ReadonlyRootfs": True, "CapDrop": ["ALL"]}}
            controller = Mock(returncode=None)
            controller.stdout.readline.return_value = "RESEARCHER_DRAINED\n"
            controller.poll.side_effect = lambda: controller.returncode
            gate = {"closed": True}
            observations = []

            def released(*args, **kwargs):
                gate["closed"], controller.returncode = False, 0

            def readiness(revision, version, *, ready_required=True, **kwargs):
                observations.append((version, ready_required, gate["closed"]))
                if version == "3.39.1":
                    raise RuntimeError("candidate verification failed")
                if ready_required and gate["closed"]:
                    raise AssertionError("rollback scheduler is blocked by its own barrier")

            controller.communicate.side_effect = released
            args = SimpleNamespace(image=REF, revision=REV, version="3.39.1", expected_current_revision=REV)
            with patch.object(release, "ROOT", root), patch.object(release, "candidate", return_value="new-image"), \
                    patch.object(release, "inspect", side_effect=[current, {"Config":{"Cmd":["./start-service.sh"]}}, {"State": {"ExitCode": 0}}]), \
                    patch.object(release, "compose_command", return_value=["docker", "compose"]), \
                    patch.object(release, "run", return_value=""), patch.object(release, "verify_shutdown", return_value={"exit_code": 143}), patch.object(release, "wait_health", side_effect=readiness), \
                    patch.object(release.subprocess, "Popen", return_value=controller), \
                    patch.object(release.select, "select", return_value=([controller.stdout], [], [])):
                with self.assertRaisesRegex(RuntimeError, "candidate verification failed"):
                    release.deploy(args)
            self.assertEqual(observations, [("3.39.1", False, True), ("3.39.0", False, True), ("3.39.0", True, False)])
            controller.communicate.assert_called_once_with("release\n", timeout=30)
            failure = next((root / "ops/bee-researcher-direct/artifacts").glob("*/failure-receipt.json"))
            details = json.loads(failure.read_text())
            self.assertEqual(details['phase'], 'verify_liveness_and_binding')
            self.assertEqual(details['exception_type'], 'RuntimeError')
            self.assertTrue(details['rollback_required'])
            self.assertNotIn('candidate verification failed', failure.read_text())
            restored = json.loads(failure.with_name('rollback-receipt.json').read_text())
            self.assertTrue(restored['healthy'])
            self.assertEqual(restored['restored_version'], '3.39.0')


if __name__ == "__main__":
    unittest.main()
