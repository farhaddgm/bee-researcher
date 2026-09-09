from __future__ import annotations

import html
import re
from collections.abc import Mapping
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .media_forecasts import build_media_consensus, classify_media_statement, parse_horizon
from .windows import window_label_fa

BEE_CFO_RENDERER_REVISION = "bee-cfo-telegram-16"
BEE_CFO_PRICE_RENDERER_REVISION = "bee-cfo-price-6"
BEE_CFO_MEDIA_MESSAGE_LIMIT = 3900
BEE_CFO_REPORT_MESSAGE_LIMIT = 3900
# Follow-up cards are deliberately shorter than Telegram's hard limit.  They
# are additive to the approved price and media-outlook cards, never a rewrite
# of those cards.
BEE_CFO_FOLLOWUP_MESSAGE_LIMIT = 1200
BEE_CFO_FOLLOWUP_RENDERER_REVISION = "bee-cfo-followups-1"
TELEGRAM_DESTINATION_PATTERN = re.compile(r"^(?:-100\d{6,20}|\d{5,20})$")
_TEHRAN = "Asia/Tehran"


def validate_telegram_destination(value: object) -> str:
    destination = str(value or "").strip()
    if not TELEGRAM_DESTINATION_PATTERN.fullmatch(destination):
        raise ValueError("Telegram destination must be a numeric private chat or channel id")
    return destination


def _localized_digits(value: str) -> str:
    return value.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _text(value: object, *, fallback: str = "—", limit: int = 500) -> str:
    if isinstance(value, Mapping):
        value = (
            value.get("summary")
            or value.get("title")
            or value.get("explanation")
            or value.get("expected_change")
            or value.get("text")
        )
    result = " ".join(str(value or "").split()).strip()
    if not result:
        return fallback
    result = _localized_digits(result)
    return result[:limit].rstrip() + ("…" if len(result) > limit else "")


def _percent(value: object) -> str:
    try:
        number = max(0.0, min(1.0, float(value))) * 100
    except (TypeError, ValueError):
        return "نامشخص"
    return f"{_localized_digits(f'{number:.0f}')}٪"


def _percent_change(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "نامشخص"
    sign = "+" if number > 0 else "-" if number < 0 else ""
    magnitude = abs(number)
    # Telegram Persian output keeps the sign after the number and leaves one
    # visible space before the percent sign, as required by the approved card.
    return f"{_localized_digits(f'{magnitude:.1f}')}{sign} ٪"


def _bullet_items(value: object, *, limit: int = 3, item_limit: int = 220) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:limit]:
        text = _text(item, fallback="", limit=item_limit)
        if text:
            result.append(text)
    return result


