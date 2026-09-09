"""Track the separate media-outlook Telegram message for Bee CFO reports."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0021_bee_cfo_media_delivery"
down_revision = "0020_bee_cfo_price_hardening"
branch_labels = None
depends_on = None

SCHEMA = "market_intelligence"
JSONB = postgresql.JSONB


def upgrade() -> None:
    op.add_column(
        "bee_cfo_deliveries",
        sa.Column("media_message_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("bee_cfo_deliveries", "media_message_ids", schema=SCHEMA)
