from __future__ import annotations

import argparse
import asyncio
import json

from app.pipeline_service import run_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Market Intelligence pipeline")
    parser.add_argument("source_keys", nargs="*")
    parser.add_argument("--force-ingestion", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--max-candidates", type=int)
    parser.add_argument("--idempotency-key")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    result = await run_pipeline(
        source_keys=args.source_keys or None,
        force_ingestion=args.force_ingestion,
        publish=args.publish,
        max_candidates=args.max_candidates,
        idempotency_key=args.idempotency_key,
    )
    print(json.dumps(result, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
