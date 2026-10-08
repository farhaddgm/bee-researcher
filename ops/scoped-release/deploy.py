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


def run(args, *, timeout=60, data=None):
    result = subprocess.run(args, input=data, capture_output=True, text=True, timeout=timeout)
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


def wait_health(revision, version, *, timeout=120, ready_required=True):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        container = inspect(APP)
        if container["State"].get("Health", {}).get("Status") == "healthy":
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
                if exc.code != 503:
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
    rollback = compose_command(current)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    artifact = ROOT / "ops/bee-researcher-direct/artifacts" / (args.version + "-completion-" + stamp)
    artifact.mkdir(mode=0o755)
    private = ROOT / "ops/bee-researcher-direct/private" / (args.version + "-completion-" + stamp)
    private.mkdir(mode=0o700)
    override = artifact / "production.override.json"
    save(override, {"services": {"market-intelligence": {
        "image": args.image, "stop_grace_period": "600s", "environment": {
            "MARKET_INTELLIGENCE_VERSION": args.version,
            "MARKET_INTELLIGENCE_BUILD_REVISION": args.revision,
            "MARKET_INTELLIGENCE_IMAGE_DIGEST": image_id,
            "MARKET_INTELLIGENCE_DEPLOYMENT_DRAIN_ENABLED": "true",
        }}}})
    command = compose_command(current, override)
    run(command + ["config", "--quiet"])
    controller = None
    stopped = False
    atomic = values.get("MARKET_INTELLIGENCE_DEPLOYMENT_DRAIN_ENABLED", "false").lower() == "true"
    try:
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
        run(["docker", "stop", "--time", "600", APP], timeout=630)
        stopped = True
        if inspect(APP)["State"]["ExitCode"] != 0:
            raise RuntimeError("graceful shutdown did not finish; refusing replacement")
        run(command + ["up", "-d", "--no-deps", "--force-recreate", "market-intelligence"], timeout=180)
        # A new scheduler cannot emit its first successful heartbeat while
        # admission is closed. Verify liveness/source/image before releasing
        # the barrier, then require full readiness; waiting for /ready while
        # holding the barrier would deadlock every subsequent atomic release.
        wait_health(args.revision, args.version, ready_required=controller is None)
        live = inspect(APP)
        if live["Image"] != image_id or live["Config"]["User"] != current["Config"]["User"]:
            raise RuntimeError("runtime image/user changed unexpectedly")
        if controller:
            controller.communicate("release\n", timeout=30)
            if controller.returncode:
                raise RuntimeError("drain controller did not confirm release")
            wait_health(args.revision, args.version)
        save(artifact / "deployment-receipt.json", {
            "version": args.version, "revision": args.revision, "registry_image": args.image,
            "image_id": image_id, "previous_revision": old_revision, "previous_version": old_version,
            "healthy": True, "atomic_drain_used": atomic, "drain_enabled_for_next_release": True,
            "migration_performed": False, "rekey_performed": False, "other_services_restarted": False,
        })
        print(json.dumps({"healthy": True, "version": args.version, "receipt": str(artifact / "deployment-receipt.json")}))
    except BaseException:
        if stopped:
            run(rollback + ["up", "-d", "--no-deps", "--force-recreate", "market-intelligence"], timeout=180)
            wait_health(old_revision, old_version)
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
