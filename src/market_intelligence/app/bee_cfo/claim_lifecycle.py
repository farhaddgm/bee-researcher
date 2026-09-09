from __future__ import annotations

"""Evidence-bound lifecycle tracking for explicit media claims."""

from collections.abc import Iterable, Mapping
import hashlib
import re


CLAIM_LIFECYCLE_REVISION = "bee-cfo-claim-lifecycle-1"
_CONDITION_PATTERN = re.compile(
    r"(?:\bif\b|\bunless\b|\bprovided\b|\bsubject to\b|اگر|در صورت|مشروط به)\s+([^.!؟\n]{3,240})",
    flags=re.IGNORECASE,
)


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _digest(*parts: object) -> str:
    payload = "|".join(_clean(part).casefold() for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:40]


def extract_conditions(value: object) -> list[str]:
    """Return only conditions explicitly present in the cited claim text."""
    text = _clean(value)
    return [_clean(match.group(0))[:260] for match in _CONDITION_PATTERN.finditer(text)]


def _active_claims(rows: Iterable[object]) -> list[dict[str, object]]:
    claims: list[dict[str, object]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        if row.get("evidence_type") != "explicit_opinion" or row.get("stance") not in {"up", "down", "flat"}:
            continue
        if row.get("status") in {"expired", "withdrawn"}:
            continue
        source_key = _clean(row.get("source_key"))
        horizon_key = _clean(row.get("horizon_key")) or "unspecified"
        analyst = _clean(row.get("analyst_name"))
        statement = _clean(row.get("snippet") or row.get("view"))
        if not source_key or not statement:
            continue
        stream_key = _digest(source_key, analyst, horizon_key)
        claim_id = _digest(stream_key, row.get("forecast_id"), statement, row.get("stance"))
        claims.append(
            {
                "claim_id": claim_id,
                "stream_key": stream_key,
                "forecast_id": row.get("forecast_id"),
                "source_key": source_key,
                "source_name": _clean(row.get("source_name")),
                "source_url": _clean(row.get("source_url")),
                "analyst_name": analyst or None,
                "stance": row.get("stance"),
                "horizon_key": horizon_key,
                "horizon_label": row.get("horizon_label"),
                "conditions": extract_conditions(statement),
                "evidence_id": row.get("evidence_id"),
                "narrative_key": row.get("narrative_key"),
                "independence_weight": row.get("independence_weight"),
                "published_at": row.get("published_at"),
                "statement_hash": _digest(statement),
            }
        )
    return claims


def build_claim_lifecycle(
    rows: Iterable[object],
    *,
    previous: Iterable[object] | None = None,
) -> dict[str, object]:
    """Track continuation, replacement and withdrawal without inventing intent."""
    current = _active_claims(rows)
    prior = [dict(row) for row in (previous or []) if isinstance(row, Mapping)]
    prior_active = [row for row in prior if row.get("lifecycle_status") in {"active", "continuing", "replaced"}]
    current_by_stream: dict[str, list[dict[str, object]]] = {}
    for claim in current:
        current_by_stream.setdefault(str(claim["stream_key"]), []).append(claim)
    prior_by_stream: dict[str, list[dict[str, object]]] = {}
    for claim in prior_active:
        key = str(claim.get("stream_key") or "")
        if key:
            prior_by_stream.setdefault(key, []).append(claim)
    result: list[dict[str, object]] = []
    for claim in current:
        candidates = prior_by_stream.get(str(claim["stream_key"]), [])
        same = next((row for row in candidates if row.get("statement_hash") == claim["statement_hash"] and row.get("stance") == claim["stance"]), None)
        replaced = None if same else (candidates[-1] if candidates else None)
        claim["lifecycle_status"] = "continuing" if same else "active" if replaced is None else "replaces"
        claim["replaces_claim_id"] = replaced.get("claim_id") if replaced else None
        result.append(claim)
    for stream_key, candidates in prior_by_stream.items():
        live = current_by_stream.get(stream_key, [])
        for prior_claim in candidates:
            if any(row.get("statement_hash") == prior_claim.get("statement_hash") and row.get("stance") == prior_claim.get("stance") for row in live):
                continue
            lifecycle_status = "replaced" if live else "withdrawn"
            result.append(
                {
                    **prior_claim,
                    "lifecycle_status": lifecycle_status,
                    "replaced_by_claim_ids": [row["claim_id"] for row in live] if live else [],
                }
            )
    result.sort(key=lambda row: (str(row.get("source_key")), str(row.get("horizon_key")), str(row.get("claim_id"))))
    return {
        "revision": CLAIM_LIFECYCLE_REVISION,
        "claims": result,
        "active_count": sum(row.get("lifecycle_status") in {"active", "continuing", "replaces"} for row in result),
        "withdrawn_count": sum(row.get("lifecycle_status") == "withdrawn" for row in result),
        "replaced_count": sum(row.get("lifecycle_status") == "replaced" for row in result),
    }
