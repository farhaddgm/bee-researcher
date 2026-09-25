import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from dataclasses import replace
from types import SimpleNamespace


os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_DB", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_USER", "assistant_test")
os.environ.setdefault("MARKET_INTELLIGENCE_POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("MARKET_INTELLIGENCE_REDIS_PASSWORD", "test-password")

from app.bee_cfo.analysis import fallback_market_report  # noqa: E402
from app.bee_cfo.audit import run_infrastructure_audit  # noqa: E402
from app.bee_cfo.service import _governance_event_payload  # noqa: E402
from app.bee_cfo.contracts import (  # noqa: E402
    detect_state_changes,
    state_fingerprint,
    validate_market_report,
    validate_source_registration,
)
from app.bee_cfo.discovery import extract_feed_candidates  # noqa: E402
from app.bee_cfo.delivery import render_followup_messages, render_media_outlook_message, render_media_outlook_messages, render_price_message, render_report_message, validate_telegram_destination  # noqa: E402
from app.bee_cfo.factors import build_factor_attributions  # noqa: E402
from app.bee_cfo.forecasting import aggregate_calibration, build_price_forecasts, evaluate_price_forecast  # noqa: E402
from app.bee_cfo.price import (  # noqa: E402
    normalize_number,
    normalize_quote_unit,
    parse_price_text,
    validate_quote_delta,
    validate_quote_normalization,
    validate_quote_value,
)
from app.bee_cfo.indicators import _catalog_option_readiness, _source_uat_state  # noqa: E402
from app.bee_cfo.operations import assess_delivery_readiness  # noqa: E402
from app.bee_cfo.windows import filter_evidence_by_lookback, normalize_analysis_windows, price_comparison, window_label_fa  # noqa: E402
from app.bee_cfo.api import ConfigurationSyncRequest, IndicatorSelectionRequest  # noqa: E402
from app.bee_cfo.researcher_adapter import (  # noqa: E402
    MarketEvidence,
    cluster_evidence,
    is_relevant_to_watch,
)


class BeeCFOContractsTest(unittest.TestCase):
    def test_manual_pilot_readiness_does_not_require_an_automatic_schedule(self):
        result = assess_delivery_readiness(
            profile_status="testing",
            timezone_configured=True,
            has_schedule_slots=False,
            selected_market_configured=True,
            indicator_selected=True,
            active_source_count=1,
            active_watch_count=1,
            watches_reference_active_sources=True,
            telegram_token_configured=True,
            telegram_destination_configured=True,
        )
        self.assertTrue(result["manual_pilot"]["ready"])
        self.assertFalse(result["scheduled_delivery"]["ready"])
        self.assertIn("schedule slots", " ".join(result["scheduled_delivery"]["blockers"]))

    def test_scheduled_delivery_requires_an_active_profile_even_with_a_slot(self):
        result = assess_delivery_readiness(
            profile_status="testing",
            timezone_configured=True,
            has_schedule_slots=True,
            selected_market_configured=True,
            indicator_selected=True,
            active_source_count=1,
            active_watch_count=1,
            watches_reference_active_sources=True,
            telegram_token_configured=True,
            telegram_destination_configured=True,
        )
        self.assertTrue(result["manual_pilot"]["ready"])
        self.assertFalse(result["scheduled_delivery"]["ready"])
        self.assertIn("profile must be active", " ".join(result["scheduled_delivery"]["blockers"]))

    def test_manual_pilot_readiness_fails_closed_when_a_watch_lacks_an_active_source(self):
        result = assess_delivery_readiness(
            profile_status="testing",
            timezone_configured=True,
            has_schedule_slots=False,
            selected_market_configured=True,
            indicator_selected=True,
            active_source_count=1,
            active_watch_count=1,
            watches_reference_active_sources=False,
            telegram_token_configured=True,
            telegram_destination_configured=True,
        )
        self.assertFalse(result["manual_pilot"]["ready"])
        self.assertIn("every active watch", " ".join(result["manual_pilot"]["blockers"]))

    def test_analysis_windows_keep_price_default_and_use_seven_day_media_default(self):
        windows = normalize_analysis_windows()
        self.assertEqual(24, windows["price_comparison_window_hours"])
        self.assertEqual(168, windows["media_analysis_window_hours"])
        self.assertEqual(6, windows["price_comparison_tolerance_hours"])
        with self.assertRaises(ValueError):
            normalize_analysis_windows({"media_analysis_window_hours": 0})
        with self.assertRaises(ValueError):
            normalize_analysis_windows({"price_comparison_window_hours": {"hours": 24}})
        self.assertEqual("نامشخص", window_label_fa({"hours": 24}))

    def test_price_comparison_ignores_non_scalar_values(self):
        as_of = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
        comparison = price_comparison(
            [
                {"observed_at": as_of - timedelta(hours=24), "value": {"price": 100}},
                {"observed_at": as_of, "value": 105},
            ],
            as_of=as_of,
            window_hours=24,
            tolerance_hours=1,
        )
        self.assertEqual("unavailable", comparison["status"])
        self.assertIsNone(comparison["baseline_value"])
        decimal_comparison = price_comparison(
            [
                {"observed_at": as_of - timedelta(hours=24), "value": Decimal("100")},
                {"observed_at": as_of, "value": Decimal("105")},
            ],
            as_of=as_of,
            window_hours=24,
            tolerance_hours=1,
        )
        self.assertEqual(5.0, decimal_comparison["change_value"])

    def test_price_comparison_is_time_based_and_fails_closed(self):
        as_of = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
        observations = [
            {"observed_at": as_of - timedelta(hours=48), "value": 90},
            {"observed_at": as_of - timedelta(hours=24, minutes=2), "value": 100},
            {"observed_at": as_of - timedelta(hours=1), "value": 105},
        ]
        comparison = price_comparison(observations, as_of=as_of, window_hours=24, tolerance_hours=1)
        self.assertEqual("available", comparison["status"])
        self.assertEqual(5, comparison["change_value"])
        missing = price_comparison(observations[:1], as_of=as_of, window_hours=24, tolerance_hours=1)
        self.assertEqual("unavailable", missing["status"])
        self.assertIsNone(missing["change_percent"])

    def test_price_comparison_accepts_the_closest_observation_after_target(self):
        as_of = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
        comparison = price_comparison(
            [
                {"observed_at": as_of - timedelta(hours=22, minutes=45), "value": 100},
                {"observed_at": as_of, "value": 105},
            ],
            as_of=as_of,
            window_hours=24,
            tolerance_hours=2,
        )
        self.assertEqual("available", comparison["status"])
        self.assertEqual(100, comparison["baseline_value"])
        self.assertEqual("nearest_observation_within_tolerance", comparison["policy"])

    def test_media_analysis_lookback_excludes_old_and_future_evidence(self):
        as_of = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
        base = dict(
            title="خبر",
            text="متن",
            source_key="SRC",
            source_name="منبع",
            source_url="https://example.com/news",
            source_origin="user",
            source_authority="news",
            discovery_path="user_provided",
            discovered_at=as_of - timedelta(hours=1),
            extraction_status="ok",
            quality_score=1.0,
            provenance={},
        )
        recent = MarketEvidence(**base, published_at=as_of - timedelta(hours=2))
        old = MarketEvidence(**base, published_at=as_of - timedelta(hours=25))
        future = MarketEvidence(**base, published_at=as_of + timedelta(hours=1))
        included, meta = filter_evidence_by_lookback([recent, old, future], as_of=as_of, hours=24)
        self.assertEqual([recent], included)
        self.assertEqual(2, meta["excluded_out_of_window_count"])

    def test_discovered_sources_are_never_auto_activated(self):
        with self.assertRaises(ValueError):
            validate_source_registration(
                {
                    "source_key": "BC-001",
                    "name": "Discovered",
                    "homepage_url": "https://example.com",
                    "fetch_url": "https://example.com/feed",
                    "origin": "discovered",
                    "status": "active",
                }
            )

    def test_report_requires_three_testable_scenarios(self):
        report = {
            "current_state": {"summary": "summary"},
            "scenarios": [
                {"key": "base", "title": "Base", "probability": 0.5, "horizon": "7d", "expected_change": "flat", "triggers": ["data"], "invalidation": "new data"},
                {"key": "upside", "title": "Up", "probability": 0.3, "horizon": "7d", "expected_change": "up", "triggers": ["data"], "invalidation": "new data"},
                {"key": "downside", "title": "Down", "probability": 0.2, "horizon": "7d", "expected_change": "down", "triggers": ["data"], "invalidation": "new data"},
            ],
            "changes": [],
            "uncertainties": ["limited data"],
            "citations": [],
            "confidence": 0.4,
        }
        normalized = validate_market_report(report)
        self.assertEqual(3, len(normalized["scenarios"]))
        with self.assertRaises(ValueError):
            validate_market_report({**report, "scenarios": report["scenarios"][:2]})

    def test_phase_one_rejects_personalized_advice(self):
        with self.assertRaises(ValueError):
            validate_market_report(
                {
                    "current_state": {},
                    "scenarios": [
                        {"key": "base", "title": "Base", "probability": 0.5, "horizon": "7d", "expected_change": "سبد شما را بخر", "triggers": ["data"], "invalidation": "new data"},
                        {"key": "up", "title": "Up", "probability": 0.3, "horizon": "7d", "expected_change": "up", "triggers": ["data"], "invalidation": "new data"},
                        {"key": "down", "title": "Down", "probability": 0.2, "horizon": "7d", "expected_change": "down", "triggers": ["data"], "invalidation": "new data"},
                    ],
                    "changes": [], "uncertainties": [], "citations": [], "confidence": 0.2,
                }
            )

    def test_snapshot_fingerprint_and_delta_are_stable(self):
        before = {"summary": "old", "facts": ["a"]}
        after = {"summary": "new", "facts": ["a"]}
        self.assertEqual(state_fingerprint(after), state_fingerprint(after))
        changes = detect_state_changes(before, after)
        self.assertEqual("summary", changes[0]["field"])


class BeeCFOAnalysisTest(unittest.TestCase):
    def test_deterministic_fallback_has_sources_and_probabilities(self):
        evidence = [
            MarketEvidence(
                title="گزارش بازار",
                text="متن گزارش بازار",
                source_key="BC-001",
                source_name="منبع رسمی",
                source_url="https://example.com/report",
                source_origin="user",
                source_authority="official",
                discovery_path="user_provided",
                published_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
                discovered_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
                extraction_status="complete",
                quality_score=0.9,
                provenance={},
            )
        ]
        payload = fallback_market_report(watch={"name": "بازار نمونه"}, evidence=evidence)
        self.assertAlmostEqual(1.0, sum(item["probability"] for item in payload["scenarios"]))
        self.assertEqual(1, len(payload["citations"]))
        self.assertEqual(0, payload["current_state"]["valid_evidence_count"])
        self.assertEqual("degraded", payload["current_state"]["quality_status"])

    def test_fallback_uses_quantitative_text_as_a_market_observation(self):
        evidence = [
            MarketEvidence(
                title="قیمت دلار",
                text="قیمت دلار در آخرین معامله ۵۹,۸۰۰ تومان ثبت شد و تغییر روزانه ۲.۱ درصد افزایش داشت.",
                source_key="BC-001",
                source_name="منبع رسمی",
                source_url="https://example.com/usd",
                source_origin="user",
                source_authority="official",
                discovery_path="user_provided",
                published_at=None,
                discovered_at=None,
                extraction_status="complete",
                quality_score=0.9,
                provenance={},
            )
        ]
        payload = fallback_market_report(watch={"name": "دلار بازار آزاد"}, evidence=evidence)
        self.assertEqual(1, payload["current_state"]["valid_evidence_count"])
        self.assertEqual("good", payload["current_state"]["quality_status"])
        self.assertIn("قیمت دلار", payload["current_state"]["facts"][0])

    def test_fallback_reports_the_explicit_forward_view_of_news_media(self):
        evidence = [
            MarketEvidence(
                title="چشم‌انداز بازار",
                text="این رسانه پیش‌بینی می‌کند قیمت طلا در هفته آینده افزایش یابد و قیمت فعلی ۵۹۸۰۰ است.",
                source_key="MEDIA-001",
                source_name="رسانه نمونه",
                source_url="https://example.com/outlook",
                source_origin="user",
                source_authority="news",
                discovery_path="user_provided",
                published_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
                discovered_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
                extraction_status="complete",
                quality_score=0.9,
                provenance={},
            )
        ]
        payload = fallback_market_report(watch={"name": "بازار نمونه"}, evidence=evidence)
        perspective = payload["current_state"]["media_perspectives"][0]
        self.assertEqual("رسانه نمونه", perspective["source_name"])
        self.assertEqual("explicit_opinion", perspective["evidence_type"])
        self.assertEqual("up", perspective["stance"])
        self.assertIn("افزایش یابد", perspective["view"])

    def test_media_perspective_drops_news_site_boilerplate(self):
        evidence = [
            MarketEvidence(
                title="Gold rises",
                text=(
                    "Gold prices rose and analysts expect further gains next week. "
                    "Copyright Business Recorder, 2026 SC order on PTI founder's medical checkup."
                ),
                source_key="MEDIA-BR",
                source_name="Business Recorder",
                source_url="https://example.com/gold",
                source_origin="discovered",
                source_authority="news",
                discovery_path="owner_requested_live_publish",
                published_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
                discovered_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
                extraction_status="complete",
                quality_score=0.9,
                provenance={},
            )
        ]
        payload = fallback_market_report(watch={"name": "طلای ۱۸ عیار"}, evidence=evidence)
        view = payload["current_state"]["media_perspectives"][0]["view"]
        self.assertNotIn("SC order", view)
        self.assertIn("expect further gains", view)

    def test_media_perspective_does_not_turn_unrelated_future_sentence_into_gold_view(self):
        evidence = [
            MarketEvidence(
                title="Gold rallies",
                text="Gold prices rallied today. The treasury secretary said fiscal consolidation will be the next strategy.",
                source_key="MEDIA-UNRELATED",
                source_name="Market source",
                source_url="https://example.com/gold",
                source_origin="discovered",
                source_authority="news",
                discovery_path="owner_requested_live_publish",
                published_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
                discovered_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
                extraction_status="complete",
                quality_score=0.9,
                provenance={},
            )
        ]
        payload = fallback_market_report(watch={"name": "طلای ۱۸ عیار"}, evidence=evidence)
        perspective = payload["current_state"]["media_perspectives"][0]
        self.assertEqual("no_explicit_opinion", perspective["evidence_type"])

    def test_watch_relevance_rejects_unrelated_instruments_and_navigation(self):
        gold_watch = SimpleNamespace(
            name="طلای ۱۸ عیار",
            market="Iran 18k gold",
            asset_class="gold",
            currency="IRR",
            watch_key="WATCH-IR-GOLD-18K-001",
        )
        self.assertTrue(
            is_relevant_to_watch(
                watch=gold_watch,
                title="طلای 18 عیار",
                url="https://www.tgju.org/profile/geram18",
            )
        )
        self.assertFalse(
            is_relevant_to_watch(
                watch=gold_watch,
                title="فرانک سویس",
                url="https://www.navasan.net/dayRates.php?item=chf",
            )
        )


        self.assertFalse(
            is_relevant_to_watch(
                watch=gold_watch,
                title="Terms & Disclaimer",
                url="https://www.bonbast.com/disclaimer",
            )
        )
        self.assertFalse(
            is_relevant_to_watch(
                watch=gold_watch,
                title="گزارش 18 دستگاه صنعتی",
                url="https://example.com/news/18",
            )
        )
        usd_watch = SimpleNamespace(
            name="دلار بازار آزاد",
            market="IRR/USD free market",
            asset_class="currency",
            currency="IRR",
            watch_key="WATCH-IR-USD-FREE-001",
        )
        self.assertTrue(
            is_relevant_to_watch(
                watch=usd_watch,
                title="دلار آمریکا",
                url="https://www.navasan.net/dayRates.php?item=usd",
            )
        )
        self.assertFalse(
            is_relevant_to_watch(
                watch=usd_watch,
                title="دلار سنگاپور",
                url="https://www.navasan.net/dayRates.php?item=sgd",
            )
        )
        self.assertFalse(
            is_relevant_to_watch(
                watch=usd_watch,
                title="نمای کلی",
                url="https://www.tgju.org/currency",
            )
        )

    def test_near_duplicate_event_narratives_are_clustered_without_losing_sources(self):
        base = MarketEvidence(
            title="ابلاغ دستورالعمل جدید بانک مرکزی به بانک‌ها",
            text="متن",
            source_key="BC-001",
            source_name="منبع یک",
            source_url="https://example.com/one",
            source_origin="user",
            source_authority="official",
            discovery_path="user_provided",
            published_at=None,
            discovered_at=None,
            extraction_status="complete",
            quality_score=0.8,
            provenance={},
        )
        duplicate = replace(
            base,
            title="دستورالعمل جدید بانک مرکزی ابلاغ شد",
            source_key="BC-002",
            source_name="منبع دو",
            source_url="https://example.com/two",
        )
        clusters = cluster_evidence([base, duplicate])
        self.assertEqual(1, len(clusters))
        self.assertEqual(2, len(clusters[0]))


class BeeCFOPriceContractTest(unittest.TestCase):
    def test_price_parser_requires_explicit_indicator_label(self):
        self.assertEqual(19000100, parse_price_text("هر گرم طلای ۱۸ عیار: ۱۹،۰۰۰،۱۰۰ تومان", "gold_18k"))
        self.assertEqual(59800, parse_price_text("دلار آمریکا ۵۹,۸۰۰ تومان", "usd_free"))
        self.assertIsNone(parse_price_text("عدد ۹۹۹۹ بدون نام شاخص", "gold_18k"))

    def test_price_parser_prefers_structured_current_quote_over_menu_numbers(self):
        html = (
            '<a>طلای 18 عیار</a><a>طلای 24 عیار</a>'
            '<span data-col="info.last_trade.PDrCotVal">217,464,000</span>'
        )
        self.assertEqual(217464000, parse_price_text(html, "gold_18k"))

    def test_price_parser_converts_explicit_source_riyal_to_catalog_toman(self):
        value, conversion = normalize_quote_unit(
            217464000,
            body="<span>واحد پولی :</span><span>ریال</span>",
            target_unit="تومان",
        )
        self.assertEqual(21746400, value)
        self.assertEqual("divide_by_10", conversion["operation"])

    def test_price_parser_applies_owner_unit_contract_to_unitless_api_quotes(self):
        value, conversion = normalize_quote_unit(
            221282000,
            body="",
            target_unit="تومان",
            configured_source_unit="ریال",
        )
        self.assertEqual(22128200, value)
        self.assertEqual("ریال", conversion["source_unit"])
        self.assertEqual("source_contract_declares_riyal", conversion["reason"])
        self.assertEqual(
            22128200,
            validate_quote_normalization(221282000, value, conversion, target_unit="تومان"),
        )

    def test_price_parser_rejects_unitless_fiat_api_quote(self):
        value, conversion = normalize_quote_unit(221282000, body="", target_unit="تومان")
        with self.assertRaisesRegex(ValueError, "source unit is not explicit"):
            validate_quote_normalization(221282000, value, conversion, target_unit="تومان")

    def test_price_parser_rejects_conflicting_page_and_owner_units(self):
        with self.assertRaisesRegex(ValueError, "conflicts"):
            normalize_quote_unit(
                221282000,
                body="واحد پولی: تومان",
                target_unit="تومان",
                configured_source_unit="ریال",
            )

    def test_price_safety_blocks_tenfold_unit_jump(self):
        with self.assertRaisesRegex(ValueError, "delivery held"):
            validate_quote_delta(22128200, 221282000)
        self.assertLess(validate_quote_delta(21746400, 22128200), 0.75)
        self.assertEqual(0.0, validate_quote_delta(None, 22128200))

    def test_price_number_supports_persian_and_json_decimals(self):
        self.assertEqual(19000100, normalize_number("۱۹،۰۰۰،۱۰۰"))
        self.assertAlmostEqual(105432.12, normalize_number("105432.12"))

    def test_price_safety_rejects_navigation_numbers(self):
        with self.assertRaises(ValueError):
            validate_quote_value(24, "gold_18k")
        self.assertEqual(210360000, validate_quote_value(210360000, "gold_18k"))

    def test_price_renderer_has_standalone_first_message_shape(self):
        message = render_price_message(
            snapshot={
                "indicator_key": "GOLD_18K",
                "indicator_name": "هر گرم طلای ۱۸ عیار",
                "value": 19000100,
                "change_value": 125000,
                "change_percent": 0.66,
                "comparison": {
                    "status": "available",
                    "window_hours": 24,
                    "change_value": 125000,
                    "change_percent": 0.66,
                },
                "quote_unit": "تومان",
                "currency": "IRR",
                "observed_at": "2026-08-22T13:02:00+00:00",
                "source_name": "TGJU",
                "source_url": "https://www.tgju.org/profile/geram18",
            }
        )
        self.assertIn("قیمت طلای ۱۸ عیار", message)
        self.assertIn("هر گرم طلای ۱۸ عیار", message)
        self.assertIn("۱۹،۰۰۰،۱۰۰", message)
        self.assertIn("مقایسه با ۱ روز قبل", message)
        self.assertIn("۳۱ مرداد ۱۴۰۵ - ۱۶:۳۲", message)
        self.assertNotIn("تغییر:", message)
        self.assertIn("مرجع: TGJU", message)
        self.assertNotIn('href="https://www.tgju.org/"', message)
        self.assertLessEqual(len(message), 1200)

    def test_indicator_selection_contract_has_owner_catalog_keys(self):
        payload = IndicatorSelectionRequest(market_key="IR_GOLD", indicator_key="GOLD_18K")
        self.assertEqual("active", payload.status)
        self.assertEqual("GOLD_18K", payload.indicator_key)

    def test_catalog_source_uat_gate_distinguishes_passed_pending_and_approval(self):
        self.assertEqual("passed", _source_uat_state(SimpleNamespace(status="active", last_success_at=datetime.now(timezone.utc))))
        self.assertEqual("pending_uat", _source_uat_state(SimpleNamespace(status="active", last_success_at=None)))
        self.assertEqual("approval_required", _source_uat_state(SimpleNamespace(status="draft", last_success_at=None)))

    def test_catalog_option_readiness_does_not_promote_draft_sources(self):
        market = SimpleNamespace(market_key="GLOBAL_CRYPTO", status="active")
        indicator = SimpleNamespace(indicator_key="BTC_USDT", display_name="قیمت بیت‌کوین", status="active")
        draft = SimpleNamespace(
            id="source-id",
            source_key="SRC-CG-BTC",
            name="CoinGecko",
            homepage_url="https://www.coingecko.com/",
            fetch_url="https://api.coingecko.com/api/v3/simple/price",
            adapter="json",
            priority=3,
            status="draft",
            last_checked_at=None,
            last_success_at=None,
            last_error=None,
        )
        result = _catalog_option_readiness(market=market, indicator=indicator, sources=[draft], selected=False)
        self.assertEqual("approval_required", result["status"])
        self.assertFalse(result["ready_for_delivery"])
        self.assertIn("explicit owner approval", " ".join(result["blockers"]))


class BeeCFOFactorForecastTest(unittest.TestCase):
    def _evidence(self, text: str, *, key: str = "SRC-001", authority: str = "official") -> MarketEvidence:
        return MarketEvidence(
            title="گزارش بازار",
            text=text,
            source_key=key,
            source_name=key,
            source_url=f"https://example.com/{key}",
            source_origin="user",
            source_authority=authority,
            discovery_path="user_provided",
            published_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
            discovered_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
            extraction_status="complete",
            quality_score=0.9,
            provenance={},
        )

    def test_factor_cards_preserve_evidence_without_causal_overclaim(self):
        result = build_factor_attributions([
            self._evidence("افزایش نرخ بهره و رشد بازده اوراق، فشار نزولی بر طلا ایجاد کرد."),
            self._evidence("دلار در بازار آزاد افزایش یافت و پریمیوم داخلی بالا رفت.", key="SRC-002"),
        ])
        self.assertEqual("available", result["status"])
        self.assertGreaterEqual(len(result["factors"]), 2)
        self.assertTrue(all(item["attribution_kind"] in {"explicit_driver", "co_movement"} for item in result["factors"]))
        self.assertTrue(all("caus" not in str(item).lower() for item in result["factors"]))
        self.assertTrue(all(item["evidence"][0]["source_url"].startswith("https://") for item in result["factors"]))

    def test_conflicting_factor_direction_is_unknown(self):
        result = build_factor_attributions([
            self._evidence("دلار افزایش یافت و فشار صعودی ثبت شد.", key="SRC-UP"),
            self._evidence("دلار کاهش یافت و فشار نزولی ثبت شد.", key="SRC-DOWN"),
        ])
        factor = next(item for item in result["factors"] if item["factor_key"] == "fx_local_premium")
        self.assertEqual("unknown", factor["direction"])
        self.assertTrue(factor["conflict"])

    def test_numeric_forecast_returns_no_call_without_history(self):
        result = build_price_forecasts([], as_of=datetime(2026, 8, 22, tzinfo=timezone.utc))
        self.assertEqual("no_call", result["status"])
        self.assertEqual([], result["forecasts"])

    def test_numeric_forecast_and_calibration_are_deterministic(self):
        observations = [
            {"observed_at": datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index), "value": 100 + index * 0.2}
            for index in range(60)
        ]
        result = build_price_forecasts(observations, as_of=datetime(2026, 3, 2, tzinfo=timezone.utc))
        self.assertEqual("available", result["status"])
        self.assertEqual([1, 7, 30], [row["horizon_days"] for row in result["forecasts"]])
        self.assertEqual("available", result["forecasts"][0]["metrics"]["walk_forward"]["status"])
        self.assertIn("benchmark", result["forecasts"][0]["metrics"])
        self.assertEqual("no_call", result["model_availability"]["macro_factor_model"]["status"])
        self.assertIn("statistical_weight", result["forecasts"][0]["components"])
        evaluated = evaluate_price_forecast(result["forecasts"][1], 113.0)
        self.assertIn("brier_score", evaluated)
        summary = aggregate_calibration([evaluated])
        self.assertEqual(1, summary["sample_size"])
        self.assertIsNotNone(summary["mae"])

    def test_forecast_evaluation_ignores_malformed_optional_probability_metrics(self):
        evaluated = evaluate_price_forecast(
            {
                "baseline_value": 100,
                "point_value": 101,
                "probability_up": object(),
                "probability_down": float("nan"),
                "probability_flat": object(),
            },
            102,
        )
        self.assertEqual("up", evaluated["predicted_direction"])
        self.assertGreaterEqual(evaluated["brier_score"], 0)
        self.assertLessEqual(evaluated["brier_score"], 1)
        summary = aggregate_calibration([
            {"absolute_error": object(), "brier_score": "not-a-number"},
            {"absolute_error": 2, "brier_score": 0.25},
        ])
        self.assertEqual(2, summary["sample_size"])
        self.assertEqual(2.0, summary["mae"])
        self.assertEqual(0.25, summary["mean_brier_score"])


