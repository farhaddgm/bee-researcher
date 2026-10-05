"""Explicit, bounded translation repair. Dry-run unless --apply is provided.

Reports IDs and counts, not article bodies, user data or API credentials.
"""
import argparse
import asyncio
import json
import uuid

from app.config import get_settings
from app.database import engine
from app.pipeline_service import repair_report_translations


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assistant-id", type=uuid.UUID, required=True)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = await repair_report_translations(get_settings(), assistant_id=args.assistant_id, limit=args.limit, apply=args.apply)
        print(json.dumps(result, ensure_ascii=False))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
