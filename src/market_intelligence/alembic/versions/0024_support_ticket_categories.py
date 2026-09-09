"""Add support ticket categories for a guided support workflow."""
from alembic import op
import sqlalchemy as sa

revision = "0024_support_ticket_categories"
down_revision = "0023_bee_cfo_benchmark"
branch_labels = None
depends_on = None
SCHEMA = "market_intelligence"

def upgrade() -> None:
    op.add_column("support_tickets", sa.Column("category", sa.String(64), nullable=False, server_default="other"), schema=SCHEMA)

def downgrade() -> None:
    op.drop_column("support_tickets", "category", schema=SCHEMA)
