"""Add per-source publication language override."""

from alembic import op
import sqlalchemy as sa


revision = "0036_source_output_language"
down_revision = "0035_support_ticket_messages"
branch_labels = None
depends_on = None

SCHEMA = "market_intelligence"


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("output_language", sa.String(length=16), nullable=False, server_default="source"),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "sources_output_language",
        "sources",
        "output_language IN ('source', 'fa', 'en', 'tr', 'ar', 'it', 'es', 'de', 'fr')",
        schema=SCHEMA,
    )
    op.alter_column("sources", "output_language", server_default=None, schema=SCHEMA)


def downgrade() -> None:
    op.drop_constraint("sources_output_language", "sources", type_="check", schema=SCHEMA)
    op.drop_column("sources", "output_language", schema=SCHEMA)
