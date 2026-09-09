"""Register the approved media rows S-006 through S-008 from Bee Researcher."""

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


SCHEMA = "market_intelligence"
revision = "0007_sheet_media_registry"
down_revision = "0006_assistant_data_scope"
branch_labels = None
depends_on = None

DEFAULT_ASSISTANT = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    rows = [
        {
            "id": uuid.UUID("00000000-0000-4000-8000-000000000006"),
            "source_key": "S-006",
            "name": "عصر تراکنش",
            "homepage_url": "https://asretarakonesh.ir/",
            "fetch_url": "https://asretarakonesh.ir/feed/",
            "adapter": "rss",
            "priority": 4,
            "enabled": False,
            "access_notes": "Public RSS candidate; repeated public probe timed out. Keep disabled until a valid response is observed.",
        },
        {
            "id": uuid.UUID("00000000-0000-4000-8000-000000000007"),
            "source_key": "S-007",
            "name": "دنیای اقتصاد",
            "homepage_url": "https://donya-e-eqtesad.com/",
            "fetch_url": "https://donya-e-eqtesad.com/feeds/",
            "adapter": "rss",
            "priority": 4,
            "enabled": True,
            "access_notes": "Public RSS endpoint /feeds/ returned XML during registry verification.",
        },
        {
            "id": uuid.UUID("00000000-0000-4000-8000-000000000008"),
            "source_key": "S-008",
            "name": "استارتاپ 360",
            "homepage_url": "https://startup360.ir/",
            "fetch_url": "https://startup360.ir/feed/",
            "adapter": "rss",
            "priority": 4,
            "enabled": True,
            "access_notes": "Public RSS endpoint /feed/ returned XML during registry verification.",
        },
    ]
    table = sa.table(
        "sources",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("assistant_id", postgresql.UUID(as_uuid=True)),
        sa.column("source_key", sa.String()),
        sa.column("name", sa.String()),
        sa.column("homepage_url", sa.String()),
        sa.column("fetch_url", sa.String()),
        sa.column("adapter", sa.String()),
        sa.column("language", sa.String()),
        sa.column("region", sa.String()),
        sa.column("priority", sa.SmallInteger()),
        sa.column("enabled", sa.Boolean()),
        sa.column("access_policy", sa.String()),
        sa.column("access_notes", sa.Text()),
        sa.column("robots_policy", sa.String()),
        sa.column("rate_limit_seconds", sa.SmallInteger()),
        sa.column("request_timeout_seconds", sa.SmallInteger()),
        sa.column("max_retries", sa.SmallInteger()),
        schema=SCHEMA,
    )
    op.bulk_insert(
        table,
        [
            {
                **row,
                "assistant_id": uuid.UUID(DEFAULT_ASSISTANT),
                "language": "fa",
                "region": "IR",
                "access_policy": "public_only",
                "robots_policy": "respect",
                "rate_limit_seconds": 60,
                "request_timeout_seconds": 20,
                "max_retries": 2,
            }
            for row in rows
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            f"DELETE FROM {SCHEMA}.sources "
            "WHERE source_key IN ('S-006', 'S-007', 'S-008')"
        )
    )
