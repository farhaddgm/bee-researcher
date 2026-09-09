"""Give the legacy default workspace its product-facing Dotin name."""
from alembic import op
import sqlalchemy as sa

SCHEMA = "market_intelligence"
revision = "0008_default_workspace_name"
down_revision = "0007_sheet_media_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            f"UPDATE {SCHEMA}.assistant_workspaces "
            "SET name = 'داتین', updated_at = CURRENT_TIMESTAMP "
            "WHERE id = '00000000-0000-0000-0000-000000000001'::uuid "
            "AND name = 'Default workspace'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            f"UPDATE {SCHEMA}.assistant_workspaces "
            "SET name = 'Default workspace', updated_at = CURRENT_TIMESTAMP "
            "WHERE id = '00000000-0000-0000-0000-000000000001'::uuid "
            "AND name = 'داتین'"
        )
    )
