"""Allow more than one business profile per assistant.

The MVP constrained business_profiles.id to 1.  The back-office now owns
profiles per assistant and needs to create/list/update them independently.
"""
from alembic import op
import sqlalchemy as sa


SCHEMA = "market_intelligence"
revision = "0010_multi_business_profiles"
down_revision = "0009_backoffice_ordering"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Alembic's naming convention prefixes the explicit legacy name once
    # more, so support both names for databases created by either revision.
    op.execute(sa.text(
        f"ALTER TABLE {SCHEMA}.business_profiles "
        "DROP CONSTRAINT IF EXISTS ck_mi_ck_mi_business_profiles_singleton, "
        "DROP CONSTRAINT IF EXISTS ck_mi_business_profiles_singleton"
    ))
    op.execute(sa.text(
        f"CREATE INDEX IF NOT EXISTS ix_mi_business_profiles_assistant "
        f"ON {SCHEMA}.business_profiles (assistant_id)"
    ))


def downgrade() -> None:
    op.drop_index("ix_mi_business_profiles_assistant", table_name="business_profiles", schema=SCHEMA, if_exists=True)
    # A downgrade is only safe while a single profile remains.
    op.create_check_constraint(
        "ck_mi_business_profiles_singleton",
        "business_profiles",
        "id = 1",
        schema=SCHEMA,
    )
