"""An append-only security journal independent of mutable operational history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0044_security_events"
down_revision = "0043_account_access"
branch_labels = depends_on = None
SCHEMA = "market_intelligence"


def upgrade():
    op.create_table("security_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True)),
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True)),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("details", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), schema=SCHEMA)
    op.create_index("ix_mi_security_events_created", "security_events", ["created_at"], schema=SCHEMA)
    op.execute(f"""CREATE FUNCTION {SCHEMA}.reject_security_event_mutation() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN RAISE EXCEPTION 'security events are append-only' USING ERRCODE = '42501'; END; $$""")
    op.execute(f"""CREATE TRIGGER security_events_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
        ON {SCHEMA}.security_events FOR EACH STATEMENT EXECUTE FUNCTION {SCHEMA}.reject_security_event_mutation()""")


def downgrade():
    raise RuntimeError("security events must be archived explicitly, never dropped by application rollback")
