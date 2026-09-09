from __future__ import annotations

"""Immutable, reproducible evidence packs for Bee CFO reports.

The pack is deliberately built from evidence already collected for a report.
It never re-fetches an article, so a later source edit cannot silently change
the support for a previously generated conclusion.
"""

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
import hashlib
import json
from urllib.parse import urlsplit, urlunsplit


EVIDENCE_PACK_REVISION = "bee-cfo-evidence-pack-1"
MAX_CITED_SPAN = 700


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def canonical_url(value: object) -> str | None:
    """Return a stable public URL or ``None`` for a non-citable reference."""
    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        return None
    return urlunsplit(("https", parsed.netloc.casefold(), parsed.path or "/", parsed.query, ""))


def _as_mapping(item: object) -> dict[str, object]:
    if isinstance(item, Mapping):
        return dict(item)
    return {
        key: getattr(item, key, None)
        for key in (
            "title", "text", "source_key", "source_name", "source_url", "source_origin",
            "source_authority", "discovery_path", "published_at", "discovered_at",
            "extraction_status", "quality_score", "provenance",
        )
    }


def _timestamp(value: object, fallback: datetime) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            parsed = fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _provenance(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    allowed = ("content_hash", "article_id", "author", "fetch", "retrieval", "language", "source_version")
    return {key: value[key] for key in allowed if key in value and value[key] not in (None, "")}


def build_evidence_pack(
    evidence: Iterable[object],
    *,
    report_as_of: datetime,
    model_revision: str,
    renderer_revision: str,
    output_contract_revision: str,
    source_policy_revision: str,
) -> dict[str, object]:
    """Capture the exact bounded excerpts used by a report and hash the pack."""
    captured_at = _timestamp(report_as_of, report_as_of)
    entries: list[dict[str, object]] = []
    for item in evidence:
        row = _as_mapping(item)
        text = _clean(row.get("text"))
        span = text[:MAX_CITED_SPAN]
        url = canonical_url(row.get("source_url"))
        status = "captured" if url and text else "incomplete"
        provenance = _provenance(row.get("provenance"))
        content_hash = str(provenance.get("content_hash") or _digest(text))
        entries.append(
            {
                "evidence_id": _digest({"source_key": row.get("source_key"), "url": url, "content_hash": content_hash}),
                "status": status,
                "source_key": _clean(row.get("source_key")),
                "source_name": _clean(row.get("source_name")),
                "source_url": url,
                "title": _clean(row.get("title"))[:300],
                "published_at": _timestamp(row.get("published_at"), report_as_of) if row.get("published_at") else None,
                "discovered_at": _timestamp(row.get("discovered_at"), report_as_of) if row.get("discovered_at") else None,
                "captured_at": captured_at,
                "extraction_status": _clean(row.get("extraction_status")) or "unknown",
                "quality_score": row.get("quality_score"),
                "cited_span": span,
                "cited_span_hash": _digest(span),
                "content_hash": content_hash,
                "provenance": provenance,
            }
        )
    entries.sort(key=lambda row: (str(row["source_key"]), str(row["source_url"]), str(row["evidence_id"])))
    payload = {
        "revision": EVIDENCE_PACK_REVISION,
        "report_as_of": captured_at,
        "model_revision": str(model_revision or "unknown")[:96],
        "renderer_revision": str(renderer_revision or "unknown")[:96],
        "output_contract_revision": str(output_contract_revision or "unknown")[:96],
        "source_policy_revision": str(source_policy_revision or "unknown")[:96],
        "entries": entries,
    }
    payload["manifest_hash"] = _digest(payload)
    payload["ready"] = bool(entries) and all(row["status"] == "captured" for row in entries)
    payload["incomplete_count"] = sum(row["status"] != "captured" for row in entries)
    return payload


def verify_evidence_pack(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {"ready": False, "reason": "missing_evidence_pack", "entry_count": 0}
    pack = dict(value)
    declared = pack.pop("manifest_hash", None)
    ready = pack.pop("ready", None)
    incomplete = pack.pop("incomplete_count", None)
    entries = pack.get("entries")
    if not isinstance(entries, list):
        return {"ready": False, "reason": "invalid_entries", "entry_count": 0}
    valid_hash = isinstance(declared, str) and declared == _digest(pack)
    complete = bool(entries) and all(isinstance(row, Mapping) and row.get("status") == "captured" for row in entries)
    return {
        "ready": bool(valid_hash and complete and ready is True and incomplete == 0),
        "reason": None if valid_hash and complete else "hash_or_capture_incomplete",
        "entry_count": len(entries),
        "manifest_hash": declared,
    }