def _as_of_label(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "زمان گزارش نامشخص"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        try:
            parsed = parsed.astimezone(ZoneInfo(_TEHRAN))
        except ZoneInfoNotFoundError:
            pass
        return _localized_digits(parsed.strftime("%Y/%m/%d، %H:%M")) + " تهران"
    except ValueError:
        return raw[:40]


def _quality_label(state: Mapping[str, object], valid_count: int) -> str:
    status = str(state.get("quality_status") or "").strip().lower()
    if status == "good" or valid_count > 0:
        return "قابل استفاده"
    return "ضعیف؛ سیگنال جهت‌دار صادر نشد"


def _coverage(state: Mapping[str, object], citations: list[object]) -> tuple[int, int, int]:
    raw = state.get("raw_evidence_count")
    valid = state.get("valid_evidence_count")
    sources = state.get("source_count")
    try:
        raw_count = max(0, int(raw))
    except (TypeError, ValueError):
        raw_count = len(citations)
    try:
        valid_count = max(0, int(valid))
    except (TypeError, ValueError):
        valid_count = min(raw_count, len(_bullet_items(state.get("facts"), limit=3)))
    try:
        source_count = max(0, int(sources))
    except (TypeError, ValueError):
        source_count = len(
            {
                str(item.get("source_key") or item.get("source_name") or "")
                for item in citations
                if isinstance(item, Mapping)
            }
        )
    return valid_count, raw_count, source_count


def _source_lines(citations: list[object], *, limit: int = 3) -> list[str]:
    """Group repeated links so a source is shown once, with clear coverage."""
    grouped: dict[str, dict[str, object]] = {}
    for citation in citations:
        if not isinstance(citation, Mapping):
            continue
        source_key = str(citation.get("source_key") or citation.get("source_name") or "").strip()
        url = str(citation.get("source_url") or "").strip()
        if not source_key:
            continue
        group = grouped.setdefault(
            source_key,
            {
                "name": _text(citation.get("source_name"), fallback="منبع", limit=80),
                "urls": [],
                "origin": "کشف‌شده" if str(citation.get("source_origin") or "").lower() == "discovered" else "ثبت‌شده",
            },
        )
        urls = group["urls"]
        if isinstance(urls, list) and url.startswith(("http://", "https://")) and url not in urls:
            urls.append(url)
    lines: list[str] = []
    for group in list(grouped.values())[:limit]:
        name = str(group["name"])
        urls = group["urls"] if isinstance(group["urls"], list) else []
        label = f"{name} · {_localized_digits(str(len(urls)))} صفحه · {group['origin']}"
        if urls:
            lines.append(f'<a href="{html.escape(str(urls[0]), quote=True)}">{html.escape(label, quote=False)}</a>')
        else:
            lines.append(html.escape(label, quote=False))
    return lines


def _scenario_lines(scenarios: list[object], *, limit: int = 3) -> list[str]:
    preferred = {"base": 0, "upside": 1, "downside": 2}
    icons = {"base": "🟡", "upside": "🟢", "downside": "🔴"}
    ordered = sorted(
        (item for item in scenarios if isinstance(item, Mapping)),
        key=lambda item: preferred.get(str(item.get("key") or ""), 9),
    )[:limit]
    lines: list[str] = []
    for scenario in ordered:
        key = str(scenario.get("key") or "")
        title = html.escape(_text(scenario.get("title"), fallback="سناریو", limit=70), quote=False)
        change = html.escape(_text(scenario.get("expected_change"), limit=125), quote=False)
        probability = _percent(scenario.get("probability"))
        trigger_values = _bullet_items(scenario.get("triggers"), limit=1, item_limit=90)
        trigger = html.escape(trigger_values[0], quote=False) if trigger_values else "محرک معتبر تازه"
        lines.append(f"{icons.get(key, '•')} <b>{title}</b> | {probability}\n{change}\n↳ محرک: {trigger}")
    return lines


def _media_perspective_lines(state: Mapping[str, object], *, limit: int = 2) -> list[str]:
    stance_labels = {"up": "صعودی", "down": "نزولی", "flat": "خنثی", "unknown": "نامشخص"}
    perspectives = state.get("media_perspectives")
    if not isinstance(perspectives, list):
        return []
    lines: list[str] = []
    for item in perspectives[:limit]:
        if not isinstance(item, Mapping):
            continue
        source = html.escape(_text(item.get("source_name"), fallback="رسانه", limit=70), quote=False)
        stance = stance_labels.get(str(item.get("stance") or "unknown").lower(), "نامشخص")
        view = html.escape(_text(item.get("view"), fallback="نظر صریحی درباره روند آتی پیدا نشد.", limit=140), quote=False)
        snippet = _text(item.get("snippet"), fallback="", limit=150)
        excerpt = f"\n  «{html.escape(snippet, quote=False)}»" if snippet else ""
        lines.append(f"🗞 <b>{source}</b> · موضع: {stance}\n{view}{excerpt}")
    return lines


def _media_link(item: Mapping[str, object]) -> str:
    raw_name = _text(item.get("source_name"), fallback="رسانه", limit=90)
    # Source records often carry a topic suffix (for example `· طلا` or
    # `· Gold Analysis`). The channel card is intentionally name-only.
    name = html.escape(raw_name.split("·", 1)[0].strip() or "رسانه", quote=False)
    url = str(item.get("source_url") or "").strip()
    if url.startswith(("http://", "https://")):
        return f'<a href="{html.escape(url, quote=True)}">{name}</a>'
    return name


def _media_identity(item: Mapping[str, object]) -> str:
    """Return the display-level outlet identity used for conflict grouping."""
    name = _text(item.get("source_name"), fallback="رسانه", limit=90)
    return name.split("·", 1)[0].strip().casefold() or str(item.get("source_key") or "")


def _media_names(rows: list[Mapping[str, object]], *, stance: str, limit: int = 4) -> str:
    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if str(row.get("stance") or "") != stance:
            continue
        key = _media_identity(row)
        if key in seen:
            continue
        seen.add(key)
        names.append(_media_link(row))
        if len(names) >= limit:
            break
    return "، ".join(names)


def _normalize_media_render_rows(rows: list[object]) -> list[dict[str, object]]:
    """Normalize legacy and current media-ledger rows for one renderer."""
    normalized_rows: list[dict[str, object]] = []
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        normalized = dict(item)
        if not normalized.get("horizon_key"):
            horizon_days = normalized.get("horizon_days")
            day_key = {1: "24h", 2: "48h", 7: "3_7d", 30: "8_30d", 90: "30d_plus"}.get(horizon_days)
            parsed = parse_horizon(str(normalized.get("horizon") or ""))
            normalized.update(parsed if day_key is None else {
                "horizon_key": day_key,
                "horizon_label": parsed.get("horizon_label") if parsed.get("horizon_key") == day_key else {
                    "24h": "تا ۲۴ ساعت",
                    "48h": "تا ۴۸ ساعت",
                    "3_7d": "۳ تا ۷ روز",
                    "8_30d": "۸ تا ۳۰ روز",
                    "30d_plus": "بیش از ۳۰ روز",
                }.get(day_key, "بدون افق مشخص"),
            })
        # Reports are durable, while the classifier can be improved between
        # collection and delivery. Re-validate a stored directional call at
        # render time so an unrelated direction word (for example, lower
        # yields) cannot become a public bearish call for the watched asset.
        if normalized.get("evidence_type") == "explicit_opinion":
            stance = classify_media_statement(str(normalized.get("view") or normalized.get("snippet") or ""))
            if stance not in {"up", "down", "flat"}:
                normalized["stance"] = "unknown"
                normalized["evidence_type"] = "no_explicit_opinion"
            else:
                normalized["stance"] = stance
        normalized_rows.append(normalized)
    return normalized_rows


def _media_statement_bullet(row: Mapping[str, object]) -> str:
    """Render one linked article-level opinion as a readable bullet."""
    view = html.escape(
        _text(
            row.get("view") or row.get("snippet"),
            fallback="نظر صریحی درباره روند آتی بازار ثبت نشد.",
            limit=175,
        ),
        quote=False,
    )
    flags: list[str] = []
    if row.get("conflict_status") == "internal_conflict":
        flags.append("⚠️ تعارض داخلی")
    if row.get("status") == "syndicated":
        flags.append("روایت هم‌منتشرشده")
    suffix = f" · {' · '.join(flags)}" if flags else ""
    return f"• {_media_link(row)} — «{view}»{suffix}"


def _media_category_block(label: str, rows: list[Mapping[str, object]]) -> str | None:
    if not rows:
        return None
    lines = [f"<b>{label}</b>"]
    seen: set[str] = set()
    for row in rows:
        # One outlet appears once per category. Article links remain attached
        # to the outlet name; contradictory articles are handled separately.
        # Different feeds can represent the same outlet with different source
        # keys. The channel contract names an outlet once per category, so the
        # display-level identity—not the feed key—is the deduplication key.
        key = _media_identity(row)
        if key in seen:
            continue
        seen.add(key)
        # The channel template uses a hollow bullet and only the outlet name
        # is linked to its supporting article.
        lines.append(f"○ {_media_link(row)}")
    return "\n".join(lines) if len(lines) > 1 else None


def render_media_outlook_messages(*, report: Mapping[str, object], watch_name: str) -> list[str]:
    """Render the channel title followed by one compact card per horizon."""
    state = report.get("current_state") if isinstance(report.get("current_state"), Mapping) else {}
    perspectives = state.get("media_perspectives")
    rows = perspectives if isinstance(perspectives, list) else []
    render_rows = _normalize_media_render_rows(rows)
    explicit_rows = [item for item in render_rows if item.get("evidence_type") == "explicit_opinion"]
    # Rebuild the aggregation from re-validated rows. Persisted consensus may
    # have been calculated by an older classifier revision.
    consensus = build_media_consensus(render_rows) if explicit_rows else {}
    buckets = consensus.get("buckets") if isinstance(consensus.get("buckets"), list) else []
    bucket_by_horizon = {
        str(bucket.get("horizon_key")): bucket
        for bucket in buckets
        if isinstance(bucket, Mapping)
    }
    horizon_order = ("24h", "48h", "3_7d", "8_30d", "30d_plus", "unspecified")
    horizon_labels = {
        "24h": "تا ۲۴ ساعت",
        "48h": "تا ۴۸ ساعت",
        "3_7d": "۳ تا ۷ روز",
        "8_30d": "۸ تا ۳۰ روز",
        "30d_plus": "بیش از ۳۰ روز",
        "unspecified": "بدون افق مشخص",
    }
    direction_meta = {
        "up": "🟢 افزایشی",
        "down": "🔴 کاهشی",
        "flat": "⚪ بدون تغییر",
    }
    # The title is intentionally its own message.  It makes the sequence
    # price → media direction → horizon cards scannable in the channel.
    result: list[str] = ["🧭 <b>جهت رسانه‌ها</b>"]
    # A headline without an explicit outlook is not a directional forecast and
    # therefore must not be placed in any of the approved direction buckets.
    for horizon_key in horizon_order:
        bucket = bucket_by_horizon.get(horizon_key)
        horizon_rows = [
            row for row in explicit_rows
            if row.get("horizon_key") == horizon_key and row.get("status") != "expired"
        ]
        if not horizon_rows:
            continue
        horizon_label = html.escape(
            _text(
                (bucket or {}).get("horizon_label") if isinstance(bucket, Mapping) else None,
                fallback=horizon_labels[horizon_key],
                limit=40,
            ),
            quote=False,
        )
        direction = str(bucket.get("direction") or "no_call") if isinstance(bucket, Mapping) else "no_call"
        direction_label = {
            # Different outlets having different calls is a lack of consensus,
            # not an internal contradiction.  "دارای اختلاف" is reserved for
            # an outlet that published incompatible calls in the same horizon.
            "mixed": "بدون اجماع",
            "no_call": "داده ناکافی",
            "up": "افزایشی",
            "down": "کاهشی",
            "flat": "بدون تغییر",
        }.get(direction, "داده ناکافی")
        independent = bucket.get("independent_source_count", 0) if isinstance(bucket, Mapping) else 0
        lines = [
            f"<b>⏱ افق زمانی: {horizon_label}</b>",
            f"{_localized_digits(str(independent))} منبع مستقل و {_localized_digits(str(len(horizon_rows)))} دیدگاه صریح.",
        ]
        conflict_rows = [row for row in horizon_rows if row.get("conflict_status") == "internal_conflict"]
        media_stances: dict[str, set[str]] = {}
        for row in horizon_rows:
            stance = str(row.get("stance") or "")
            if stance in {"up", "down", "flat"}:
                media_stances.setdefault(_media_identity(row), set()).add(stance)
        conflicting_media = {key for key, stances in media_stances.items() if len(stances) > 1}
        conflict_rows.extend(
            row for row in horizon_rows
            if _media_identity(row) in conflicting_media
            and row not in conflict_rows
        )
        directional_rows = [
            row for row in horizon_rows
            if row.get("conflict_status") != "internal_conflict"
            and _media_identity(row) not in conflicting_media
        ]
        if conflicting_media:
            direction = "mixed"
            direction_label = "دارای اختلاف"
        for stance, label in direction_meta.items():
            block = _media_category_block(label, [row for row in directional_rows if str(row.get("stance") or "") == stance])
            if block:
                lines.append(block)
        conflict_block = _media_category_block("↕️ دارای اختلاف", conflict_rows)
        if conflict_block:
            lines.append(conflict_block)
        lines.append(f"<b>برآیند: {direction_label}</b>")
        result.append("\n\n".join(lines))

    if len(result) == 1:
        result.append("در این نوبت مقاله قابل‌استناد با نظر رسانه‌ای استخراج نشد.")
    return result


def render_media_outlook_message(*, report: Mapping[str, object], watch_name: str) -> str:
    """Backward-compatible joined preview; delivery uses one message per horizon."""
    return "\n\n".join(render_media_outlook_messages(report=report, watch_name=watch_name))


def _card_message(title: str, blocks: list[str], *, limit: int = BEE_CFO_FOLLOWUP_MESSAGE_LIMIT) -> str | None:
    """Return a complete bounded card, dropping whole low-priority blocks only."""
    retained: list[str] = []
    for block in blocks:
        candidate = "\n\n".join([title, *retained, block])
        if len(candidate) > limit:
            break
        retained.append(block)
    return "\n\n".join([title, *retained]) if retained else None


def _factor_direction_label(value: object) -> tuple[str, str]:
    labels = {
        "up": ("🟢", "افزایشی"),
        "down": ("🔴", "کاهشی"),
        "flat": ("⚪", "خنثی"),
        "unknown": ("⚪", "نامشخص"),
    }
    return labels.get(str(value or "unknown"), labels["unknown"])


def _factor_card(state: Mapping[str, object]) -> str | None:
    factors = state.get("factor_attributions") or state.get("factor_summary")
    if not isinstance(factors, list):
        return None
    strength_labels = {"strong": "قوی", "medium": "متوسط", "weak": "ضعیف", "unknown": "نامشخص"}
    blocks: list[str] = []
    for item in factors:
        if not isinstance(item, Mapping):
            continue
        # A factor with no evidenced direction is an internal diagnostic, not
        # a useful public explanation of the current move.
        if str(item.get("direction") or "") not in {"up", "down", "flat"}:
            continue
        evidence_rows = item.get("evidence")
        evidence = evidence_rows[0] if isinstance(evidence_rows, list) and evidence_rows and isinstance(evidence_rows[0], Mapping) else None
        # Factors without a visible source are useful internally but are not
        # safe to place in a public card.
        if evidence is None:
            continue
        icon, direction = _factor_direction_label(item.get("direction"))
        strength = strength_labels.get(str(item.get("strength") or "unknown"), "نامشخص")
        label = html.escape(_text(item.get("label"), fallback="عامل بازار", limit=66), quote=False)
        kind = "عامل صریح" if item.get("attribution_kind") == "explicit_driver" else "شاهد هم‌زمان"
        published_at = _price_datetime(evidence.get("published_at")) if evidence.get("published_at") else None
        source_line = f"○ {kind}: {_media_link(evidence)}"
        if published_at and published_at != "نامشخص":
            source_line += f" · {published_at}"
        lines = [f"{icon} <b>{label}</b> · {direction} · قدرت {strength}", source_line]
        snippet = _text(evidence.get("snippet"), fallback="", limit=150)
        if snippet:
            lines.append(f"○ شاهد: {html.escape(snippet, quote=False)}")
        invalidation = _text(item.get("invalidation"), fallback="", limit=120)
        if invalidation:
            lines.append(f"○ شرط نقض: {html.escape(invalidation, quote=False)}")
        blocks.append("\n".join(lines))
        if len(blocks) >= 3:
            break
    return _card_message("🧩 <b>عوامل اثرگذار</b>", blocks)


def _forecast_unit(state: Mapping[str, object]) -> str:
    live_price = state.get("live_price") if isinstance(state.get("live_price"), Mapping) else {}
    return html.escape(_text(live_price.get("quote_unit"), fallback="واحد شاخص", limit=24), quote=False)


def _model_forecast_card(state: Mapping[str, object]) -> str | None:
    bundle = state.get("price_forecast")
    if not isinstance(bundle, Mapping) or bundle.get("status") != "available":
        # A no-call is intentionally represented in the quality card rather
        # than creating an empty-looking forecast card.
        return None
    publication = bundle.get("publication")
    if isinstance(publication, Mapping) and not publication.get("public_target_permitted", False):
        return None
    forecasts = bundle.get("forecasts")
    if not isinstance(forecasts, list):
        return None
    unit = _forecast_unit(state)
    blocks: list[str] = []
    for item in forecasts:
        if not isinstance(item, Mapping):
            continue
        try:
            horizon = int(item.get("horizon_days"))
            point = float(item.get("point_value"))
            lower = float(item.get("lower_value"))
            upper = float(item.get("upper_value"))
        except (TypeError, ValueError):
            continue
        probabilities = (
            f"🟢 {_percent(item.get('probability_up'))} · "
            f"🔴 {_percent(item.get('probability_down'))} · "
            f"⚪ {_percent(item.get('probability_flat'))}"
        )
        blocks.append(
            f"<b>افق {_localized_digits(str(horizon))} روز</b>\n"
            f"○ میانه: {_price_number(point)} {unit}\n"
            f"○ بازه: {_price_number(lower)} تا {_price_number(upper)} {unit}\n"
            f"○ احتمال جهت: {probabilities}"
        )
        if len(blocks) >= 3:
            break
    agreement = state.get("model_agreement") if isinstance(state.get("model_agreement"), Mapping) else {}
    if agreement and agreement.get("status") != "no_call":
        label = html.escape(_text(agreement.get("label"), fallback="نامشخص", limit=80), quote=False)
        blocks.append(f"🧮 توافق مدل‌ها: {label}")
    return _card_message("🔭 <b>برآورد مدل</b>", blocks)


def _scenario_card(report: Mapping[str, object]) -> str | None:
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        return None
    icons = {"base": "🟡", "upside": "🟢", "downside": "🔴"}
    blocks: list[str] = []
    for item in scenarios:
        if not isinstance(item, Mapping):
            continue
        triggers = _bullet_items(item.get("triggers"), limit=1, item_limit=100)
        invalidation = _text(item.get("invalidation"), fallback="", limit=100)
        evidence_rows = item.get("evidence")
        evidence = next(
            (
                candidate for candidate in evidence_rows
                if isinstance(candidate, Mapping) and str(candidate.get("source_url") or "").startswith(("http://", "https://"))
            ),
            None,
        ) if isinstance(evidence_rows, list) else None
        # Scenarios without observable trigger and invalidation stay in the
        # ledger but do not become a public channel assertion.  A fallback
        # scenario also needs a visible source; otherwise it is only a useful
        # internal planning object.
        if not triggers or not invalidation or evidence is None:
            continue
        key = str(item.get("key") or "")
        title = html.escape(_text(item.get("title"), fallback="سناریو", limit=55), quote=False)
        expected = html.escape(_text(item.get("expected_change"), fallback="تغییر مورد انتظار نامشخص", limit=100), quote=False)
        blocks.append(
            f"{icons.get(key, '⚪')} <b>{title}</b> · {_percent(item.get('probability'))}\n"
            f"○ {expected}\n"
            f"○ محرک: {html.escape(triggers[0], quote=False)}\n"
            f"○ شرط نقض: {html.escape(invalidation, quote=False)}\n"
            f"○ شاهد: {_media_link(evidence)}"
        )
        if len(blocks) >= 3:
            break
    return _card_message("🎯 <b>سناریوهای مشروط</b>", blocks)


def _quality_card(state: Mapping[str, object]) -> str | None:
    coverage = state.get("coverage_score") if isinstance(state.get("coverage_score"), Mapping) else {}
    budget = state.get("confidence_budget") if isinstance(state.get("confidence_budget"), Mapping) else {}
    live_price = state.get("live_price") if isinstance(state.get("live_price"), Mapping) else {}
    if not coverage and not budget:
        return None
    status_labels = {"complete": "کامل", "partial": "ناقص", "insufficient": "ناکافی"}
    missing_labels = {
        "quote": "قیمت مرجع", "benchmark": "مرجع مقایسه‌ای", "forecast": "پیش‌بینی عددی",
        "coverage": "پوشش داده", "source_health": "سلامت منبع", "forecast_quality": "کیفیت مدل",
        "model_agreement": "توافق مدل‌ها",
    }
    blocks: list[str] = []
    if coverage:
        status = status_labels.get(str(coverage.get("status") or ""), "نامشخص")
        blocks.append(f"○ پوشش گزارش: {_percent(coverage.get('score'))} · {status}")
    if budget:
        label = html.escape(_text(budget.get("label"), fallback="نامشخص", limit=50), quote=False)
        blocks.append(f"○ اطمینان داده/مدل: {_percent(budget.get('overall'))} · {label}")
    missing: list[str] = []
    for value in (coverage.get("missing") if coverage else [], budget.get("missing") if budget else []):
        if not isinstance(value, list):
            continue
        for item in value:
            key = str(item or "")
            # A live quote was fetched for this delivery; the historical
            # report coverage may pre-date it and must not falsely call it
            # missing in the channel.
            if key == "quote" and live_price.get("value") is not None:
                continue
            label = missing_labels.get(key, key)
            if label and label not in missing:
                missing.append(label)
    coverage_gaps = state.get("coverage_gaps")
    if isinstance(coverage_gaps, list):
        for gap in coverage_gaps:
            if not isinstance(gap, Mapping):
                continue
            label = _text(gap.get("label"), fallback="", limit=45)
            if label and label not in missing:
                missing.append(label)
    if missing:
        blocks.append("○ نیازمند تکمیل: " + "، ".join(html.escape(item, quote=False) for item in missing[:4]))
    source_health = live_price.get("price_source_health") if isinstance(live_price.get("price_source_health"), Mapping) else state.get("price_source_health")
    if isinstance(source_health, Mapping):
        selected = _text(source_health.get("selected_source"), fallback="", limit=45)
        errors = source_health.get("errors")
        if selected:
            blocks.append(f"○ منبع قیمت این نوبت: {html.escape(selected, quote=False)}")
        elif isinstance(errors, list) and errors:
            blocks.append("○ سلامت منبع قیمت: نیازمند بررسی")
    return _card_message("🧪 <b>کیفیت و محدودیت</b>", blocks)


def _event_matches_watch(*, title: object, url: object, watch_name: str) -> bool:
    """Keep public follow-up events scoped to the selected market."""
    watch = str(watch_name or "").casefold()
    if any(marker in watch for marker in ("طلا", "gold", "xau")):
        markers = ("طلا", "gold", "xau", "اونس", "bullion", "سکه", "18k", "۱۸ عیار")
    elif any(marker in watch for marker in ("دلار", "usd", "dollar")):
        markers = ("دلار", "usd", "dollar", "ارز")
    elif any(marker in watch for marker in ("بیت", "bitcoin", "btc")):
        markers = ("بیت", "bitcoin", "btc", "رمزارز", "crypto")
    else:
        # Future catalog items remain compatible until they declare a marker
        # contract of their own.
        return True
    candidate = f"{title or ''} {url or ''}".casefold()
    return any(marker in candidate for marker in markers)


def _monitor_card(state: Mapping[str, object], *, watch_name: str) -> str | None:
    blocks: list[str] = []
    source_rows: list[Mapping[str, object]] = []
    for key in ("media_perspectives", "evidence_cards"):
        values = state.get(key)
        if isinstance(values, list):
            source_rows.extend(item for item in values if isinstance(item, Mapping))
    events = state.get("events")
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, Mapping):
                continue
            title = html.escape(_text(event.get("title"), fallback="رویداد بازار", limit=115), quote=False)
            urls = event.get("source_urls")
            url = str(urls[0] or "") if isinstance(urls, list) and urls else ""
            if not _event_matches_watch(title=event.get("title"), url=url, watch_name=watch_name):
                continue
            published_at = _price_datetime(event.get("published_at")) if event.get("published_at") else None
            source_item = next((item for item in source_rows if str(item.get("source_url") or "") == url), None)
            source = _media_link(source_item) if source_item is not None else (
                f'<a href="{html.escape(url, quote=True)}">منبع خبر</a>'
                if url.startswith(("http://", "https://")) else "منبع خبر"
            )
            line = f"🗓 <b>{title}</b>\n○ {source}"
            if published_at and published_at != "نامشخص":
                line += f" · {published_at}"
            blocks.append(line)
            if len(blocks) >= 2:
                break
    open_checks = state.get("open_checks")
    live_price = state.get("live_price") if isinstance(state.get("live_price"), Mapping) else {}
    if isinstance(open_checks, list):
        for item in open_checks:
            if not isinstance(item, Mapping) or str(item.get("status") or "open") != "open":
                continue
            if str(item.get("key") or "") == "quote" and live_price.get("value") is not None:
                continue
            label = html.escape(_text(item.get("label"), fallback="مورد پیگیری", limit=70), quote=False)
            action = html.escape(_text(item.get("next_action"), fallback="بازبینی در اجرای بعدی", limit=110), quote=False)
            blocks.append(f"📌 <b>{label}</b>\n○ اقدام بعدی: {action}")
            if len(blocks) >= 4:
                break
    media_history = state.get("media_history")
    if isinstance(media_history, list):
        for item in media_history:
            if not isinstance(item, Mapping) or not item.get("transition"):
                continue
            entries = item.get("items")
            latest = entries[-1] if isinstance(entries, list) and entries and isinstance(entries[-1], Mapping) else item
            blocks.append(
                f"🔄 {_media_link(latest)}\n"
                f"○ تغییر روایت: {html.escape(_text(item.get('transition'), limit=45), quote=False)}"
            )
            if len(blocks) >= 5:
                break
    return _card_message("🗓 <b>پیگیری بعدی</b>", blocks)


