"""Researcher-only encrypted backup and isolated database/WAV recovery proof.

Voice must be paused and producers idle for a consistent initial snapshot.
Never rotates existing keys, restores over production or touches other apps.
The recovery key is stored separately and reused, not included in the bundle.
"""

import argparse
import json
import os
import subprocess
import time
import uuid
from deploy import inspect, run, save
from migrate_news_chat import MIGRATOR, PRIVATE, migration_values, scoped_backup_values


def proof(command, timeout):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        try:
            data = json.loads(result.stdout)
            if (
                set(data) == {"backup_error"}
                and isinstance(data["backup_error"], str)
                and len(data["backup_error"]) < 100
            ):
                print(json.dumps(data), flush=True)
        except (ValueError, TypeError):
            import re

            match = re.findall(
                r"(?:^|\n)([A-Za-z]+Error|ModuleNotFoundError|PermissionError|OSError):",
                result.stderr,
            )
            print(
                json.dumps(
                    {
                        "failure_type": match[-1]
                        if match
                        else "container_execution_error",
                        "exit_code": result.returncode,
                    }
                ),
                flush=True,
            )
        raise RuntimeError("Recovery proof failed")
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image",
        required=True,
        help="Locally tested package containing the backup module",
    )
    args = parser.parse_args()
    print("Recovery stage: preflight", flush=True)
    current = inspect("ai-market-intelligence")
    runtime = dict(v.split("=", 1) for v in current["Config"]["Env"] if "=" in v)
    check = """import asyncio,json
from sqlalchemy import select,func
from app.database import SessionLocal
from app.news_voice.models import VoicePolicy,VoiceAudio,VoiceSaveJob,VoiceSession
async def main():
 async with SessionLocal() as s:
  p=await s.get(VoicePolicy,1)
  assert not p or not p.config.get('enabled'), 'Pause voice before consistent backup'
  for cls in (VoiceAudio,VoiceSaveJob,VoiceSession):
   assert not await s.scalar(select(func.count()).select_from(cls).where(cls.status.in_(['created','preparing','running'])))
 print(json.dumps({'voice_paused':True,'producers_idle':True}))
asyncio.run(main())"""
    run(["docker", "exec", "ai-market-intelligence", "python", "-c", check])
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    directory = PRIVATE / ("voice-backup-" + stamp)
    directory.mkdir(mode=0o700)
    recovery = PRIVATE / "voice-recovery"
    recovery.mkdir(mode=0o700, exist_ok=True)
    if recovery.is_symlink() or recovery.stat().st_mode & 0o077:
        raise RuntimeError("Private recovery directory required")
    print("Recovery stage: scoped database credentials", flush=True)
    pg = scoped_backup_values(migration_values(MIGRATOR), runtime)
    inputs = PRIVATE / ("voice-backup-inputs-" + stamp)
    inputs.mkdir(mode=0o700)
    pgfile = inputs / "backup.env"
    save(pgfile, "".join(k + "=" + v + "\n" for k, v in pg.items()), private=True)
    envfile = inputs / "runtime.env"
    save(
        envfile,
        "".join(
            k + "=" + v + "\n"
            for k, v in runtime.items()
            if k.startswith("MARKET_INTELLIGENCE_")
        ),
        private=True,
    )
    dump = directory / "database.dump"
    fd = os.open(dump, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as output:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "container:ai-market-intelligence",
                "--env-file",
                str(pgfile),
                "--entrypoint",
                "pg_dump",
                "postgres:17.10-alpine",
                "--format=custom",
                "--schema=market_intelligence",
                "--no-owner",
                "--no-acl",
            ],
            stdout=output,
            stderr=subprocess.PIPE,
            timeout=180,
        )
        if result.returncode:
            raise RuntimeError("Scoped database backup failed; diagnostics withheld")
        output.flush()
        os.fsync(output.fileno())
    print("Recovery stage: key provisioning", flush=True)
    # Only the newly created operation directory is transferred to the service
    # UID. Existing application keys and voice volume are mounted read-only.
    bootstrap = """import os,secrets,stat
key=Path('/recovery/key')
if not key.exists():
 fd=os.open(key,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as f:f.write(secrets.token_bytes(32));f.flush();os.fsync(f.fileno())
 os.chown(key,10002,10002)
assert stat.S_ISREG(key.lstat().st_mode) and not key.stat().st_mode&0o077 and key.stat().st_size==32
os.chown('/backup',10002,10002);os.chown('/backup/database.dump',10002,10002)
"""
    run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "0",
            "--entrypoint",
            "python",
            "-v",
            str(directory) + ":/backup",
            "-v",
            str(recovery) + ":/recovery",
            args.image,
            "-c",
            bootstrap,
        ]
    )
    common = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:size=512m,mode=1777",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--env-file",
        str(envfile),
        "--volumes-from",
        "ai-market-intelligence:ro",
        "-v",
        str(directory) + ":/backup",
        "-v",
        str(recovery / "key") + ":/recovery-key:ro",
        "--entrypoint",
        "python",
        args.image,
        "-m",
        "app.news_voice.backup",
    ]
    print("Recovery stage: encrypted bundle", flush=True)
    created = proof(
        common
        + [
            "create",
            "--bundle",
            "/backup/voice.aead",
            "--recovery-key",
            "/recovery-key",
            "--database-dump",
            "/backup/database.dump",
        ],
        timeout=300,
    )
    print("Recovery stage: authenticated restore", flush=True)
    restored = proof(
        common
        + [
            "restore",
            "--bundle",
            "/backup/voice.aead",
            "--recovery-key",
            "/recovery-key",
            "--directory",
            "/backup/restore-proof",
        ],
        timeout=300,
    )
    print("Recovery stage: isolated database restore", flush=True)
    name = "bee-voice-restore-" + uuid.uuid4().hex[:12]
    try:
        run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "--network",
                "none",
                "-e",
                "POSTGRES_PASSWORD=synthetic-recovery-proof-only",
                "-e",
                "POSTGRES_DB=voice_restore",
                "-v",
                str(directory) + "/restore-proof/database.dump:/restore.dump:ro",
                "postgres:17.10-alpine",
            ]
        )
        for _ in range(60):
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    name,
                    "pg_isready",
                    "-U",
                    "postgres",
                    "-d",
                    "voice_restore",
                ],
                capture_output=True,
            )
            if result.returncode == 0:
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("Isolated recovery database did not start")
        run(
            [
                "docker",
                "exec",
                name,
                "psql",
                "-U",
                "postgres",
                "-d",
                "voice_restore",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                "CREATE ROLE bee_researcher_runtime;",
            ]
        )
        run(
            [
                "docker",
                "exec",
                name,
                "pg_restore",
                "-U",
                "postgres",
                "-d",
                "voice_restore",
                "--no-owner",
                "--no-acl",
                "--exit-on-error",
                "/restore.dump",
            ],
            timeout=180,
        )
        count = int(
            run(
                [
                    "docker",
                    "exec",
                    name,
                    "psql",
                    "-U",
                    "postgres",
                    "-d",
                    "voice_restore",
                    "-tAc",
                    "SELECT count(*) FROM market_intelligence.reader_voice_audio",
                ]
            )
        )
        # No restored user text, provider secret or audio is printed.
        receipt = {
            **created,
            **restored,
            "database_restore_verified": True,
            "audio_rows_restored": count,
            "other_services_changed": False,
            "existing_keys_changed": False,
            "backup_directory": str(directory),
            "recovery_key_stored_separately": True,
        }
    finally:
        subprocess.run(
            ["docker", "rm", "-f", "-v", name], capture_output=True, timeout=30
        )
    cleanup = """import hashlib,json,shutil
root=Path('/backup')
print(json.dumps({'bundle_sha256':hashlib.sha256((root/'voice.aead').read_bytes()).hexdigest()}))
shutil.rmtree(root/'restore-proof')
(root/'database.dump').unlink()
"""
    receipt.update(
        json.loads(
            run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--user",
                    "0",
                    "--entrypoint",
                    "python",
                    "-v",
                    str(directory) + ":/backup",
                    args.image,
                    "-c",
                    cleanup,
                ]
            )
        )
    )
    # Env snapshots are no longer needed and are not part of the recovery copy.
    pgfile.unlink()
    envfile.unlink()
    inputs.rmdir()
    save(PRIVATE / ("voice-backup-receipt-" + stamp + ".json"), receipt, private=True)
    print(json.dumps(receipt))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Voice backup/recovery proof failed; private diagnostics withheld."
        ) from None
