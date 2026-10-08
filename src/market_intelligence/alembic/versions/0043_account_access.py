"""Account identity metadata and explicit isolation of Admin/User sessions.

Old sessions are classified as admin. Old reader cookies must sign in once
again; silently authorizing an ambiguous token in both portals is unsafe.
"""
from alembic import op
import sqlalchemy as sa

revision = "0043_account_access"
down_revision = "0042_research_context"
branch_labels = None
depends_on = None
SCHEMA = "market_intelligence"


def upgrade():
    # Older rows carry no portal discriminator: preserving them as "admin"
    # would let an old User token be moved into an Admin cookie. Invalidate
    # all legacy sessions once; identities, memberships and content survive.
    op.execute(f"DELETE FROM {SCHEMA}.admin_sessions")
    op.add_column("admin_users", sa.Column("display_name", sa.String(160)), schema=SCHEMA)
    op.add_column("admin_users", sa.Column("last_login_at", sa.DateTime(timezone=True)), schema=SCHEMA)
    op.add_column("admin_sessions", sa.Column("portal", sa.String(16), nullable=False, server_default="admin"), schema=SCHEMA)
    op.create_check_constraint("admin_sessions_portal", "admin_sessions", "portal IN ('admin', 'user')", schema=SCHEMA)


def downgrade():
    # Never leave User tokens usable as admin tokens in an older release.
    op.execute(f"DELETE FROM {SCHEMA}.admin_sessions WHERE portal = 'user'")
    op.drop_constraint(op.f("ck_mi_admin_sessions_portal"), "admin_sessions", schema=SCHEMA, type_="check")
    op.drop_column("admin_sessions", "portal", schema=SCHEMA)
    op.drop_column("admin_users", "last_login_at", schema=SCHEMA)
    op.drop_column("admin_users", "display_name", schema=SCHEMA)
