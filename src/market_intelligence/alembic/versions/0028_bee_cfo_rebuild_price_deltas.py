"""Rebuild Bee CFO price deltas after the legacy unit repair."""

from alembic import op
import sqlalchemy as sa


revision = "0028_bee_cfo_price_deltas"
down_revision = "0027_bee_cfo_price_unit_contract"
branch_labels = None
depends_on = None

SCHEMA = "market_intelligence"


def upgrade() -> None:
    # The previous_value column is denormalized for fast Telegram rendering.
    # Recompute it from the now-correct value sequence so a corrected current
    # quote cannot retain a -90% delta from a legacy tenfold snapshot.
    op.execute(sa.text(f"""
        WITH ordered AS (
            SELECT
                id,
                value,
                LAG(value) OVER (
                    PARTITION BY assistant_id, indicator_key
                    ORDER BY observed_at, id
                ) AS prior_value
            FROM {SCHEMA}.bee_cfo_price_snapshots
        )
        UPDATE {SCHEMA}.bee_cfo_price_snapshots AS snapshot
        SET previous_value = ordered.prior_value,
            change_value = CASE
                WHEN ordered.prior_value IS NULL THEN NULL
                ELSE ordered.value - ordered.prior_value
            END,
            change_percent = CASE
                WHEN ordered.prior_value IS NULL OR ordered.prior_value = 0 THEN NULL
                ELSE ((ordered.value - ordered.prior_value) / ordered.prior_value) * 100
            END
        FROM ordered
        WHERE snapshot.id = ordered.id
    """))


def downgrade() -> None:
    # Delta reconstruction is a data correction and is intentionally not
    # reversed because the pre-migration values were demonstrably defective.
    pass
