from __future__ import annotations

import argparse
import asyncio
import json

from app.ingestion_service import run_ingestion


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one MI-003 ingestion pass")
    parser.add_argument("source_keys", nargs="*", help="Optional source keys such as S-002")
    parser.add_argument("--force", action="store_true", help="Bypass the DB rate-limit cursor")
    args = parser.parse_args()
    result = asyncio.run(run_ingestion(args.source_keys or None, force=args.force))
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
