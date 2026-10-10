"""Digest-bound, Researcher-only application cutover; never migrates or rekeys.

Run only after the exact source has passed CI and its GHCR signature has been
verified. The candidate must already be present locally. Existing compose
files, OAuth credentials, restricted roles and other services are preserved.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import select
import subprocess
import time
import urllib.error
import urllib.request

APP = "ai-market-intelligence"
ROOT = Path("/opt/ai-assistant")


def run(args, *, timeout=60, data=None, env=None):
    result = subprocess.run(args, input=data, capture_output=True, text=True, timeout=timeout, env=env)
    if result.returncode:
        # Command diagnostics may contain environment values. Do not echo them.
        raise RuntimeError(f"{args[0]} failed with exit {result.returncode}; diagnostics withheld")
    return result.stdout


def inspect(ref):
    return json.loads(run(["docker", "inspect", ref]))[0]


def save(path, value, *, private=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600 if private else 0o644)
    with os.fdopen(fd, "w") as output:
        output.write(value if isinstance(value, str) else json.dumps(value, indent=2) + "\n")


def candidate(ref, revision, version):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("a full source commit is required")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("invalid version")
    if not re.fullmatch(r"ghcr\.io/farhaddgm/bee-researcher-market-intelligence@sha256:[0-9a-f]{64}", ref):
        raise ValueError("the verified Researcher GHCR digest is required")
    image = inspect(ref)
    labels = image["Config"]["Labels"]
    if labels.get("org.opencontainers.image.revision") != revision or labels.get("org.opencontainers.image.version") != version:
        raise RuntimeError("candidate image/source/version binding mismatch")
    return image["Id"]


def compose_command(current, extra=None):
    labels = current["Config"]["Labels"]
    files = labels["com.docker.compose.project.config_files"].split(",")
    command = ["docker", "compose", "--project-directory", str(ROOT), "-p", labels["com.docker.compose.project"]]
    for filename in files:
        path = Path(filename).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise RuntimeError("unverified compose file")
        command += ["-f", str(path)]
    if extra:
        command += ["-f", str(extra)]
    return command


def compose_environment(current):
    # Compose interpolates each inherited file before it merges overrides.
    # A private final snapshot alone cannot satisfy earlier ${VAR:?} fields.
    # Provision only this service's actual values, never another app's env.
    result = dict(os.environ)
    result.update(dict(item.split("=", 1) for item in current["Config"]["Env"]
                       if item.startswith("MARKET_INTELLIGENCE_") and "=" in item))
    result["BEE_SCOPED_IMAGE"] = current["Image"]
    return result


def runtime_preflight(ref, env_path):
    # Use the verified new package to check the additive schema/privileges.
    # The old release's hard-coded schema check cannot understand 0045.
    run(["docker", "run", "--rm", "--network", "ai-assistant-backend", "--env-file", str(env_path),
         "--read-only", "--tmpfs", "/tmp:size=32m,mode=1777", "--cap-drop", "ALL",
         "--security-opt", "no-new-privileges:true", "--entrypoint", "python", ref,
         "-m", "app.runtime_permissions"], timeout=60)


def rollback_service(current, environment, version):
    service = {"image": current["Image"], "stop_grace_period": "600s", "environment": dict(environment)}
    old = current["Config"]["Labels"]["org.opencontainers.image.version"]
    if old in {"3.39.0", "3.39.1"} and version == "3.40.0":
        # Auth configuration is still checked. A separate candidate-package
        # preflight verifies least privilege before the legacy app is restored.
        # Never downgrade 0045 or ask the 0044-only preflight to read it.
        service["command"] = ["sh", "-c", "python -m app.auth_deployment && exec uvicorn app.main:app --host 0.0.0.0 --port 8010 --no-access-log --no-proxy-headers"]
    return service


def production_service(ref, environment):
    # A prior forward-schema rollback leaves its temporary auth-only command
    # in the inherited compose stack. Restore the verified image's own CMD,
    # including runtime_permissions; never inherit that compatibility bypass.
    configuration = inspect(ref)["Config"]
    command = configuration.get("Cmd")
    if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
        raise RuntimeError("candidate must declare an explicit startup command")
    return {"image": ref, "command": command, "stop_grace_period": "600s", "environment": dict(environment)}


def verify_shutdown(stopped, since):
    state = stopped["State"]
    if state.get("Running") or state.get("OOMKilled") or state.get("Error") or state.get("ExitCode") not in {0, 143}:
        raise RuntimeError("graceful shutdown did not finish; refusing replacement")
    # Uvicorn re-raises SIGTERM after its lifespan finishes: Docker reports
    # 143 even for a clean stop. Neither 143 nor zero alone proves completion.
    # Require both current-stop markers; never export the underlying logs.
    logs = subprocess.run(["docker", "logs", "--since", since, "--tail", "200", stopped["Id"]],
                          capture_output=True, text=True, timeout=30)
    output = logs.stdout + logs.stderr
    complete = re.search(r"(?m)^INFO:\s+Application shutdown complete\.\s*$", output)
    finished = re.search(r"(?m)^INFO:\s+Finished server process \[\d+\]\s*$", output)
    failure = re.search(r"(?m)^ERROR:|^Traceback \(most recent call last\):|"
                        r"ASGI 'lifespan' protocol appears unsupported|Application shutdown failed|"
                        r"Cancel \d+ running task|timeout graceful shutdown exceeded", output)
    if logs.returncode or failure or not complete or not finished:
        raise RuntimeError("shutdown completion evidence missing; refusing replacement")
    return {"exit_code": state["ExitCode"], "lifespan_completed": True, "server_finished": True}


def wait_health(revision, version, *, timeout=120, ready_required=True):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        container = inspect(APP)
        # Docker itself probes /ready. Requiring Docker healthy before
        # releasing admission is the SAME scheduler-heartbeat deadlock as
        # directly querying /ready. During drain, independently require a
        # running container, bound source and public /health instead. The
        # normal final gate still requires both Docker healthy and /ready.
        state = container["State"]
        if state.get("Running") and (not ready_required or state.get("Health", {}).get("Status") == "healthy"):
            if container["Config"]["Labels"].get("org.opencontainers.image.revision") != revision:
                raise RuntimeError("running source binding mismatch")
            try:
                paths = ("/health", "/ready") if ready_required else ("/health",)
                for path in paths:
                    with urllib.request.urlopen("https://researcher.beeproject.ir" + path, timeout=15) as response:
                        payload = json.load(response)
                        if payload.get("version") != version:
                            raise RuntimeError("public route is serving the wrong version")
                return
            except urllib.error.HTTPError as exc:
                # Docker running does not imply Uvicorn is listening yet.
                # A reverse proxy emits 502/504 during this bounded cutover,
                # including rollback. Do not retry auth/rate-limit/wrong-route
                # errors or accept a mismatched version/source.
                if exc.code not in {502, 503, 504}:
                    raise
            except (urllib.error.URLError, TimeoutError):
                pass
        time.sleep(2)
    raise TimeoutError("Researcher health did not pass")


ACTIVE_JOBS = '''import asyncio,json
from sqlalchemy import select,func
from app.database import engine,SessionLocal
from app.models import JobRun
async def main():
 async with SessionLocal() as s:
  print(json.dumps({'running':await s.scalar(select(func.count()).select_from(JobRun).where(JobRun.status=='running',JobRun.finished_at.is_(None)))}))
 await engine.dispose()
asyncio.run(main())
'''


def deploy(args):
    image_id = candidate(args.image, args.revision, args.version)
    current = inspect(APP)
    labels = current["Config"]["Labels"]
    if labels.get("org.opencontainers.image.revision") != args.expected_current_revision:
        raise RuntimeError("production changed since review; refusing cutover")
    values = dict(item.split("=", 1) for item in current["Config"]["Env"] if "=" in item)
    if values.get("MARKET_INTELLIGENCE_POSTGRES_USER") != "bee_researcher_runtime":
        raise RuntimeError("restricted runtime role must be preserved")
    if not current["HostConfig"]["ReadonlyRootfs"] or current["HostConfig"]["CapDrop"] != ["ALL"]:
        raise RuntimeError("review current security posture before deployment")
    old_version = labels["org.opencontainers.image.version"]
    old_revision = labels["org.opencontainers.image.revision"]
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    artifact = ROOT / "ops/bee-researcher-direct/artifacts" / (args.version + "-completion-" + stamp)
    artifact.mkdir(mode=0o755)
    private = ROOT / "ops/bee-researcher-direct/private" / (args.version + "-completion-" + stamp)
    private.mkdir(mode=0o700)
    # Snapshot this service's actual environment, not a newly re-evaluated
    # shared .env. Another project's deployment must not silently rotate our
    # credentials/configuration. Compose interpolation requires literal '$'
    # to be escaped. The complete override contains secrets: private 0600 only.
    environment = {key: value.replace("$", "$$") for key, value in values.items()
                   if key.startswith("MARKET_INTELLIGENCE_")}
    rollback_override = private / "rollback.override.json"
    save(rollback_override, {"services": {"market-intelligence": rollback_service(current, environment, args.version)}}, private=True)
    if any("\n" in value or "\r" in value for value in values.values()):
        raise RuntimeError("multiline runtime values require secret-file provisioning")
    runtime_env = private / "runtime-preflight.env"
    save(runtime_env, "".join(f"{key}={value}\n" for key, value in values.items()
                             if key.startswith("MARKET_INTELLIGENCE_")), private=True)
    rollback = compose_command(current, rollback_override)
    compose_env = compose_environment(current)
    environment.update({
        "MARKET_INTELLIGENCE_VERSION": args.version,
        "MARKET_INTELLIGENCE_BUILD_REVISION": args.revision,
        "MARKET_INTELLIGENCE_IMAGE_DIGEST": args.image.split("@", 1)[1],
        "MARKET_INTELLIGENCE_DEPLOYMENT_DRAIN_ENABLED": "true",
    })
    override = private / "production.override.json"
    production = production_service(args.image, environment)
    save(override, {"services": {"market-intelligence": production}}, private=True)
    command = compose_command(current, override)
    run(command + ["config", "--quiet"], env=compose_env)
    controller = None
    stopped = False
    phase = "runtime_preflight"
    atomic = values.get("MARKET_INTELLIGENCE_DEPLOYMENT_DRAIN_ENABLED", "false").lower() == "true"
    try:
        runtime_preflight(args.image, runtime_env)
        phase = "drain"
        if atomic:
            env = {key: value for key, value in values.items() if key.startswith("MARKET_INTELLIGENCE_")}
            if any("\n" in value or "\r" in value for value in env.values()):
                raise RuntimeError("multiline runtime secrets require explicit secret-file provisioning")
            env_path = private / "drain.env"
            save(env_path, "".join(f"{key}={value}\n" for key, value in env.items()), private=True)
            controller = subprocess.Popen([
                "docker", "run", "--rm", "-i", "--name", "researcher-drain-" + stamp.lower(),
                "--network", "ai-assistant-backend", "--env-file", str(env_path),
                "--read-only", "--tmpfs", "/tmp:size=32m,mode=1777", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges:true", "--entrypoint", "python",
                current["Image"], "-m", "app.deployment_drain", "--timeout", "300", "--hold-seconds", "900",
            ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            if not select.select([controller.stdout], [], [], 330)[0] or controller.stdout.readline().strip() != "RESEARCHER_DRAINED":
                raise RuntimeError("drain failed; production left unchanged")
        else:
            # First upgrade from a version without the barrier. Never pretend
            # the old application understands the new advisory locks.
            jobs = json.loads(run(["docker", "exec", "-i", APP, "python", "-"], data=ACTIVE_JOBS))
            if jobs["running"]:
                raise RuntimeError("legacy application has active jobs; retry after completion")
        # SIGTERM lets Uvicorn finish HTTP/background work and its scheduler
        # lifespan. Only this container is stopped; no dependent service is.
        stop_since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        phase = "graceful_shutdown"
        run(["docker", "stop", "--time", "600", APP], timeout=630)
        stopped = True
        shutdown = verify_shutdown(inspect(APP), stop_since)
        phase = "recreate_researcher"
        run(command + ["up", "-d", "--no-deps", "--force-recreate", "market-intelligence"], timeout=180, env=compose_env)
        # A new scheduler cannot emit its first successful heartbeat while
        # admission is closed. Verify liveness/source/image before releasing
        # the barrier, then require full readiness; waiting for /ready while
        # holding the barrier would deadlock every subsequent atomic release.
        phase = "verify_liveness_and_binding"
        wait_health(args.revision, args.version, ready_required=controller is None)
        live = inspect(APP)
        if live["Image"] != image_id or live["Config"]["User"] != current["Config"]["User"]:
            raise RuntimeError("runtime image/user changed unexpectedly")
        if live["Config"].get("Cmd") != production["command"]:
            raise RuntimeError("native candidate startup command was not restored")
        if controller:
            phase = "release_admission"
            controller.communicate("release\n", timeout=30)
            if controller.returncode:
                raise RuntimeError("drain controller did not confirm release")
            wait_health(args.revision, args.version)
        phase = "receipt"
        save(artifact / "deployment-receipt.json", {
            "version": args.version, "revision": args.revision, "registry_image": args.image,
            "image_id": image_id, "previous_revision": old_revision, "previous_version": old_version,
            "healthy": True, "atomic_drain_used": atomic, "drain_enabled_for_next_release": True,
            "migration_performed": False, "rekey_performed": False, "other_services_restarted": False,
            "runtime_environment_preserved_in_private_override": True,
            "compose_interpolation_bound_to_runtime": True, "shutdown": shutdown,
            "native_image_command_restored": True,
        })
        print(json.dumps({"healthy": True, "version": args.version, "receipt": str(artifact / "deployment-receipt.json")}))
    except BaseException as exc:
        # Actionable stage/type/state without command output, credentials,
        # compose env, HTTP response bodies or application/customer logs.
        save(artifact / "failure-receipt.json", {
            "version": args.version, "revision": args.revision,
            "phase": phase, "exception_type": type(exc).__name__,
            "researcher_stopped": stopped, "rollback_required": stopped,
            "other_services_restarted": False,
        })
        if stopped:
            runtime_preflight(args.image, runtime_env)
            run(rollback + ["up", "-d", "--no-deps", "--force-recreate", "market-intelligence"], timeout=180, env=compose_env)
            # The restored scheduler has the same cold-heartbeat constraint.
            # Restore liveness and original private configuration first, then
            # release admission before awaiting its first successful tick.
            if controller and controller.poll() is None:
                wait_health(old_revision, old_version, ready_required=False)
                controller.communicate("release\n", timeout=30)
                if controller.returncode:
                    raise RuntimeError("rollback drain controller did not confirm release")
            wait_health(old_revision, old_version)
            save(artifact / "rollback-receipt.json", {
                "restored_revision": old_revision, "restored_version": old_version,
                "healthy": True, "other_services_restarted": False,
                "runtime_privilege_preflight_verified": True,
            })
        raise
    finally:
        if controller and controller.poll() is None:
            controller.communicate("release\n", timeout=30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--expected-current-revision", required=True)
    deploy(parser.parse_args())
