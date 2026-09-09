"""Make direct price units explicit and repair legacy TGJU API snapshots."""

from alembic import op
import sqlalchemy as sa


revision = "0027_bee_cfo_price_unit_contract"
down_revision = "0026_bee_cfo_weight_audit"
branch_labels = None
depends_on = None

SCHEMA = "market_intelligence"


def upgrade() -> None:
    # TGJU's HTML/API values for these IRR instruments are expressed in rials,
    # while Bee CFO's customer-facing catalog unit is toman.  The API payload
    # has no unit field, so the owner-approved catalog parser must carry it.
    op.execute(sa.text(f"""
        UPDATE {SCHEMA}.bee_cfo_indicator_sources
        SET parser_json = COALESCE(parser_json, '{{}}'::jsonb) || '{{"source_unit":"ریال","unit_policy":"owner_declared"}}'::jsonb,
            updated_at = NOW()
        WHERE source_key IN ('SRC-TGJU-API', 'SRC-TGJU-GOLD', 'SRC-TGJU-USD')
    """))
    op.execute(sa.text(f"""
        UPDATE {SCHEMA}.bee_cfo_indicator_sources
        SET parser_json = COALESCE(parser_json, '{{}}'::jsonb) || '{{"source_unit":"تومان","unit_policy":"owner_declared"}}'::jsonb,
            updated_at = NOW()
        WHERE source_key = 'SRC-NVSN-USD'
    """))

    # Snapshots created by v2.92.0's JSON adapter stored the raw rial number as
    # toman because the unitless API response was not normalized. Repair only
    # those rows, preserving an auditable copy of the original source value.
    op.execute(sa.text(f"""
        UPDATE {SCHEMA}.bee_cfo_price_snapshots AS snapshot
        SET value = snapshot.value / 10,
            previous_value = CASE WHEN snapshot.previous_value IS NULL THEN NULL ELSE snapshot.previous_value / 10 END,
            change_value = CASE WHEN snapshot.change_value IS NULL THEN NULL ELSE snapshot.change_value / 10 END,
            raw_quote = COALESCE(snapshot.raw_quote, '{{}}'::jsonb)
                || jsonb_build_object(
                    'source_quote_value', snapshot.value,
                    'unit_conversion', jsonb_build_object(
                        'source_unit', 'ریال',
                        'target_unit', 'تومان',
                        'operation', 'divide_by_10',
                        'reason', 'legacy_json_source_unit_repair'
                    )
                )
        WHERE snapshot.source_id = (
            SELECT source.id
            FROM {SCHEMA}.bee_cfo_indicator_sources AS source
            WHERE source.source_key = 'SRC-TGJU-API'
            LIMIT 1
        )
          AND COALESCE(snapshot.raw_quote, '{{}}'::jsonb) -> 'unit_conversion' IS NULL
    """))


def downgrade() -> None:
    # Historical numeric repair is intentionally not reversed: reversing it
    # would reintroduce the production data defect. Remove only the metadata
    # that this migration added to source parser contracts.
    op.execute(sa.text(f"""
        UPDATE {SCHEMA}.bee_cfo_indicator_sources
        SET parser_json = parser_json - 'source_unit' - 'unit_policy',
            updated_at = NOW()
        WHERE source_key IN ('SRC-TGJU-API', 'SRC-TGJU-GOLD', 'SRC-TGJU-USD', 'SRC-NVSN-USD')
    """))
