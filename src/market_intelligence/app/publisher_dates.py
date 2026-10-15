"""Publisher timestamps only; discovery/HTTP response times are not news dates."""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def latest_publisher_date(*values: object) -> datetime | None:
    dates: list[datetime] = []
    for value in values:
        parsed = value if isinstance(value, datetime) else None
        if isinstance(value, str) and value.strip():
            try:
                parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            except ValueError:
                try:
                    parsed = parsedate_to_datetime(value.strip())
                except (ValueError, TypeError, OverflowError):
                    continue
        if parsed is not None:
            dates.append(parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc))
    return max(dates, default=None)
