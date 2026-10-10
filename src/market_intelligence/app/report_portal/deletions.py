"""Append-only tombstone registry: keep this volume OUTSIDE database backups."""

import fcntl
import os
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from app.config import get_settings


def registry():
    return Path(get_settings().report_deletion_registry_file)


def contains(report_id):
    path = registry()
    try:
        with path.open("r") as handle:
            return any(line.strip() == str(report_id) for line in handle)
    except OSError:
        raise HTTPException(503, "report_registry_unavailable") from None


async def prepare():
    """Never silently recreate a lost deletion ledger after restoring a DB."""
    from sqlalchemy import select
    from app.database import SessionLocal
    from .models import ReportDeletion, InternalReport

    path = registry()
    if path.exists():
        if not path.is_file() or not os.access(path, os.R_OK | os.W_OK):
            raise HTTPException(503, "report_registry_unavailable")
        return
    async with SessionLocal() as session:
        if await session.scalar(
            select(ReportDeletion.report_id).limit(1)
        ) or await session.scalar(select(InternalReport.id).limit(1)):
            raise HTTPException(503, "report_registry_unavailable")
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
    except FileExistsError:
        return
    except OSError:
        raise HTTPException(503, "report_registry_unavailable") from None


def record(report_id):
    value = str(UUID(str(report_id)))
    path = registry()
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.write(value + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        raise HTTPException(503, "report_registry_unavailable") from None