def render_followup_messages(*, report: Mapping[str, object], watch_name: str) -> list[str]:
    """Render additive cards after the immutable price and media cards.

    ``watch_name`` is deliberately retained in the public signature for the
    delivery boundary.  The current channel layout omits it from the cards
    because the price card already identifies the selected indicator.
    """
    state = report.get("current_state") if isinstance(report.get("current_state"), Mapping) else {}
    cards = [
        _factor_card(state),
        _model_forecast_card(state),
        _scenario_card(report),
        _quality_card(state),
        _monitor_card(state, watch_name=watch_name),
    ]
    return [card for card in cards if card]


def _factor_lines(state: Mapping[str, object], *, limit: int = 3) -> list[str]:
    direction_labels = {"up": "صعودی", "down": "نزولی", "flat": "خنثی", "unknown": "نامشخص"}
    strength_labels = {"strong": "قوی", "medium": "متوسط", "weak": "ضعیف", "unknown": "نامشخص"}
    values = state.get("factor_attributions") or state.get("factor_summary")
    if not isinstance(values, list):
        return []
    lines: list[str] = []
    for item in values[:limit]:
        if not isinstance(item, Mapping):
            continue
        label = html.escape(_text(item.get("label"), fallback="عامل بازار", limit=75), quote=False)
        direction = direction_labels.get(str(item.get("direction") or "unknown"), "نامشخص")
        strength = strength_labels.get(str(item.get("strength") or "unknown"), "نامشخص")
        kind = "نظر رسانه‌ای" if item.get("attribution_kind") == "media_statement" else "شاهد/هم‌حرکتی"
        evidence = item.get("evidence")
        snippet = ""
        if isinstance(evidence, list) and evidence and isinstance(evidence[0], Mapping):
            snippet = _text(evidence[0].get("snippet"), fallback="", limit=55)
        line = f"• <b>{label}</b> · {direction} · قدرت {strength} · {kind}"
        if snippet:
            line += f"\n  {html.escape(snippet, quote=False)}"
        lines.append(line)
    return lines


