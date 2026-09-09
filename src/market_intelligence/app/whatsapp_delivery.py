"""Safe, opt-in WhatsApp delivery readiness for MI-066.

This module deliberately does not make network calls.  Meta credentials and a
public webhook are required before a production adapter can be enabled; until
then the service exposes only a non-secret readiness report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.config import Settings


WhatsAppDestination = Literal["cloud_api", "channel"]


@dataclass(frozen=True, slots=True)
class WhatsAppReadiness:
    enabled: bool
    destination_type: WhatsAppDestination
    configured: bool
    ready: bool
    missing: tuple[str, ...]
    status: str

    def safe_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "destination_type": self.destination_type,
            "configured": self.configured,
            "ready": self.ready,
            "missing": list(self.missing),
            "status": self.status,
        }


def whatsapp_readiness(settings: Settings) -> WhatsAppReadiness:
    """Return a secret-free readiness gate; never call Meta implicitly."""
    destination = settings.whatsapp_destination_type
    if not settings.whatsapp_enabled:
        return WhatsAppReadiness(
            enabled=False,
            destination_type=destination,
            configured=False,
            ready=False,
            missing=("owner_enablement", "meta_credentials"),
            status="disabled_until_meta_approval",
        )

    missing: list[str] = []
    if settings.whatsapp_access_token is None:
        missing.append("access_token")
    if settings.whatsapp_webhook_verify_token is None:
        missing.append("webhook_verify_token")
    if not settings.whatsapp_webhook_public_url:
        missing.append("webhook_public_url")
    if destination == "cloud_api":
        if not settings.whatsapp_business_account_id:
            missing.append("business_account_id")
        if not settings.whatsapp_phone_number_id:
            missing.append("phone_number_id")
    elif not settings.whatsapp_channel_id:
        missing.append("channel_id")
    return WhatsAppReadiness(
        enabled=True,
        destination_type=destination,
        configured=not missing,
        ready=False,
        missing=tuple(missing),
        status="awaiting_official_adapter_validation" if not missing else "missing_meta_prerequisites",
    )


class WhatsAppClient:
    """Placeholder client that fails closed until the official adapter is wired."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def readiness(self) -> WhatsAppReadiness:
        return whatsapp_readiness(self.settings)

    async def send_text(self, *, text: str, idempotency_key: str) -> dict[str, object]:
        del text, idempotency_key
        status = self.readiness()
        raise RuntimeError(
            "WhatsApp delivery is disabled until official Meta credentials, webhook, "
            f"and adapter validation are complete ({', '.join(status.missing) or status.status})"
        )
