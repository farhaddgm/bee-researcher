"""Per-workspace data-retention policy shared by the API and the daily job."""

from __future__ import annotations

from app.config import get_settings


# The floor stays well above the 7-day freshness window: deleting items that
# feeds still list would let ingestion rediscover and republish them.
MIN_RETENTION_DAYS = 30
MAX_RETENTION_DAYS = 3650


def effective_retention_days(config: dict | None) -> tuple[int, str]:
    """Return the enforced article retention and where it comes from.

    A workspace that never saved a value keeps the deployment default
    (``normalized_retention_days``); an explicit workspace value is enforced
    by the daily retention job exactly as shown in the privacy panel.
    """
    raw = (config or {}).get("privacy") if isinstance(config, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    default = int(get_settings().normalized_retention_days)
    try:
        value = int(raw["retention_days"])
    except (KeyError, TypeError, ValueError):
        return default, "deployment_default"
    return min(max(value, MIN_RETENTION_DAYS), MAX_RETENTION_DAYS), "workspace"