class BeeCFODiscoveryTest(unittest.TestCase):
    def test_same_domain_feed_declarations_become_draft_candidates(self):
        candidates = extract_feed_candidates(
            '<link rel="alternate" type="application/rss+xml" href="/feed.xml">'
            '<link rel="alternate" type="application/json" href="https://other.example/feed.json">',
            "https://example.com/",
        )
        self.assertEqual(1, len(candidates))
        self.assertEqual("rss", candidates[0].adapter)
        self.assertEqual("domain_discovery", candidates[0].discovery_path)


class BeeCFOAuditTest(unittest.TestCase):
    def test_reuse_audit_is_passed_and_separable(self):
        result = run_infrastructure_audit()
        self.assertEqual("passed", result["status"])
        self.assertEqual("adapter_boundary_ready", result["decision"]["separability"])
        self.assertIn("app.consultant_bee", result["decision"]["forbidden_dependencies"])
        self.assertFalse(result["isolation_contract"]["shared_runtime_state"])

    def test_governance_events_use_their_own_payload_contract(self):
        event = SimpleNamespace(
            id="event-id",
            assistant_id="assistant-id",
            category="pilot_run",
            event_key="report-id",
            status="passed",
            payload={"quality_gate": "passed"},
            created_at=datetime(2026, 9, 25, tzinfo=timezone.utc),
        )

        result = _governance_event_payload(event)

        self.assertEqual("pilot_run", result["category"])
        self.assertEqual("report-id", result["event_key"])
        self.assertEqual({"quality_gate": "passed"}, result["payload"])


