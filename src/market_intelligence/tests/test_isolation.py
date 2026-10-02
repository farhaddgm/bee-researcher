import os
import unittest
from pathlib import Path


os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_DB", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_USER", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_REDIS_PASSWORD", "test-password")

from app.config import Settings  # noqa: E402
from app.models import Base, SCHEMA  # noqa: E402
from app.queue_names import get_queue_names, pipeline_lock_key, queue_key  # noqa: E402


class IsolationTest(unittest.TestCase):
    def settings(self) -> Settings:
        return Settings(
            postgres_db="assistant_test",
            postgres_user="assistant_test",
            postgres_password="secret",
            redis_password="secret",
            _env_file=None,
        )

    def test_all_tables_are_in_dedicated_schema(self):
        self.assertEqual("market_intelligence", SCHEMA)
        self.assertEqual(
            {
                "market_intelligence.service_state",
                "market_intelligence.assistant_workspaces",
                "market_intelligence.admin_users",
                "market_intelligence.admin_sessions",
                "market_intelligence.admin_audit_logs",
                "market_intelligence.assistant_members",
                "market_intelligence.job_runs",
                "market_intelligence.sources",
                "market_intelligence.source_items",
                "market_intelligence.source_fetch_runs",
                "market_intelligence.business_profiles",
                "market_intelligence.topics",
                "market_intelligence.normalized_articles",
                "market_intelligence.article_topics",
                "market_intelligence.event_clusters",
                "market_intelligence.cluster_members",
                "market_intelligence.article_analyses",
                "market_intelligence.publications",
                "market_intelligence.feedback",
                "market_intelligence.support_ticket_messages",
                "market_intelligence.weekly_reports",
                "market_intelligence.bee_cfo_profiles",
                "market_intelligence.bee_cfo_markets",
                "market_intelligence.bee_cfo_indicators",
                "market_intelligence.bee_cfo_indicator_sources",
                "market_intelligence.bee_cfo_assistant_indicator_selections",
                "market_intelligence.bee_cfo_price_snapshots",
                "market_intelligence.bee_cfo_price_deliveries",
                "market_intelligence.bee_cfo_sources",
                "market_intelligence.bee_cfo_watches",
                "market_intelligence.bee_cfo_snapshots",
                "market_intelligence.bee_cfo_reports",
                "market_intelligence.bee_cfo_deliveries",
                "market_intelligence.bee_cfo_forecasts",
                "market_intelligence.bee_cfo_forecast_evaluations",
                "market_intelligence.bee_cfo_factor_attributions",
                "market_intelligence.bee_cfo_price_forecasts",
                "market_intelligence.bee_cfo_price_forecast_evaluations",
                "market_intelligence.bee_cfo_alerts",
                "market_intelligence.bee_cfo_alert_rules",
                "market_intelligence.bee_cfo_market_events",
                "market_intelligence.bee_cfo_coverage_snapshots",
                "market_intelligence.bee_cfo_media_forecast_evaluations",
                "market_intelligence.bee_cfo_media_forecasts",
                "market_intelligence.bee_cfo_media_forecast_outcomes",
                "market_intelligence.bee_cfo_media_weighting_audits",
                "market_intelligence.bee_cfo_infrastructure_audits",
                "market_intelligence.bee_cfo_governance_events",
                "market_intelligence.support_tickets",
            },
            set(Base.metadata.tables),
        )
        self.assertTrue(
            all(table.schema == SCHEMA for table in Base.metadata.tables.values())
        )
        constraint_names = {
            constraint.name
            for table in Base.metadata.tables.values()
            for constraint in table.constraints
            if constraint.name is not None
        }
        self.assertIn("ck_mi_service_state_singleton", constraint_names)
        self.assertIn("ck_mi_job_runs_status", constraint_names)
        self.assertIn("ck_mi_sources_adapter", constraint_names)
        self.assertIn("ck_mi_source_fetch_runs_status", constraint_names)

    def test_queue_keys_have_a_dedicated_namespace(self):
        settings = self.settings()
        names = get_queue_names(settings)
        namespace = settings.queue_namespace
        self.assertEqual(f"{namespace}:runs", names.runs)
        self.assertEqual(f"{namespace}:dead-letter", names.dead_letter)
        self.assertEqual(f"{namespace}:scheduler-lock", names.scheduler_lock)
        self.assertNotIn("research_digest", names.runs)
        with self.assertRaises(ValueError):
            queue_key("../runs", settings=settings)

    def test_pipeline_locks_are_valid_and_workspace_specific(self):
        settings = self.settings()
        first = __import__("uuid").UUID("11111111-1111-1111-1111-111111111111")
        second = __import__("uuid").UUID("22222222-2222-2222-2222-222222222222")
        first_key = pipeline_lock_key(first, settings=settings)
        second_key = pipeline_lock_key(second, settings=settings)
        self.assertNotEqual(first_key, second_key)
        namespace = settings.queue_namespace
        self.assertTrue(first_key.startswith(f"{namespace}:pipeline_lock_"))
        self.assertNotIn(":", first_key.split(f"{namespace}:", 1)[1])

    def test_operational_models_have_workspace_owner(self):
        for table_name in (
            "job_runs", "sources", "source_items", "source_fetch_runs", "business_profiles",
            "topics", "normalized_articles", "article_topics", "event_clusters",
            "cluster_members", "article_analyses", "publications", "feedback", "weekly_reports",
            "bee_cfo_profiles", "bee_cfo_sources", "bee_cfo_watches", "bee_cfo_snapshots",
            "bee_cfo_reports", "bee_cfo_deliveries", "bee_cfo_forecasts", "bee_cfo_forecast_evaluations",
            "bee_cfo_factor_attributions", "bee_cfo_price_forecasts", "bee_cfo_price_forecast_evaluations",
            "bee_cfo_alerts", "bee_cfo_infrastructure_audits", "bee_cfo_governance_events",
        ):
            self.assertIn("assistant_id", Base.metadata.tables["market_intelligence." + table_name].columns)

    def test_pipeline_defaults_legacy_calls_to_the_stable_workspace(self):
        source = Path(__file__).resolve().parents[1].joinpath("app", "pipeline_service.py").read_text(encoding="utf-8")
        self.assertIn("assistant_id = assistant_id or DEFAULT_ASSISTANT_ID", source)
        self.assertIn("run_ingestion(source_keys, force=force_ingestion, assistant_id=assistant_id)", source)


if __name__ == "__main__":
    unittest.main()
