from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from app.config import Settings, get_settings


SEGMENT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def queue_key(segment: str, *, settings: Settings | None = None) -> str:
    if not SEGMENT_PATTERN.fullmatch(segment):
        raise ValueError("queue key segment is invalid")
    active_settings = settings or get_settings()
    return f"{active_settings.queue_namespace}:{segment}"


def pipeline_lock_key(assistant_id: uuid.UUID | None = None, *, settings: Settings | None = None) -> str:
    """Return a Redis lock key that is valid and isolated per workspace."""
    suffix = str(assistant_id).replace("-", "_") if assistant_id else "default"
    return queue_key(f"pipeline_lock_{suffix}", settings=settings)


@dataclass(frozen=True)
class QueueNames:
    runs: str
    dead_letter: str
    scheduler_lock: str


def get_queue_names(settings: Settings | None = None) -> QueueNames:
    active_settings = settings or get_settings()
    return QueueNames(
        runs=queue_key("runs", settings=active_settings),
        dead_letter=queue_key("dead-letter", settings=active_settings),
        scheduler_lock=queue_key("scheduler-lock", settings=active_settings),
    )
