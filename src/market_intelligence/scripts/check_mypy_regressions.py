#!/usr/bin/env python3
"""Compare Mypy diagnostics to a source baseline and report resolved debt.

CI also runs a blocking zero-diagnostic Mypy check. This comparison provides
an auditable count of diagnostics introduced or resolved by a change.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    Path("app/market_intelligence/app")
    if (ROOT / "app/market_intelligence/app").is_dir()
    else Path("app")
)
DIAGNOSTIC = re.compile(
    r"^(?P<path>[^:]+):\d+: error: (?P<message>.*?)(?: \[(?P<code>[\w-]+)\])?$"
)


def diagnostics(source_root: Path) -> Counter[tuple[str, str, str]]:
    with tempfile.TemporaryDirectory(prefix="bee-mypy-cache-") as cache_dir:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "mypy",
                str(source_root / SOURCE),
                "--ignore-missing-imports",
                "--no-error-summary",
                f"--cache-dir={cache_dir}",
            ],
            cwd=source_root,
            check=False,
            capture_output=True,
            text=True,
        )
    parsed: Counter[tuple[str, str, str]] = Counter()
    for line in (result.stdout + result.stderr).splitlines():
        match = DIAGNOSTIC.match(line)
        if not match:
            continue
        path = match.group("path")
        normalized_path = re.sub(
            r"^.*?((?:app/market_intelligence/)?app/)", r"\1", path
        )
        parsed[(normalized_path, match.group("code") or "", match.group("message"))] += 1
    if result.returncode not in (0, 1):
        raise RuntimeError(
            f"Mypy could not complete for {source_root}: "
            f"{(result.stdout + result.stderr)[-4000:]}"
        )
    return parsed


def main() -> int:
    if len(sys.argv) > 2:
        print(f"Usage: {Path(sys.argv[0]).name} [baseline-ref]", file=sys.stderr)
        return 2
    baseline_ref = sys.argv[1] if len(sys.argv) == 2 else "HEAD^"
    repository = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if repository.returncode:
        print("Mypy regression gate must run inside a Git checkout.", file=sys.stderr)
        return 2
    repository_root = Path(repository.stdout.strip()).resolve()
    try:
        project_prefix = ROOT.resolve().relative_to(repository_root)
    except ValueError:
        print("Mypy project root is outside its Git checkout.", file=sys.stderr)
        return 2
    archive_source = (project_prefix / SOURCE).as_posix()
    parent = subprocess.run(
        ["git", "rev-parse", "--verify", baseline_ref],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if parent.returncode:
        print(f"Mypy regression gate cannot resolve baseline {baseline_ref!r}.", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="bee-mypy-baseline-") as temporary:
        baseline_root = Path(temporary)
        archive = subprocess.Popen(
            ["git", "archive", "--format=tar", parent.stdout.strip(), archive_source],
            cwd=repository_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert archive.stdout is not None
        try:
            with tarfile.open(fileobj=archive.stdout, mode="r|*") as tar:
                tar.extractall(path=baseline_root, filter="data")
        finally:
            archive.stdout.close()
        archive_error = archive.stderr.read().decode("utf-8", errors="replace") if archive.stderr else ""
        archive_returncode = archive.wait()
        if archive_returncode:
            print(f"Could not prepare the Mypy baseline: {archive_error}", file=sys.stderr)
            return 2

        baseline = diagnostics(baseline_root / project_prefix)
        current = diagnostics(ROOT)

    introduced = current - baseline
    resolved = baseline - current
    print(
        "Mypy diagnostics: "
        f"baseline={sum(baseline.values())}, current={sum(current.values())}, "
        f"new={sum(introduced.values())}, resolved={sum(resolved.values())}"
    )
    if introduced:
        print("New diagnostics:", file=sys.stderr)
        for (path, code, message), count in sorted(introduced.items()):
            suffix = f" [{code}]" if code else ""
            print(f"  {count}x {path}: {message}{suffix}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