class BeeCFODeliveryTest(unittest.TestCase):
    def test_followup_cards_are_additive_bounded_and_evidence_first(self):
        report = {
            "scenarios": [
                {
                    "key": "base", "title": "پایه", "probability": 0.5,
                    "expected_change": "نوسان در بازه ثبت‌شده",
                    "triggers": ["پایداری نرخ مرجع"],
                    "invalidation": "شکست سطح مرجع با شاهد تازه",
                    "evidence": [{"source_name": "رسانه نمونه · طلا", "source_url": "https://example.com/scenario"}],
                }
            ],
            "current_state": {
                "live_price": {"quote_unit": "تومان", "value": 22000000, "price_source_health": {"selected_source": "TGJU"}},
                "factor_attributions": [
                    {
                        "label": "بازده اوراق", "direction": "down", "strength": "strong",
                        "attribution_kind": "explicit_driver", "invalidation": "کاهش بازده تأییدشده",
                        "evidence": [{"source_name": "رسانه نمونه · طلا", "source_url": "https://example.com/factor", "published_at": "2026-08-24T12:00:00+00:00", "snippet": "بازده بالا مانع رشد طلا شد."}],
                    }
                ],
                "price_forecast": {
                    "status": "available",
                    "forecasts": [{"horizon_days": 7, "point_value": 22100000, "lower_value": 21500000, "upper_value": 22700000, "probability_up": 0.5, "probability_down": 0.3, "probability_flat": 0.2}],
                },
                "model_agreement": {"status": "available", "label": "هم‌جهت"},
                "coverage_score": {"score": 0.7, "status": "partial", "missing": ["benchmark", "quote"]},
                "confidence_budget": {"overall": 0.6, "label": "متوسط", "missing": ["forecast_quality"]},
                "events": [{"title": "رویداد نمونه", "source_keys": ["MEDIA-A"], "source_urls": ["https://example.com/event"], "published_at": "2026-08-24T12:00:00+00:00"}],
                "open_checks": [{"status": "open", "label": "مرجع مقایسه‌ای", "next_action": "ثبت منبع تأییدشده"}],
                "media_history": [{"transition": "up → down", "items": [{"source_name": "رسانه نمونه · طلا", "source_url": "https://example.com/history"}]}],
            },
        }
        messages = render_followup_messages(report=report, watch_name="طلای ۱۸ عیار")
        rendered = "\n---\n".join(messages)
        self.assertEqual(["🧩", "🔭", "🎯", "🧪", "🗓"], [message[:1] for message in messages])
        self.assertTrue(all(len(message) <= 1200 for message in messages))
        self.assertIn('href="https://example.com/factor">رسانه نمونه</a>', rendered)
        self.assertIn("شرط نقض", rendered)
        self.assertIn("نیازمند تکمیل: مرجع مقایسه‌ای", rendered)
        self.assertNotIn("نیازمند تکمیل: قیمت مرجع", rendered)

    def test_followup_forecast_card_is_suppressed_for_no_call(self):
        messages = render_followup_messages(
            report={"current_state": {"price_forecast": {"status": "no_call", "reason": "تاریخچه کافی نیست"}}},
            watch_name="طلای ۱۸ عیار",
        )
        self.assertFalse(any(message.startswith("🔭") for message in messages))

    def test_report_renderers_ignore_malformed_and_non_finite_persisted_values(self):
        report = {
            "confidence": float("nan"),
            "current_state": {
                "summary": {"unexpected": ["object"]},
                "facts": ["یک داده محدود"],
                "raw_evidence_count": "not-a-count",
                "valid_evidence_count": float("inf"),
                "source_count": [],
                "price_comparison": {"window_hours": {"unexpected": "value"}, "status": "available"},
                "analysis_windows": [],
                "price_forecast": {
                    "status": "available",
                    "forecasts": [{
                        "horizon_days": 7,
                        "point_value": float("inf"),
                        "lower_value": float("nan"),
                        "upper_value": 120,
                    }],
                },
                "coverage_score": {"status": "partial", "score": float("nan")},
                "events": {"unexpected": "object"},
                "media_perspectives": [None, "malformed"],
            },
            "scenarios": {"unexpected": "object"},
            "citations": None,
            "changes": "not-a-list",
            "uncertainties": 17,
        }

        rendered = render_report_message(report=report, watch_name="طلای ۱۸ عیار")
        followups = render_followup_messages(report=report, watch_name="طلای ۱۸ عیار")
        media = render_media_outlook_messages(report=report, watch_name="طلای ۱۸ عیار")

        self.assertIn("داده‌ی معتبر", rendered)
        self.assertNotIn("nan", rendered.lower())
        self.assertNotIn("inf", rendered.lower())
        self.assertTrue(all("nan" not in message.lower() and "inf" not in message.lower() for message in followups))
        self.assertEqual(2, len(media))

    def test_followup_monitor_card_filters_events_unrelated_to_selected_gold_market(self):
        messages = render_followup_messages(
            report={"current_state": {
                "events": [
                    {"title": "پزشکیان: در جنگ تمام‌عیار اقتصادی و نظامی هستیم", "source_urls": ["https://example.com/general"]},
                    {"title": "Gold rallies to a three-month high", "source_urls": ["https://example.com/gold"]},
                ],
                "open_checks": [{"status": "open", "label": "مرجع مقایسه‌ای", "next_action": "ثبت منبع"}],
            }},
            watch_name="طلای ۱۸ عیار",
        )
        monitor = next(message for message in messages if message.startswith("🗓"))
        self.assertIn("Gold rallies", monitor)
        self.assertNotIn("پزشکیان", monitor)

    def test_media_outlook_renderer_groups_explicit_views_and_links_sources(self):
        message = render_media_outlook_message(
            watch_name="طلای ۱۸ عیار",
            report={
                "current_state": {
                    "media_perspectives": [
                        {
                            "source_name": "رسانه صعودی",
                            "source_url": "https://example.com/up",
                            "stance": "up",
                            "horizon": "۴۸ ساعت",
                            "evidence_type": "explicit_opinion",
                            "view": "این رسانه انتظار افزایش قیمت طلا را دارد.",
                        },
                        {
                            "source_name": "رسانه بدون پیش‌بینی",
                            "source_url": "https://example.com/unknown",
                            "stance": "unknown",
                            "horizon": "نامشخص",
                            "evidence_type": "no_explicit_opinion",
                            "view": "نظر صریحی درباره روند آتی بازار پیدا نشد.",
                        },
                    ]
                }
            },
        )
        self.assertIn("جهت رسانه‌ها", message)
        self.assertIn("🟢 افزایشی", message)
        self.assertNotIn("بدون پیش‌بینی صریح", message)
        self.assertIn("○", message)
        self.assertIn('href="https://example.com/up"', message)
        self.assertIn("رسانه صعودی", message)
        self.assertNotIn("این رسانه انتظار افزایش قیمت را دارد", message)
        horizon_messages = render_media_outlook_messages(
            report={"current_state": {"media_perspectives": [
                {"source_name": "رسانه صعودی", "source_url": "https://example.com/up", "stance": "up", "horizon": "۴۸ ساعت", "evidence_type": "explicit_opinion", "view": "این رسانه انتظار افزایش قیمت طلا را دارد."},
                {"source_name": "رسانه بدون پیش‌بینی", "source_url": "https://example.com/unknown", "stance": "unknown", "horizon": "نامشخص", "evidence_type": "no_explicit_opinion", "view": "نظر صریحی درباره روند آتی بازار پیدا نشد."},
            ]}},
            watch_name="طلای ۱۸ عیار",
        )
        self.assertEqual(2, len(horizon_messages))
        self.assertEqual("🧭 <b>جهت رسانه‌ها</b>", horizon_messages[0])
        self.assertIn("افق زمانی: تا ۴۸ ساعت", horizon_messages[1])

    def test_media_renderer_emits_every_agreed_horizon_in_order(self):
        labels = ["تا ۲۴ ساعت", "تا ۴۸ ساعت", "۳ تا ۷ روز", "۸ تا ۳۰ روز", "بیش از ۳۰ روز", "بدون افق مشخص"]
        rows = []
        horizons = ["۲۴ ساعت", "۴۸ ساعت", "۳ تا ۷ روز", "۸ تا ۳۰ روز", "بیش از ۳۰ روز", "نامشخص"]
        for index, horizon in enumerate(horizons, start=1):
            rows.append({
                "source_key": f"SRC-{index}",
                "source_name": f"رسانه {index} · طلا",
                "source_url": f"https://example.com/{index}",
                "stance": "up",
                "horizon": horizon,
                "evidence_type": "explicit_opinion",
                "view": "پیش‌بینی افزایش قیمت طلا",
            })
        messages = render_media_outlook_messages(
            report={"current_state": {"media_perspectives": rows}},
            watch_name="طلای ۱۸ عیار",
        )
        self.assertEqual(7, len(messages))
        self.assertEqual("🧭 <b>جهت رسانه‌ها</b>", messages[0])
        self.assertEqual(labels, [
            next(line.split(": ", 1)[1].replace("<b>", "").replace("</b>", "") for line in message.splitlines() if "افق زمانی:" in line)
            for message in messages[1:]
        ])
        self.assertNotIn("· طلا", "\n".join(messages))
        self.assertTrue(all("برآیند: افزایشی" in message for message in messages[1:]))

    def test_media_renderer_calls_split_outlet_views_no_consensus_not_conflict(self):
        messages = render_media_outlook_messages(
            report={"current_state": {"media_perspectives": [
                {"source_key": "UP", "source_name": "رسانه افزایشی", "source_url": "https://example.com/up", "stance": "up", "horizon": "بیش از ۳۰ روز", "evidence_type": "explicit_opinion", "view": "رسانه انتظار افزایش قیمت طلا را دارد."},
                {"source_key": "DOWN", "source_name": "رسانه کاهشی", "source_url": "https://example.com/down", "stance": "down", "horizon": "بیش از ۳۰ روز", "evidence_type": "explicit_opinion", "view": "رسانه انتظار کاهش قیمت طلا را دارد."},
                {"source_key": "FLAT", "source_name": "رسانه خنثی", "source_url": "https://example.com/flat", "stance": "flat", "horizon": "بیش از ۳۰ روز", "evidence_type": "explicit_opinion", "view": "رسانه انتظار ثبات قیمت طلا را دارد."},
            ]}},
            watch_name="طلای ۱۸ عیار",
        )
        card = messages[1]
        self.assertIn("برآیند: بدون اجماع", card)
        self.assertNotIn("↕️ دارای اختلاف", card)

    def test_media_renderer_deduplicates_one_outlet_with_multiple_feed_keys(self):
        message = render_media_outlook_message(
            report={"current_state": {"media_perspectives": [
                {
                    "source_key": "GFA-OUTLET",
                    "source_name": "رسانه نمونه · طلا",
                    "source_url": "https://example.com/gold",
                    "stance": "up",
                    "horizon": "۴۸ ساعت",
                    "evidence_type": "explicit_opinion",
                    "view": "رسانه انتظار افزایش قیمت طلا را دارد.",
                },
                {
                    "source_key": "GFX-OUTLET",
                    "source_name": "رسانه نمونه · Gold Analysis",
                    "source_url": "https://example.com/analysis",
                    "stance": "up",
                    "horizon": "۴۸ ساعت",
                    "evidence_type": "explicit_opinion",
                    "view": "رسانه انتظار افزایش قیمت طلا را دارد.",
                },
            ]}},
            watch_name="طلای ۱۸ عیار",
        )
        self.assertEqual(1, message.count("رسانه نمونه"))
        self.assertNotIn("· طلا", message)
        self.assertNotIn("Gold Analysis", message)

    def test_renderer_is_structured_and_contains_sources_without_advice(self):
        message = render_report_message(
            watch_name="بازار نمونه",
            report={
                "current_state": {
                    "summary": "وضعیت فعلی بازار با شواهد محدود",
                    "facts": ["خبر رسمی نمونه"],
                    "risks": ["داده ناقص"],
                    "media_perspectives": [
                        {
                            "source_key": "MEDIA-001",
                            "source_name": "رسانه نمونه",
                            "source_url": "https://example.com/outlook",
                            "published_at": None,
                            "view": "این رسانه پیش‌بینی می‌کند روند بازار در هفته آینده صعودی باشد.",
                            "stance": "up",
                            "horizon": "هفته آینده",
                            "evidence_type": "explicit_opinion",
                            "confidence": 0.8,
                        }
                    ],
                    "factor_attributions": [
                        {
                            "label": "نرخ بهره و نقدینگی",
                            "direction": "down",
                            "strength": "medium",
                            "attribution_kind": "explicit_driver",
                            "evidence": [{"snippet": "افزایش نرخ بهره"}],
                        }
                    ],
                    "price_forecast": {
                        "status": "available",
                        "forecasts": [
                            {
                                "horizon_days": 7,
                                "point_value": 105.0,
                                "lower_value": 98.0,
                                "upper_value": 112.0,
                                "probability_up": 0.4,
                                "probability_down": 0.35,
                                "probability_flat": 0.25,
                            }
                        ],
                    },
                    "analysis_windows": {
                        "media_analysis_window_hours": 24,
                        "price_comparison_window_hours": 24,
                    },
                    "price_comparison": {
                        "status": "available",
                        "window_hours": 24,
                        "current_value": 105,
                        "change_percent": 2.5,
                    },
                },
                "scenarios": [
                    {"title": "پایه", "probability": 0.5, "horizon": "۷ روز", "expected_change": "تداوم وضعیت"},
                ],
                "changes": [],
                "uncertainties": ["نیازمند داده تازه"],
                "citations": [{"source_name": "منبع رسمی", "source_url": "https://example.com/report"}],
                "confidence": 0.4,
            },
        )
        self.assertIn("گزارش بازار", message)
        self.assertIn("سناریوهای مشروط", message)
        self.assertIn("کیفیت داده", message)
        self.assertIn("چارچوب زمانی گزارش", message)
        self.assertIn("مقایسه قیمت", message)
        self.assertIn("تحلیل اخبار و دیدگاه رسانه‌ها", message)
        self.assertIn("نظر رسانه‌ها درباره روند آتی", message)
        self.assertIn("عوامل اثرگذار", message)
        self.assertIn("پیش‌بینی عددی آماری", message)
        self.assertIn("پیش‌بینی می‌کند", message)
        self.assertIn("منبع رسمی", message)
        self.assertIn("بدون توصیه شخصی", message)
        self.assertLessEqual(len(message), 3900)
        self.assertNotIn("اثر احتمالی بر بازار", message)
        self.assertNotIn("بخر", message)

    def test_destination_validation_supports_private_chat_and_channel(self):
        self.assertEqual("123456789", validate_telegram_destination("123456789"))
        self.assertEqual("-1001234567890", validate_telegram_destination("-1001234567890"))
        with self.assertRaises(ValueError):
            validate_telegram_destination("https://t.me/example")


class BeeCFOConfigurationSyncTest(unittest.TestCase):
    def test_sheet_sync_defaults_to_testing_and_never_requests_activation(self):
        request = ConfigurationSyncRequest(
            timezone="Asia/Tehran",
            schedule_slots=[{"weekday": 0, "time": "16:00"}],
            sources=[],
            watches=[],
        )
        self.assertEqual("testing", request.status)
        self.assertFalse(request.activate_sources)
        self.assertFalse(request.activate_watches)
        self.assertIsNone(request.telegram_destination)

    def test_sheet_sync_accepts_numeric_workspace_destination_without_a_token(self):
        request = ConfigurationSyncRequest(telegram_destination="-1001234567890")
        self.assertEqual("-1001234567890", request.telegram_destination)


if __name__ == "__main__":
    unittest.main()
