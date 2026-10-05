"""Service-scoped operational logging without enabling noisy HTTP client logs."""

from __future__ import annotations

import json
import logging
import sys
import traceback
from datetime import datetime, timezone

from app.security_controls import redact_sensitive_text


class OperationalFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_sensitive_text(record.getMessage(), limit=4000),
        }
        if record.exc_info:
            exc_type, _, tb = record.exc_info
            payload["exception_type"] = exc_type.__name__ if exc_type else "unknown"
            # Exception strings and source lines can contain customer data or
            # secrets. File/function/line identify the failure without them.
            payload["frames"] = [
                {"file": frame.filename.rsplit("/", 1)[-1], "function": frame.name, "line": frame.lineno}
                for frame in traceback.extract_tb(tb)[-12:]
            ]
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging() -> None:
    logger = logging.getLogger("app")
    if not any(getattr(handler, "bee_operational", False) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.bee_operational = True  # type: ignore[attr-defined]
        handler.setFormatter(OperationalFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def log_event(event: str, **fields: object) -> None:
    logging.getLogger(__name__).info(
        "operational_event=%s", json.dumps({"event": event, **fields}, separators=(",", ":"))
    )
