"""Identify the owner by e-mail, add Google sign-in and fix publication states.

* ``admin_users`` gains ``email``, ``google_sub`` and ``login_method``;
  ``password_hash`` becomes nullable for Google-only accounts.
* The stored ``owner`` role is retired: ownership is derived only from
  ``MARKET_INTELLIGENCE_OWNER_EMAIL``. The pre-existing owner row (stored role
  ``owner``, otherwise ``MARKET_INTELLIGENCE_ADMIN_OWNER_USERNAME``) receives
  that address and keeps its password (``login_method = 'both'``) so the
  owner is never locked out before Google sign-in is configured.
* The publication status check now allows ``publishing`` (the send claim)
  and the ``archived``/``rejected`` states that bulk actions already write.
"""

import os
import re

from alembic import op
import sqlalchemy as sa


revision = "0037_owner_email_google_login"
down_revision = "0036_source_output_language"
branch_labels = None
depends_on = None

SCHEMA = "market_intelligence"
ROLES = ("admin", "assistant_admin", "editor", "analyst", "viewer")


def _normalize_email(value: str) -> str:
    # Mirrors app.google_auth.normalize_email; duplicated so the migration
    # never changes behaviour when application code evolves.
    value = value.strip().lower()
    local, _, domain = value.partition("@")
    if domain in {"gmail.com", "googlemail.com"}:
        local = local.split("+", 1)[0].replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"


def _drop_check(table: str, *names: str) -> None:
    for name in names:
        op.execute(f"ALTER TABLE {SCHEMA}.{table} DROP CONSTRAINT IF EXISTS {name}")


def upgrade() -> None:
    op.add_column("admin_users", sa.Column("email", sa.String(length=320), nullable=True), schema=SCHEMA)
    op.add_column("admin_users", sa.Column("google_sub", sa.String(length=255), nullable=True), schema=SCHEMA)
    op.add_column(
        "admin_users",
        sa.Column("login_method", sa.String(length=16), nullable=False, server_default="password"),
        schema=SCHEMA,
    )
    op.alter_column("admin_users", "password_hash", existing_type=sa.String(length=256), nullable=True, schema=SCHEMA)
    op.create_unique_constraint("uq_mi_admin_users_email", "admin_users", ["email"], schema=SCHEMA)
    op.create_unique_constraint("uq_mi_admin_users_google_sub", "admin_users", ["google_sub"], schema=SCHEMA)
    op.create_check_constraint(
        "admin_users_login_method",
        "admin_users",
        "login_method IN ('password', 'google', 'both')",
        schema=SCHEMA,
    )

    owner_email = _normalize_email(os.environ.get("MARKET_INTELLIGENCE_OWNER_EMAIL") or "farhad.dgm@gmail.com")
    owner_username = (os.environ.get("MARKET_INTELLIGENCE_ADMIN_OWNER_USERNAME") or "admin").strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", owner_email):
        raise RuntimeError("MARKET_INTELLIGENCE_OWNER_EMAIL is not a valid e-mail address")
    # Pure SQL (no Python-side SELECT) so the migration also renders in
    # offline ``--sql`` mode.  The owner row keeps its password.
    op.execute(
        sa.text(
            f"UPDATE {SCHEMA}.admin_users "
            "SET email = :email, login_method = 'both', role = 'admin', active = true "
            f"WHERE id = (SELECT id FROM {SCHEMA}.admin_users "
            "WHERE role = 'owner' OR lower(username) = :username "
            "ORDER BY (role = 'owner') DESC, created_at ASC LIMIT 1)"
        ).bindparams(email=owner_email, username=owner_username)
    )
    # Retire the stored owner role and quarantine unknown legacy values to the
    # least-privileged role before the check constraint is enforced.
    op.execute(f"UPDATE {SCHEMA}.admin_users SET role = 'admin' WHERE role = 'owner'")
    roles = ", ".join(f"'{role}'" for role in ROLES)
    op.execute(f"UPDATE {SCHEMA}.admin_users SET role = 'viewer' WHERE role NOT IN ({roles})")
    op.create_check_constraint(
        "admin_users_role",
        "admin_users",
        "role IN ('admin', 'assistant_admin', 'editor', 'analyst', 'viewer')",
        schema=SCHEMA,
    )

    _drop_check("publications", "publications_status", "ck_mi_publications_status")
    op.create_check_constraint(
        "publications_status",
        "publications",
        "status IN ('preview', 'publishing', 'published', 'edited', 'deleted', 'failed', 'archived', 'rejected')",
        schema=SCHEMA,
    )


def downgrade() -> None:
    _drop_check("publications", "publications_status", "ck_mi_publications_status")
    op.execute(
        f"UPDATE {SCHEMA}.publications SET status = 'preview' WHERE status = 'publishing'"
    )
    op.execute(
        f"UPDATE {SCHEMA}.publications SET status = 'deleted' WHERE status IN ('archived', 'rejected')"
    )
    op.create_check_constraint(
        "publications_status",
        "publications",
        "status IN ('preview', 'published', 'edited', 'deleted', 'failed')",
        schema=SCHEMA,
    )
    _drop_check(
        "admin_users",
        "admin_users_role",
        "ck_mi_admin_users_role",
        "admin_users_login_method",
        "ck_mi_admin_users_login_method",
    )
    # Restore the legacy ownership marker before the e-mail column goes, so
    # the previous release (and a later re-upgrade) find the same owner row.
    owner_email = _normalize_email(os.environ.get("MARKET_INTELLIGENCE_OWNER_EMAIL") or "farhad.dgm@gmail.com")
    op.execute(
        sa.text(f"UPDATE {SCHEMA}.admin_users SET role = 'owner' WHERE email = :email").bindparams(email=owner_email)
    )
    op.drop_constraint("uq_mi_admin_users_google_sub", "admin_users", schema=SCHEMA, type_="unique")
    op.drop_constraint("uq_mi_admin_users_email", "admin_users", schema=SCHEMA, type_="unique")
    op.execute(f"UPDATE {SCHEMA}.admin_users SET password_hash = '!' WHERE password_hash IS NULL")
    op.alter_column("admin_users", "password_hash", existing_type=sa.String(length=256), nullable=False, schema=SCHEMA)
    op.drop_column("admin_users", "login_method", schema=SCHEMA)
    op.drop_column("admin_users", "google_sub", schema=SCHEMA)
    op.drop_column("admin_users", "email", schema=SCHEMA)
