"""Guard the legacy-attribute transformer from regressing its known input set.

The active CSP is strict by default and does not authorize inline event or
style attributes. The shell still contains legacy markup which is transformed
before execution; this count is a regression budget for that migration input,
not an allow-list of CSP exceptions.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


DEFAULT_MAX_ONCLICK = 132
# The transformer currently covers this bounded legacy input. Keep the number
# explicit so new inline markup cannot silently grow the conversion surface.
DEFAULT_MAX_STYLE = 54
_ATTR_PATTERNS = {
    # Do not count DOM property assignments such as ``button.onclick =``;
    # CSP's unsafe-inline exception applies to HTML event attributes only.
    "onclick": re.compile(r"(?<![.\w])\bonclick\s*=", re.IGNORECASE),
    "style": re.compile(r"(?<![.\w])\bstyle\s*=", re.IGNORECASE),
}


def count_inline_attributes(source: str) -> dict[str, int]:
    """Return counts for the two attributes covered by the CSP exceptions."""

    return {name: len(pattern.findall(source)) for name, pattern in _ATTR_PATTERNS.items()}


def check_budget(source: str, *, max_onclick: int = DEFAULT_MAX_ONCLICK, max_style: int = DEFAULT_MAX_STYLE) -> dict[str, int]:
    """Validate the migration budget and return the measured counts."""

    counts = count_inline_attributes(source)
    violations = {
        name: count
        for name, count in counts.items()
        if count > {"onclick": max_onclick, "style": max_style}[name]
    }
    if violations:
        details = ", ".join(f"{name}={count} (max { {'onclick': max_onclick, 'style': max_style}[name] })" for name, count in violations.items())
        raise ValueError(f"CSP inline-attribute budget exceeded: {details}")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "app" / "admin_ui.py",
        help="back-office source file to inspect",
    )
    parser.add_argument("--max-onclick", type=int, default=DEFAULT_MAX_ONCLICK)
    parser.add_argument("--max-style", type=int, default=DEFAULT_MAX_STYLE)
    args = parser.parse_args()

    counts = check_budget(
        args.source.read_text(encoding="utf-8"),
        max_onclick=args.max_onclick,
        max_style=args.max_style,
    )
    print(f"CSP inline budget OK: onclick={counts['onclick']}/{args.max_onclick}, style={counts['style']}/{args.max_style}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
