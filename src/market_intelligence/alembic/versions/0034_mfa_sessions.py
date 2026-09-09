"""Add MFA verification state to admin sessions."""

from alembic import op
import sqlalchemy as sa


revision = "0034_mfa_sessions"
down_revision = "0033_social_source_connectors"
branch_labels = None
depends_on = None

SCHEMA = "market_intelligence"


def upgrade() -> None:
    op.add_column(
        "admin_sessions",
        sa.Column("mfa_verified", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("admin_sessions", "mfa_verified", schema=SCHEMA)
