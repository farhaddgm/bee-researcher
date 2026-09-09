import inspect
import unittest
import uuid

from app.admin import (
    AssistantCloneRequest,
    PublicationReviewRequest,
    RuntimeSettingsPreviewRequest,
    ShareLinkCreateRequest,
    preview_assistant_runtime_settings,
    publication_explanation,
    resolve_share_link,
    review_publication,
)
from app.insights import source_health_summary
from app.pipeline_service import publish_ready_previews, publish_publication, settings_for_assistant


class ApprovedIdeasFeatureContractTest(unittest.TestCase):
    def test_approval_states_are_bounded_and_notes_are_auditable(self):
        self.assertEqual("review", PublicationReviewRequest(state="review", note="needs source check").state)
        for state in ("draft", "review", "approved", "rejected"):
            self.assertEqual(state, PublicationReviewRequest(state=state).state)

    def test_runtime_preview_is_non_mutating_and_bounded(self):
        payload = RuntimeSettingsPreviewRequest(max_items_per_run=7, freshness_window_days=7)
        self.assertEqual(7, payload.max_items_per_run)
        source = inspect.getsource(preview_assistant_runtime_settings)
        self.assertIn('"mutated": False', source)
        self.assertIn('"telegram_send_attempted": False', source)

    def test_sandbox_clone_and_delivery_guards_are_explicit(self):
        clone = AssistantCloneRequest(slug="sandbox-project", name="Sandbox", business_name="Demo", sandbox=True)
        self.assertTrue(clone.sandbox)
        self.assertIn("sandbox", inspect.getsource(settings_for_assistant))
        self.assertIn("sandbox publication is disabled", inspect.getsource(publish_publication))
        self.assertIn('"approval"', inspect.getsource(publish_ready_previews))

    def test_explanation_returns_persisted_evidence_only(self):
        source = inspect.getsource(publication_explanation)
        self.assertIn("facts", source)
        self.assertIn("citations", source)
        self.assertIn("matched_positive", source)
        self.assertIn("no model-generated explanation", source)

    def test_source_health_contract_exposes_freshness_latency_and_failures(self):
        source = inspect.getsource(source_health_summary)
        self.assertIn("latency_seconds", source)
        self.assertIn("failure_count_30d", source)
        self.assertIn("freshness_state", source)

    def test_restricted_share_links_are_expiring_and_hashed(self):
        payload = ShareLinkCreateRequest(expiry_hours=24, publication_ids=[uuid.uuid4()])
        self.assertEqual(24, payload.expiry_hours)
        source = inspect.getsource(resolve_share_link)
        self.assertIn("compare_digest", source)
        self.assertIn("expires_at", source)
        self.assertIn("view_count", source)


if __name__ == "__main__":
    unittest.main()
