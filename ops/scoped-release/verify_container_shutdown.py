"""Real Docker/Uvicorn shutdown regression; synthetic ASGI, no network/secrets."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import time
import uuid

spec = importlib.util.spec_from_file_location("release", Path(__file__).with_name("deploy.py"))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

PROGRAM = '''
import asyncio
async def app(scope,receive,send):
 assert scope['type']=='lifespan'
 while True:
  message=await receive()
  if message['type']=='lifespan.startup':
   await send({'type':'lifespan.startup.complete'})
  elif message['type']=='lifespan.shutdown':
   await asyncio.sleep(0.1)
   if FAIL_SHUTDOWN:
    raise RuntimeError('synthetic shutdown failure')
   await send({'type':'lifespan.shutdown.complete'})
   return
'''


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=40)
    if result.returncode:
        raise RuntimeError("isolated Docker fixture command failed")
    return result.stdout


def verify_case(image, mode):
    name = "researcher-shutdown-test-" + uuid.uuid4().hex[:16]
    created = False
    try:
        docker("run", "--detach", "--init", "--name", name, "--network", "none", "--read-only",
               "--tmpfs", "/tmp:size=32m,mode=1777", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges:true", "--entrypoint", "python", image,
               "-c", "import os,pathlib; pathlib.Path('/tmp/shutdown_fixture.py').write_text("
               + repr("FAIL_SHUTDOWN=" + repr(mode == "failed_lifespan") + "\n" + PROGRAM)
               + "); os.execvp('uvicorn',['uvicorn','shutdown_fixture:app','--app-dir','/tmp',"
               "'--host','127.0.0.1','--port','8010','--no-access-log'])")
        created = True
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            logs = subprocess.run(["docker", "logs", "--tail", "30", name], capture_output=True, text=True, timeout=10)
            if "Application startup complete." in logs.stdout + logs.stderr:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("synthetic ASGI fixture did not start")
        since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if mode == "sigkill":
            docker("kill", "--signal", "KILL", name)
            docker("wait", name)
        else:
            docker("stop", "--time", "15", name)
        stopped = json.loads(docker("inspect", name))[0]
        if mode == "clean":
            result = release.verify_shutdown(stopped, since)
            assert result["exit_code"] in {0, 143}
            return {"mode": mode, "exit_code": result["exit_code"], "accepted": True}
        try:
            release.verify_shutdown(stopped, since)
        except RuntimeError:
            return {"mode": mode, "exit_code": stopped["State"]["ExitCode"], "accepted": False}
        raise AssertionError("an incomplete shutdown was incorrectly accepted")
    finally:
        if created:
            docker("rm", "--force", name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    print(json.dumps({"isolated_shutdown_cases": [verify_case(args.image, mode)
                                                  for mode in ("clean", "sigkill", "failed_lifespan")]}))
