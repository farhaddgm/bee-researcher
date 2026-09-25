from __future__ import annotations

"""Fail-closed controls for direct price sources and quote reconciliation."""

from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from urllib.parse import urlsplit


QUOTE_CONTROL_REVISION = "bee-cfo-quote-control-1"
PROVIDER_CONTRACT_REVISION = "bee-cfo-provider-contract-1"
DEFAULT_MAX_RELATIVE_SPREAD = 0.10


def _payload(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _shape(value: object, *, depth: int = 0) -> object:
    """Return a bounded structural fingerprint without retaining response data."""
    if depth >= 5:
        return "…"
    if isinstance(value, Mapping):
        return {str(key): _shape(item, depth=depth + 1) for key, item in sorted(value.items(), key=lambda row: str(row[0]))}
    if isinstance(value, list):
        return ["list", len(value), _shape(value[0], depth=depth + 1) if value else None]
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if value is None:
        return "null"
    return "str"


def build_provider_signature(
    *,
    adapter: object,
    payload: object,
    parser: Mapping[str, object] | None = None,
    parser_key: object = None,
    extraction_status: object = None,
) -> dict[str, object]:
    """Build a secret-free, deterministic response-shape signature.

    Values are deliberately replaced with types.  This detects provider schema
    drift without storing raw market responses or making an ordinary price move
    look like a parser change.
    """
    contract = {
        "revision": PROVIDER_CONTRACT_REVISION,
        "adapter": str(adapter or "").strip().lower(),
        "parser_key": str(parser_key or "").strip(),
        "parser": {str(key): value for key, value in sorted(dict(parser or {}).items()) if key in {"path", "source_unit", "unit_policy"}},
        "extraction_status": str(extraction_status or "") or None,
        "response_shape": _shape(payload),
    }
    return {**contract, "schema_fingerprint": hashlib.sha256(_payload(contract).encode("utf-8")).hexdigest()}


def build_provider_fixture(signature: Mapping[str, object]) -> dict[str, object]:
    """Freeze an approved offline schema fixture from a UAT signature."""
    normalized = dict(signature or {})
    required = ("revision", "adapter", "parser_key", "parser", "response_shape", "schema_fingerprint")
    if any(key not in normalized for key in required):
        raise ValueError("provider fixture requires a complete response signature")
    if normalized["revision"] != PROVIDER_CONTRACT_REVISION:
        raise ValueError("provider fixture revision is unsupported")
    return {
        "revision": PROVIDER_CONTRACT_REVISION,
        "adapter": normalized["adapter"],
        "parser_key": normalized["parser_key"],
        "parser": normalized["parser"],
        "extraction_status": normalized.get("extraction_status"),
        "response_shape": normalized["response_shape"],
        "schema_fingerprint": normalized["schema_fingerprint"],
    }


def validate_provider_fixture(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("provider_fixture must be an object")
    fixture = build_provider_fixture(value)
    # The fixture stores a structural shape rather than raw response data, so
    # re-hash that canonical structure directly instead of shaping it again.
    direct = {
        "revision": fixture["revision"], "adapter": fixture["adapter"], "parser_key": fixture["parser_key"],
        "parser": fixture["parser"], "extraction_status": fixture.get("extraction_status"), "response_shape": fixture["response_shape"],
    }
    if fixture["schema_fingerprint"] != hashlib.sha256(_payload(direct).encode("utf-8")).hexdigest():
        raise ValueError("provider_fixture fingerprint is invalid")
    return fixture


def evaluate_provider_response(
    fixture: Mapping[str, object] | None,
    signature: Mapping[str, object] | None,
    *,
    enforced: bool = False,
) -> dict[str, object]:
    """Quarantine an observed provider shape that differs from its fixture."""
    if not fixture:
        return {
            "revision": PROVIDER_CONTRACT_REVISION,
            "status": "legacy_unpinned",
            "delivery_permitted": True,
            "quarantined": False,
            "enforced": False,
        }
    try:
        baseline = validate_provider_fixture(fixture)
    except ValueError as exc:
        return {
            "revision": PROVIDER_CONTRACT_REVISION,
            "status": "invalid_fixture",
            "delivery_permitted": False,
            "quarantined": True,
            "reason": str(exc),
            "enforced": bool(enforced),
        }
    if not isinstance(signature, Mapping):
        return {
            "revision": PROVIDER_CONTRACT_REVISION,
            "status": "missing_runtime_signature",
            "delivery_permitted": not enforced,
            "quarantined": bool(enforced),
            "enforced": bool(enforced),
        }
    current = str(signature.get("schema_fingerprint") or "")
    pinned = str(baseline.get("schema_fingerprint") or "")
    match = bool(current and current == pinned)
    return {
        "revision": PROVIDER_CONTRACT_REVISION,
        "status": "pinned" if match else "provider_drift",
        "delivery_permitted": match,
        "quarantined": not match,
        "enforced": bool(enforced),
        "baseline_fingerprint": pinned,
        "observed_fingerprint": current or None,
    }


def source_contract_fingerprint(*, indicator: object, source: object) -> str:
    """Hash only the configuration that can alter a delivered price."""
    fields = {
        "indicator_key": getattr(indicator, "indicator_key", None),
        "quote_unit": getattr(indicator, "quote_unit", None),
        "parser_key": getattr(indicator, "parser_key", None),
        "source_key": getattr(source, "source_key", None),
        "fetch_url": getattr(source, "fetch_url", None),
        "homepage_url": getattr(source, "homepage_url", None),
        "adapter": getattr(source, "adapter", None),
        "parser_json": getattr(source, "parser_json", None) or {},
    }
    return hashlib.sha256(_payload(fields).encode("utf-8")).hexdigest()


def evaluate_source_contract(
    decision: Mapping[str, object] | None,
    *,
    current_fingerprint: str,
    now: datetime | None = None,
) -> dict[str, object]:
    """Require a decision to pin the exact source/parser configuration."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(decision, Mapping):
        return {"status": "missing_decision", "delivery_permitted": False, "revalidation_required": True}
    stored = str(decision.get("contract_fingerprint") or "")
    if not stored:
        return {"status": "unversioned_contract", "delivery_permitted": False, "revalidation_required": True}
    if stored != current_fingerprint:
        return {"status": "contract_drift", "delivery_permitted": False, "revalidation_required": True}
    expires_at = decision.get("expires_at")
    if expires_at:
        try:
            parsed = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed.astimezone(timezone.utc) <= now.astimezone(timezone.utc):
                return {"status": "expired", "delivery_permitted": False, "revalidation_required": True}
        except (TypeError, ValueError):
            return {"status": "invalid_expiry", "delivery_permitted": False, "revalidation_required": True}
    return {"status": "pinned", "delivery_permitted": True, "revalidation_required": False}


def _value(quote: object) -> float | None:
    value = getattr(quote, "value", None)
    if not isinstance(value, (str, bytes, bytearray, int, float, Decimal)):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed > 0 else None


def reconcile_quotes(
    primary: object,
    verifier: object | None,
    *,
    max_relative_spread: float = DEFAULT_MAX_RELATIVE_SPREAD,
) -> dict[str, object]:
    """Check independently fetched quotes without silently averaging them."""
    first = _value(primary)
    if first is None:
        return {"status": "invalid_primary", "delivery_permitted": False, "relative_spread": None}
    if verifier is None:
        return {
            "status": "single_source",
            "delivery_permitted": True,
            "relative_spread": None,
            "threshold": max_relative_spread,
            "revision": QUOTE_CONTROL_REVISION,
        }
    second = _value(verifier)
    if second is None:
        return {"status": "invalid_verifier", "delivery_permitted": False, "relative_spread": None}
    threshold = max(0.0, min(1.0, float(max_relative_spread)))
    spread = abs(first - second) / max(abs(first), abs(second))
    return {
        "status": "passed" if spread <= threshold else "mismatch",
        "delivery_permitted": spread <= threshold,
        "relative_spread": round(spread, 8),
        "threshold": threshold,
        "primary_value": first,
        "verifier_value": second,
        "revision": QUOTE_CONTROL_REVISION,
    }


def source_hostname(source: object) -> str:
    try:
        return (urlsplit(str(getattr(source, "fetch_url", ""))).hostname or "").casefold()
    except ValueError:
        return ""


def sources_independent(primary: object, candidate: object) -> bool:
    return (
        str(getattr(primary, "source_key", "")) != str(getattr(candidate, "source_key", ""))
        and bool(source_hostname(primary))
        and source_hostname(primary) != source_hostname(candidate)
    )