def _numeric_forecast_lines(state: Mapping[str, object], *, limit: int = 3) -> list[str]:
    bundle = state.get("price_forecast")
    if not isinstance(bundle, Mapping):
        return []
    if bundle.get("status") == "no_call":
        reason = html.escape(_text(bundle.get("reason"), fallback="تاریخچه معتبر کافی نیست", limit=110), quote=False)
        return [f"• پیش‌بینی عددی صادر نشد: {reason}"]
    rows = bundle.get("forecasts")
    if not isinstance(rows, list):
        return []
    lines: list[str] = []
    for item in rows[:limit]:
        if not isinstance(item, Mapping):
            continue
        try:
            horizon = int(item.get("horizon_days"))
            point = float(item.get("point_value"))
            lower = float(item.get("lower_value"))
            upper = float(item.get("upper_value"))
        except (TypeError, ValueError):
            continue
        probs = f"↑ {_percent(item.get('probability_up'))} · ↓ {_percent(item.get('probability_down'))} · ـ {_percent(item.get('probability_flat'))}"
        def number(value: float) -> str:
            return _localized_digits(f"{value:,.2f}")
        lines.append(f"• افق {_localized_digits(str(horizon))} روز · میانه {number(point)} · بازه {number(lower)} تا {number(upper)}\n  احتمال: {probs}")
    return lines


