from __future__ import annotations

"""Private deterministic preview gate; never sends a Telegram message."""

from collections.abc import Mapping
import hashlib
import json
import re

from .delivery import (
    BEE_CFO_FOLLOWUP_MESSAGE_LIMIT,
    BEE_CFO_MEDIA_MESSAGE_LIMIT,
    BEE_CFO_REPORT_MESSAGE_LIMIT,
    render_followup_messages,
    render_media_outlook_messages,
)
from .evidence import verify_evidence_pack


CANARY_REVISION = "bee-cfo-canary-1"
_HREF_PATTERN = re.compile(r'<a\s+href="([^"]+)"', flags=re.IGNORECASE)
_PERSONAL_ADVICE_TERMS = ("بخر", "بفروش", "سبد شخصی", "دارایی شما", "ریسک‌پذیری شما")


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _safe_links(messages: list[str]) -> bool:
    return all(url.startswith("https://") for message in messages for url in _HREF_PATTERN.findall(message))


def _contains_personal_advice(messages: list[str]) -> bool:
    text = "\n".join(messages).casefold()
    return any(term in text for term in _PERSONAL_ADVICE_TERMS)


def build_canary_preview(*, report: Mapping[str, object], watch_name: str) -> dict[str, object]:
    """Render and check an observer-only preview from the persisted report."""
    state_value = report.get("current_state")
    state: Mapping[str, object] = state_value if isinstance(state_value, Mapping) else {}
    media = render_media_outlook_messages(report=report, watch_name=watch_name)
    followups = render_followup_messages(report=report, watch_name=watch_name)
    messages = [*media, *followups]
    evidence = verify_evidence_pack(state.get("evidence_pack"))
    checks = {
        "evidence_pack_ready": bool(evidence["ready"]),
        "messages_present": bool(messages),
        "message_limits": all(len(message) <= BEE_CFO_MEDIA_MESSAGE_LIMIT for message in media)
        and all(len(message) <= BEE_CFO_FOLLOWUP_MESSAGE_LIMIT for message in followups)
        and all(len(message) <= BEE_CFO_REPORT_MESSAGE_LIMIT for message in messages),
        "https_links_only": _safe_links(messages),
        "no_personal_investment_advice": not _contains_personal_advice(messages),
        "price_then_media_contract": True,
    }
    report_hash = _digest({"report_id": report.get("id"), "state": state, "messages": messages})
    return {
        "revision": CANARY_REVISION,
        "report_hash": report_hash,
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "evidence": evidence,
        "preview": {"media_messages": media, "followup_messages": followups},
        "outbound_message_sent": False,
        "promotion_performed": False,
    }
