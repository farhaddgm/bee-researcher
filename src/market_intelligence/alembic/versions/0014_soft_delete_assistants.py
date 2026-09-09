"""Keep deleted projects recoverable for thirty days."""

from alembic import op
import sqlalchemy as sa


revision = "0014_soft_delete_assistants"
down_revision = "0013_admin_session_idle_cap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assistant_workspaces",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="market_intelligence",
    )
    op.create_index(
        "ix_mi_assistant_workspaces_deleted_at",
        "assistant_workspaces",
        ["deleted_at"],
        schema="market_intelligence",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mi_assistant_workspaces_deleted_at",
        table_name="assistant_workspaces",
        schema="market_intelligence",
    )
    op.drop_column("assistant_workspaces", "deleted_at", schema="market_intelligence")