def render_report_message(
    *,
    report: Mapping[str, object],
    watch_name: str,
    include_sources: bool = True,
) -> str:
    """Render the compact, evidence-first Bee CFO Telegram market brief."""
    state = report.get("current_state") if isinstance(report.get("current_state"), Mapping) else {}
    scenarios = report.get("scenarios") if isinstance(report.get("scenarios"), list) else []
    citations = report.get("citations") if isinstance(report.get("citations"), list) else []
    valid_count, raw_count, source_count = _coverage(state, citations)
    quality = _quality_label(state, valid_count)
    quality_icon = "✅" if valid_count > 0 else "⚠️"
    if valid_count == 0:
        summary = "داده‌ی معتبر برای قیمت یا درصد تغییر در دسترس نیست؛ سیگنال جهت‌دار صادر نمی‌شود."
    else:
        summary = _text(state.get("summary"), limit=180)

    parts = [
        "🐝 <b>BEE CFO</b> · گزارش بازار",
        f"<b>{html.escape(_text(watch_name, limit=100), quote=False)}</b>\n"
        f"⏱ {_as_of_label(report.get('as_of'))} · افق گزارش: ۷ روز\n"
        f"{quality_icon} کیفیت داده: <b>{html.escape(quality, quote=False)}</b> · "
        f"پوشش: {_localized_digits(str(valid_count))}/{_localized_digits(str(raw_count))} شاهد معتبر · "
        f"{_localized_digits(str(source_count))} منبع",
        f"<b>📐 چارچوب زمانی گزارش</b>\n"
        f"• مقایسه قیمت: {_localized_digits(window_label_fa((state.get('price_comparison') or {}).get('window_hours', 24)))}\n"
        f"• تحلیل اخبار و دیدگاه رسانه‌ها: {_localized_digits(window_label_fa((state.get('analysis_windows') or {}).get('media_analysis_window_hours', 24)))}",
        f"<b>۱) 🧭 جمع‌بندی سریع</b>\n{html.escape(summary, quote=False)}",
    ]

    comparison = state.get("price_comparison") if isinstance(state.get("price_comparison"), Mapping) else {}
    live_price = state.get("live_price") if isinstance(state.get("live_price"), Mapping) else {}
    if comparison or live_price:
        value = live_price.get("value", comparison.get("current_value"))
        price_line = f"• قیمت ثبت‌شده: {_localized_digits(str(value))}" if value is not None else "• قیمت ثبت‌شده: نامشخص"
        if comparison.get("status") == "available":
            price_line += f"\n• تغییر نسبت به {_localized_digits(window_label_fa(comparison.get('window_hours', 24)))} قبل: {_percent_change(comparison.get('change_percent'))}"
        else:
            price_line += "\n• تغییر نسبت به بازه‌ی مبنا: محاسبه نشد؛ سابقه‌ی معتبر کافی در دسترس نیست"
        parts.insert(4, "<b>۲) 📍 وضعیت قیمت</b>\n" + price_line)

    facts = _bullet_items(state.get("facts"), limit=3, item_limit=180)
    if facts:
        parts.append("<b>۳) 📌 داده‌های کلیدی</b>\n" + "\n".join(f"• {html.escape(item, quote=False)}" for item in facts))

    factor_lines = _factor_lines(state)
    if factor_lines:
        parts.append("<b>۴) 🧩 عوامل اثرگذار بر وضعیت فعلی</b>\n" + "\n".join(factor_lines))

    forecast_lines = _numeric_forecast_lines(state)
    if forecast_lines:
        parts.append("<b>۵) 🔭 پیش‌بینی عددی آماری</b>\n" + "\n".join(forecast_lines))

    media_lines = _media_perspective_lines(state, limit=3)
    if media_lines:
        parts.append("<b>۶) 🗣 نظر رسانه‌ها درباره روند آتی</b>\n" + "\n\n".join(media_lines))

    coverage = state.get("coverage_score") if isinstance(state.get("coverage_score"), Mapping) else {}
    if coverage:
        coverage_status = {"complete": "کامل", "partial": "ناقص", "insufficient": "ناکافی"}.get(str(coverage.get("status")), "نامشخص")
        parts.append(f"<b>🧪 امتیاز پوشش داده</b> · {_percent(coverage.get('score'))} · {coverage_status}")

    agreement = state.get("model_agreement") if isinstance(state.get("model_agreement"), Mapping) else {}
    if agreement and agreement.get("status") != "no_call":
        parts.append(f"<b>🧮 توافق مدل‌ها</b> · {html.escape(_text(agreement.get('label'), limit=80), quote=False)}")

    events = state.get("events") if isinstance(state.get("events"), list) else []
    event_lines = []
    for event in events[:5]:
        if isinstance(event, Mapping):
            event_lines.append(f"• {_text(event.get('title'), limit=120)}")
    if event_lines:
        parts.append("<b>🗓 رویدادهای رصدشده</b>\n" + "\n".join(event_lines))

    trends = _bullet_items(state.get("trends"), limit=3, item_limit=180)
    if valid_count > 0 and trends:
        parts.append("<b>📈 برداشت تحلیلی</b>\n• " + html.escape(trends[0], quote=False))
        if len(trends) > 1:
            parts[-1] += "\n" + "\n".join(f"• {html.escape(item, quote=False)}" for item in trends[1:])

    scenario_lines = _scenario_lines(scenarios)
    if scenario_lines:
        parts.append("<b>۷) 🎯 سناریوهای مشروط | افق ۷ روز</b>\n" + "\n\n".join(scenario_lines))

    changes: list[str] = []
    for change in report.get("changes", []) if isinstance(report.get("changes"), list) else []:
        if isinstance(change, Mapping):
            explanation = _text(change.get("explanation"), fallback="", limit=150)
            if explanation:
                changes.append(explanation)
        if len(changes) >= 5:
            break
    if changes:
        parts.append("<b>🔄 تغییرات مهم</b>\n" + "\n".join(f"• {html.escape(item, quote=False)}" for item in changes))

    risks = _bullet_items(state.get("risks"), limit=3, item_limit=180)
    uncertainties = _bullet_items(report.get("uncertainties"), limit=3, item_limit=180)
    risk_lines = (risks + uncertainties)[:4]
    if risk_lines:
        parts.append("<b>⚠️ محدودیت و عدم‌قطعیت</b>\n" + "\n".join(f"• {html.escape(item, quote=False)}" for item in risk_lines))

    if include_sources:
        source_lines = _source_lines(citations, limit=6)
        if source_lines:
            parts.append("<b>🔗 منابع مورد استناد</b>\n" + "\n".join(f"• {line}" for line in source_lines))

    confidence = _percent(report.get("confidence"))
    parts.append(f"<i>اطمینان مدل: {confidence} · تحلیل عمومی بازار؛ بدون توصیه شخصی.</i>")
    return "\n\n".join(parts)


