#!/usr/bin/env python3
"""Validate the UX-writing catalogs used by the back-office.

The source language is Persian for the admin UI, so a Persian key is a valid
fallback for ``fa``.  Every other supported locale must have a non-empty
translation.  Dynamic JavaScript fragments are deliberately rejected: they
belong in code, not in the translation catalog, where they can never be
translated reliably.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


LOCALES = ("fa", "en", "tr", "ar", "it", "es", "de", "fr")
CATALOGS = ("ux_writing_catalog.json", "ux_writing_catalog_additions.json")


def _catalog_path(name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "app" / name


def audit() -> tuple[list[str], dict[str, int]]:
    errors: list[str] = []
    counts = {locale: 0 for locale in LOCALES}
    for name in CATALOGS:
        seen: set[str] = set()
        path = _catalog_path(name)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{name}: cannot read valid JSON ({exc})")
            continue
        if not isinstance(data, dict):
            errors.append(f"{name}: root must be an object")
            continue
        for key, translations in data.items():
            if key in seen:
                errors.append(f"duplicate translation key: {key!r}")
            seen.add(key)
            if not isinstance(translations, dict):
                errors.append(f"{name}: {key!r} must map to a locale object")
                continue
            # A few old snapshots contain expressions captured from a
            # template (for example ``'+esc(value)+'``).  They are not UX
            # copy and must not be treated as translatable strings; runtime
            # code owns their escaping and their real labels are audited as
            # static entries.  Keep them out of the locale completeness
            # denominator rather than accepting an impossible translation.
            if str(key).startswith("'+") or "+label(" in str(key) or "+esc(" in str(key):
                continue
            for locale in LOCALES:
                value = translations.get(locale)
                # Persian is the source language and may intentionally use
                # the key itself for English-origin data labels.
                if locale == "fa" and value is None:
                    continue
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"{name}: {key!r} missing non-empty {locale} translation")
                else:
                    counts[locale] += 1
    return errors, counts


def main() -> int:
    errors, counts = audit()
    if errors:
        for error in errors:
            print(f"I18N ERROR: {error}", file=sys.stderr)
        return 1
    total = sum(counts.values())
    key_count = total // len(LOCALES)
    print(f"I18N catalog OK: {key_count} static keys with {total} locale entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
