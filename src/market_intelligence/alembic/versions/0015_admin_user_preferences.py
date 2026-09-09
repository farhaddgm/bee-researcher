"""Store owner-controlled backoffice preferences."""

from alembic import op
import sqlalchemy as sa


revision = "0015_admin_user_preferences"
down_revision = "0014_soft_delete_assistants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "admin_users",
        sa.Column("preferences", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        schema="market_intelligence",
    )


def downgrade() -> None:
    op.drop_column("admin_users", "preferences", schema="market_intelligence")