def render_report_diff_message(*, diff: Mapping[str, object], watch_name: str = "گزارش بازار") -> str:
    """Render an on-demand explanation of what changed, without rerunning forecast."""

    labels = {
        "confidence_budget": "بودجه اطمینان",
        "coverage_score": "پوشش داده",
        "price_forecast": "پیش‌بینی عددی",
        "media_pulse": "نبض رسانه‌ای",
        "media_consensus": "اجماع رسانه‌ای",
        "media_conflicts": "تعارض رسانه‌ای",
        "factor_summary": "عوامل اثرگذار",
        "events": "رویدادها",
        "open_checks": "موارد باز",
    }
    parts = [
        "🔎 <b>چرا گزارش تغییر کرد؟</b>",
        f"<b>{html.escape(_text(watch_name, limit=90), quote=False)}</b> · مقایسه شواهد و وضعیت ذخیره‌شده",
    ]
    changed = diff.get("changed_fields") if isinstance(diff.get("changed_fields"), list) else []
    if changed:
        lines = []
        for item in changed[:5]:
            if not isinstance(item, Mapping):
                continue
            field = labels.get(str(item.get("field")), str(item.get("field") or "تغییر عمومی"))
            lines.append(f"• <b>{html.escape(field, quote=False)}</b>: مقدار قبلی و فعلی متفاوت است")
        if lines:
            parts.append("<b>تغییرهای قابل ردیابی</b>\n" + "\n".join(lines))
    else:
        parts.append("تغییر معناداری در مؤلفه‌های ثبت‌شده دیده نشد.")
    new_ids = diff.get("new_evidence_ids") if isinstance(diff.get("new_evidence_ids"), list) else []
    evidence = diff.get("new_evidence") if isinstance(diff.get("new_evidence"), list) else []
    evidence_lines: list[str] = []
    for item in evidence[:3]:
        if not isinstance(item, Mapping):
            continue
        name = html.escape(_text(item.get("source_name"), fallback="شاهد", limit=70), quote=False)
        url = str(item.get("source_url") or "")
        evidence_lines.append(
            f'<a href="{html.escape(url, quote=True)}">{name}</a>' if url.startswith(("http://", "https://")) else name
        )
    if evidence_lines:
        parts.append("<b>شواهد تازه</b>\n" + "، ".join(evidence_lines))
    elif new_ids:
        parts.append(f"شواهد تازه: {_localized_digits(str(len(new_ids)))} مورد؛ جزئیات در API evidence ledger")
    parts.append("<i>این پاسخ از گزارش‌های ذخیره‌شده ساخته شده و forecast جدید یا توصیه شخصی تولید نمی‌کند.</i>")
    result = "\n\n".join(parts)
    return result if len(result) <= 1200 else "\n\n".join(parts[:3] + parts[-1:])


