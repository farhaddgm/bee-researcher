"""Private reporting: frozen schema; no dependencies on evolving ORM metadata."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0046_report_portal"
down_revision = "0045_news_chat"
branch_labels = depends_on = None
S = "market_intelligence"


def uid(name="id", target=None, *, nullable=False, primary=False, ondelete="SET NULL"):
    args = [name, pg.UUID(as_uuid=True)]
    if target:
        args.append(sa.ForeignKey(f"{S}.{target}.id", ondelete=ondelete))
    return sa.Column(*args, nullable=nullable, primary_key=primary)


def stamp(name="created_at", *, nullable=False, default=True):
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=sa.func.now() if default else None,
    )


def upgrade():
    op.drop_constraint(
        op.f("ck_mi_admin_sessions_portal"), "admin_sessions", type_="check", schema=S
    )
    op.create_check_constraint(
        op.f("ck_mi_admin_sessions_portal"),
        "admin_sessions",
        "portal IN ('admin','user','report')",
        schema=S,
    )
    op.create_table(
        "report_businesses",
        uid(primary=True),
        sa.Column("source_ref", sa.String(512), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("policy", pg.JSONB(), nullable=False),
        uid("generation"),
        stamp(),
        sa.UniqueConstraint("source_ref", name="uq_report_business_source"),
        schema=S,
    )
    op.create_table(
        "report_project_bindings",
        uid(primary=True),
        uid("business_id", "report_businesses", ondelete="RESTRICT"),
        uid("assistant_id", "assistant_workspaces", nullable=True),
        sa.Column("source_ref", sa.String(512), nullable=False),
        sa.Column("generation", sa.String(128), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint(
            "business_id", "assistant_id", name="uq_report_business_project"
        ),
        schema=S,
    )
    op.create_table(
        "report_business_grants",
        uid(primary=True),
        uid("business_id", "report_businesses", ondelete="RESTRICT"),
        uid("user_id", "admin_users", nullable=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("assistant_ids", pg.JSONB(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        uid("granted_by", "admin_users", nullable=True),
        stamp("updated_at"),
        sa.UniqueConstraint("business_id", "user_id", name="uq_report_business_user"),
        sa.CheckConstraint("role IN ('reporter','manager')", name="report_grant_role"),
        schema=S,
    )
    op.create_table(
        "internal_reports",
        uid(primary=True),
        uid("business_id", "report_businesses", ondelete="RESTRICT"),
        uid("assistant_id", "assistant_workspaces", nullable=True),
        uid("author_id", "admin_users", nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        uid("current_version_id"),
        stamp(),
        stamp("expires_at", default=False),
        stamp("deleted_at", nullable=True, default=False),
        sa.CheckConstraint(
            "state IN ('draft','submitted','archived','deleted')",
            name="internal_report_state",
        ),
        schema=S,
    )
    op.create_index(
        "ix_mi_internal_reports_business_id",
        "internal_reports",
        ["business_id"],
        schema=S,
    )
    op.create_table(
        "internal_report_versions",
        uid(primary=True),
        uid("report_id", "internal_reports", ondelete="CASCADE"),
        sa.Column("number", sa.Integer(), nullable=False),
        uid("parent_id", nullable=True),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("classification", sa.String(24), nullable=False),
        stamp("sealed_at", nullable=True, default=False),
        stamp(),
        sa.UniqueConstraint("report_id", "number", name="uq_report_version_number"),
        schema=S,
    )
    op.create_index(
        "ix_mi_internal_report_versions_report_id",
        "internal_report_versions",
        ["report_id"],
        schema=S,
    )
    op.create_table(
        "internal_report_jobs",
        uid(primary=True),
        uid("report_id", "internal_reports", ondelete="CASCADE"),
        uid("version_id", "internal_report_versions", nullable=True),
        uid("business_id", "report_businesses", ondelete="RESTRICT"),
        uid("user_id", "admin_users", nullable=True),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        uid("policy_generation"),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("input_snapshot", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("reserved_usd", sa.Numeric(18, 8), nullable=False),
        sa.Column("actual_usd", sa.Numeric(18, 8)),
        stamp(),
        stamp("started_at", nullable=True, default=False),
        stamp("heartbeat_at", nullable=True, default=False),
        stamp("finished_at", nullable=True, default=False),
        sa.UniqueConstraint(
            "user_id", "idempotency_key", name="uq_report_submit_idempotency"
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','needs_input','failed','cancelled')",
            name="report_job_status",
        ),
        schema=S,
    )
    op.create_index(
        "ix_mi_internal_report_jobs_report_id",
        "internal_report_jobs",
        ["report_id"],
        schema=S,
    )
    op.create_index(
        "uq_report_running_business",
        "internal_report_jobs",
        ["business_id"],
        unique=True,
        postgresql_where=sa.text("status='running'"),
        schema=S,
    )
    op.create_index(
        "ix_report_queue", "internal_report_jobs", ["status", "created_at"], schema=S
    )
    op.create_index(
        "ix_report_daily_cost",
        "internal_report_jobs",
        ["business_id", "created_at"],
        schema=S,
    )
    op.create_table(
        "report_audit_events",
        uid(primary=True),
        uid("business_id", nullable=True),
        uid("user_id", nullable=True),
        uid("report_id", nullable=True),
        sa.Column("action", sa.String(48), nullable=False),
        stamp(),
        schema=S,
    )
    op.create_table(
        "report_deletions",
        uid("report_id", primary=True),
        stamp("deleted_at"),
        schema=S,
    )
    op.execute(
        sa.text(f"""CREATE FUNCTION {S}.sealed_report_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF OLD.sealed_at IS NOT NULL THEN RAISE EXCEPTION 'sealed report is immutable'; END IF;
        RETURN NEW;
      END $$""")
    )
    op.execute(
        sa.text(
            f"CREATE TRIGGER sealed_report_immutable BEFORE UPDATE ON {S}.internal_report_versions FOR EACH ROW EXECUTE FUNCTION {S}.sealed_report_immutable()"
        )
    )
    # Only the dedicated restricted identity is changed. Development DBs need
    # no production role. Do not rely on broad historical default privileges.
    op.execute(
        sa.text(f"""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='bee_researcher_runtime') THEN
        GRANT SELECT,INSERT,UPDATE,DELETE ON {S}.report_businesses,{S}.report_project_bindings,
          {S}.report_business_grants,{S}.internal_reports,{S}.internal_report_versions,
          {S}.internal_report_jobs TO bee_researcher_runtime;
        REVOKE UPDATE,DELETE,TRUNCATE ON {S}.report_audit_events,{S}.report_deletions FROM bee_researcher_runtime;
        GRANT SELECT,INSERT ON {S}.report_audit_events,{S}.report_deletions TO bee_researcher_runtime;
      END IF;
    END $$""")
    )


def downgrade():
    raise RuntimeError(
        "Disable report_portal_enabled; do not destroy private reports in a rollback"
    )
