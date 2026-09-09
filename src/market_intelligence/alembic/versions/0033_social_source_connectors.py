"""Add secure social-source connector metadata."""

from alembic import op
import sqlalchemy as sa


revision = "0033_social_source_connectors"
down_revision = "0032_bee_cfo_provider_capacity_controls"
branch_labels = None
depends_on = None

SCHEMA = "market_intelligence"


def upgrade() -> None:
    op.alter_column("sources", "adapter", schema=SCHEMA, existing_type=sa.String(length=16), type_=sa.String(length=32), existing_nullable=False)
    op.add_column("sources", sa.Column("credential_ref", sa.String(length=128), nullable=True), schema=SCHEMA)
    op.add_column("sources", sa.Column("account_ref", sa.String(length=256), nullable=True), schema=SCHEMA)
    op.drop_constraint("sources_adapter", "sources", schema=SCHEMA, type_="check")
    op.create_check_constraint(
        "sources_adapter", "sources",
        "adapter IN ('rss', 'html', 'json', 'telegram_public', 'telegram_private', 'instagram_public', 'instagram_private', 'x_public', 'x_private')",
        schema=SCHEMA,
    )
    op.drop_constraint("sources_access_policy", "sources", schema=SCHEMA, type_="check")
    op.create_check_constraint(
        "sources_access_policy", "sources",
        "access_policy IN ('public_only', 'private_authenticated')",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint("sources_adapter", "sources", schema=SCHEMA, type_="check")
    op.create_check_constraint("sources_adapter", "sources", "adapter IN ('rss', 'html', 'json')", schema=SCHEMA)
    op.drop_constraint("sources_access_policy", "sources", schema=SCHEMA, type_="check")
    op.create_check_constraint("sources_access_policy", "sources", "access_policy IN ('public_only')", "sources", schema=SCHEMA)
    op.drop_column("sources", "account_ref", schema=SCHEMA)
    op.drop_column("sources", "credential_ref", schema=SCHEMA)
    op.alter_column("sources", "adapter", schema=SCHEMA, existing_type=sa.String(length=32), type_=sa.String(length=16), existing_nullable=False)