def render_why_changed_message(
    *,
    diff: Mapping[str, object],
    report: Mapping[str, object],
    watch_name: str = "گزارش بازار",
) -> str:
    """Render the typed Bee CFO reply from saved evidence only.

    This intentionally reuses the bounded diff renderer and only appends links
    already attached to the stored report.  It is suitable for a private bot
    reply and never calls a model or reads fresh market data.
    """
    base = render_report_diff_message(diff=diff, watch_name=watch_name)
    citations = report.get("citations") if isinstance(report.get("citations"), list) else []
    lines = _source_lines(citations, limit=3)
    if not lines:
        return base
    message = base.replace(
        "<i>این پاسخ از گزارش‌های ذخیره‌شده ساخته شده و forecast جدید یا توصیه شخصی تولید نمی‌کند.</i>",
        "<b>منابع همان گزارش</b>\n" + "\n".join(f"• {line}" for line in lines)
        + "\n\n<i>این پاسخ از گزارش‌های ذخیره‌شده ساخته شده و forecast جدید یا توصیه شخصی تولید نمی‌کند.</i>",
    )
    return message if len(message) <= 1200 else base


def _price_title(indicator_key: object, indicator_name: object) -> tuple[str, str]:
    key = str(indicator_key or "").upper()
    if key == "GOLD_18K":
        return "قیمت طلای ۱۸ عیار", "هر گرم طلای ۱۸ عیار"
    if key == "USD_FREE":
        return "قیمت دلار", "دلار آمریکا در بازار آزاد"
    if key == "BTC_USDT":
        return "قیمت بیت‌کوین", "بیت‌کوین"
    return f"قیمت {_text(indicator_name, fallback='شاخص بازار', limit=90)}", _text(indicator_name, fallback="شاخص بازار", limit=120)


def _price_number(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "نامشخص"
    if number.is_integer():
        raw = f"{number:,.0f}"
    else:
        raw = f"{number:,.8f}".rstrip("0").rstrip(".")
    return _localized_digits(raw).replace(",", "،").replace(".", "٫")


def _price_change(value: object, *, unit: str) -> str | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    sign = "+" if number > 0 else "-" if number < 0 else ""
    return f"{_price_number(abs(number))}{sign} {html.escape(unit, quote=False)}"


def _price_datetime(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "نامشخص"
    try:
        from app.telegram_delivery import _jalali_date

        label = _jalali_date(raw)
        return label.split(" ", 1)[1] if " " in label else label
    except (TypeError, ValueError, IndexError):
        return raw[:40]


def render_price_message(*, snapshot: Mapping[str, object]) -> str:
    """Render the required standalone price card sent before Bee CFO news."""
    title, quote_label = _price_title(snapshot.get("indicator_key"), snapshot.get("indicator_name"))
    currency = str(snapshot.get("currency") or "").upper()
    unit = str(snapshot.get("quote_unit") or ("تومان" if currency == "IRR" else "دلار"))
    current = _price_number(snapshot.get("value"))
    comparison = snapshot.get("comparison") if isinstance(snapshot.get("comparison"), Mapping) else {}
    comparison_line = None
    comparison_hours = comparison.get("window_hours", 24)
    if comparison.get("status") == "available":
        comparison_line = (
            f"مقایسه با {_localized_digits(window_label_fa(comparison_hours))} قبل: "
            f"{_price_change(comparison.get('change_value'), unit=unit) or 'نامشخص'}"
        )
        if comparison.get("change_percent") is not None:
            comparison_line += f" ({_percent_change(comparison.get('change_percent'))})"
    else:
        comparison_line = (
            f"مقایسه با {_localized_digits(window_label_fa(comparison_hours))} قبل: "
            "محاسبه نشد؛ سابقه‌ی معتبر کافی در دسترس نیست"
        )
    source_name_raw = _text(snapshot.get("source_name"), fallback="مرجع", limit=100)
    source_url = str(snapshot.get("source_url") or "").strip()
    if "tgju" in source_name_raw.lower() or "tgju" in source_url.lower():
        source_name_raw = "TGJU"
        source_url = "https://www.tgju.org/"
    else:
        source_name_raw = re.sub(r"\s+API$", "", source_name_raw, flags=re.IGNORECASE).strip() or "مرجع"
    source_name = html.escape(source_name_raw, quote=False)
    # Only the media outlet names are hyperlinks in the channel template.
    # The price-source attribution remains visible but intentionally plain.
    source_line = f"🔗 مرجع: {source_name}"
    parts = [
        f"💰 <b>{html.escape(title, quote=False)}</b>",
        f"<b>{html.escape(quote_label, quote=False)}:</b> {current} {html.escape(unit, quote=False)}",
    ]
    # Approved order: price → observed timestamp → comparison → source.
    parts.append(_price_datetime(snapshot.get("observed_at")))
    if comparison_line:
        parts.append(comparison_line)
    parts.append(source_line)
    message = "\n\n".join(parts)
    return message
