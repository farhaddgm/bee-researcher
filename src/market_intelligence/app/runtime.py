from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from redis.asyncio import Redis

from app.config import TIME_PATTERN, Settings
from app.pipeline_service import (
    _claim_job,
    _finish_job,
    apply_retention,
    generate_weekly_report,
    publish_ready_previews,
    record_feedback,
    run_pipeline,
)
from app.ingestion_service import run_degraded_source_health_probe
from app.queue_names import queue_key
from app.security_controls import redact_sensitive_text
from app.telegram_delivery import TelegramClient
from app.database import SessionLocal
from app.models import AssistantWorkspace
from app.bee_cfo.service import run_scheduled_reports, why_changed_for_report
from sqlalchemy import select


@dataclass(slots=True)
class RuntimeStatus:
    scheduler_running: bool = False
    telegram_poller_running: bool = False
    last_scheduler_tick: str | None = None
    last_scheduler_error: str | None = None
    last_pipeline_slot: str | None = None
    last_pipeline_status: str | None = None
    last_feedback_update_id: int | None = None


STATUS = RuntimeStatus()
LOGGER = logging.getLogger(__name__)
SCHEDULER_SETTINGS_KEY = queue_key("scheduler_settings")
WHY_CHANGED_COMMAND = re.compile(
    r"^\s*(?:/why(?:@[A-Za-z0-9_]+)?|چرا\s+تغییر\s+کرد[؟?]?)\s+([0-9a-fA-F-]{36})\s*$"
)


def _log_runtime_event(event: str, **fields: object) -> None:
    """Emit one redacted, machine-readable runtime event.

    Health probes are deliberately silent (``--no-access-log`` keeps the
    transport noise out of the container), while scheduler and delivery
    outcomes remain observable through a compact JSON record.  Only counts,
    statuses and identifiers already safe for operational logs are included;
    article text, credentials and upstream responses never enter this path.
    """
    payload = {"event": event, **fields}
    LOGGER.info("runtime_event=%s", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def normalize_schedule_times(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    if not cleaned or any(not TIME_PATTERN.fullmatch(value) for value in cleaned):
        raise ValueError("schedule_times must contain HH:MM values")
    return tuple(sorted(set(cleaned), key=lambda value: (int(value[:2]), int(value[3:]))))


def normalize_schedule_slots(values: list[dict[str, object]] | tuple[dict[str, object], ...]) -> tuple[tuple[int, str], ...]:
    slots: set[tuple[int, str]] = set()
    for raw in values:
        if not isinstance(raw, dict):
            raise ValueError("schedule_slots must contain objects")
        try:
            raw_weekday = raw.get("weekday")
            if isinstance(raw_weekday, bool) or not isinstance(raw_weekday, (int, str)):
                raise ValueError
            weekday = int(raw_weekday)
            value = str(raw.get("time", "")).strip()
        except (TypeError, ValueError):
            raise ValueError("schedule_slots must contain weekday and HH:MM") from None
        if weekday < 0 or weekday > 6 or not TIME_PATTERN.fullmatch(value):
            raise ValueError("schedule_slots weekday must be 0..6 and time must be HH:MM")
        slots.add((weekday, value))
    if not slots:
        raise ValueError("schedule_slots cannot be empty")
    return tuple(sorted(slots, key=lambda item: (item[0], int(item[1][:2]), int(item[1][3:]))))


def default_collection_schedule_slots() -> tuple[tuple[int, str], ...]:
    """Return the safe first-run collection cadence.

    Collection is intentionally separate from publication.  Three daily
    collection windows (10:00, 14:00 and 18:00) give a new workspace useful
    coverage without making the first configuration crawl every hour.
    Owners can replace this default with any non-empty 7x24 selection.
    """
    return tuple(
        (weekday, f"{hour:02d}:00")
        for weekday in range(7)
        for hour in (10, 14, 18)
    )


def latest_schedule_slot(
    now_utc: datetime,
    *,
    timezone_name: str,
    schedule_slots: tuple[tuple[int, str], ...],
) -> datetime | None:
    """Return the latest configured slot today that is not in the future.

    This is used only as the publication eligibility anchor.  It lets an
    evening publication slot deliver items collected at an earlier custom
    collection slot, while never reaching back into a previous calendar day.
    """
    zone = ZoneInfo(timezone_name)
    local_now = now_utc.astimezone(zone)
    candidates: list[datetime] = []
    for weekday, value in schedule_slots:
        if weekday != local_now.weekday():
            continue
        hour, minute = (int(part) for part in value.split(":"))
        candidate = datetime.combine(local_now.date(), time(hour, minute), tzinfo=zone)
        if candidate <= local_now:
            candidates.append(candidate.astimezone(timezone.utc))
    return max(candidates) if candidates else None


async def scheduler_schedule_times(settings: Settings) -> tuple[tuple[str, ...], bool]:
    slots, overridden = await scheduler_schedule_config(settings)
    return tuple(sorted({value for _, value in slots}, key=lambda value: (int(value[:2]), int(value[3:])))), overridden


async def scheduler_schedule_config(settings: Settings) -> tuple[tuple[tuple[int, str], ...], bool]:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        raw = await redis.get(SCHEDULER_SETTINGS_KEY)
        if not raw:
            return tuple((weekday, value) for weekday in range(7) for value in settings.schedule_time_values), False
        try:
            payload = json.loads(raw)
            if payload.get("schedule_slots"):
                values = normalize_schedule_slots(payload.get("schedule_slots", []))
            else:
                times = normalize_schedule_times(payload.get("schedule_times", []))
                values = tuple((weekday, value) for weekday in range(7) for value in times)
        except (TypeError, ValueError, json.JSONDecodeError, AttributeError):
            LOGGER.warning("invalid scheduler override; falling back to environment")
            return tuple((weekday, value) for weekday in range(7) for value in settings.schedule_time_values), False
        return values, True
    finally:
        await redis.aclose()


async def update_scheduler_schedule_times(settings: Settings, values: list[str]) -> tuple[str, ...]:
    normalized = normalize_schedule_times(values)
    await update_scheduler_schedule_slots(settings, [{"weekday": weekday, "time": value} for weekday in range(7) for value in normalized])
    return normalized


async def update_scheduler_schedule_slots(settings: Settings, values: list[dict[str, object]]) -> tuple[tuple[int, str], ...]:
    normalized = normalize_schedule_slots(values)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis.set(
            SCHEDULER_SETTINGS_KEY,
            json.dumps({
                "schedule_slots": [{"weekday": weekday, "time": value} for weekday, value in normalized],
                "schedule_times": sorted({value for _, value in normalized}, key=lambda value: (int(value[:2]), int(value[3:]))),
            }),
        )
    finally:
        await redis.aclose()
    return normalized


def due_schedule_slots(
    now_utc: datetime,
    *,
    timezone_name: str,
    schedule_times: tuple[str, ...],
    recovery_hours: int,
    schedule_slots: tuple[tuple[int, str], ...] | None = None,
) -> list[datetime]:
    zone = ZoneInfo(timezone_name)
    local_now = now_utc.astimezone(zone)
    cutoff = local_now - timedelta(hours=recovery_hours)
    slots: list[datetime] = []
    active_slots = schedule_slots or tuple((weekday, value) for weekday in range(7) for value in schedule_times)
    for day in {local_now.date(), cutoff.date()}:
        for weekday, value in active_slots:
            if day.weekday() != weekday:
                continue
            hour, minute = (int(part) for part in value.split(":"))
            local_slot = datetime.combine(day, time(hour, minute), tzinfo=zone)
            if cutoff <= local_slot <= local_now:
                slots.append(local_slot.astimezone(timezone.utc))
    return sorted(set(slots))


def current_schedule_slots(
    now_utc: datetime,
    *,
    timezone_name: str,
    schedule_slots: tuple[tuple[int, str], ...] | None = None,
    schedule_times: tuple[str, ...] = (),
) -> list[datetime]:
    """Return only the schedule slot that is active right now.

    Scheduled delivery must not replay a missed slot.  The scheduler polls
    every few seconds, so the one-minute wall-clock window is enough to catch
    the configured slot while making a late restart a no-op for that slot.
    ``due_schedule_slots`` remains available for reporting/legacy recovery
    semantics; delivery uses this strict helper instead.
    """
    zone = ZoneInfo(timezone_name)
    local_now = now_utc.astimezone(zone)
    active_slots = schedule_slots or tuple(
        (weekday, value) for weekday in range(7) for value in schedule_times
    )
    slots: list[datetime] = []
    for weekday, value in active_slots:
        hour, minute = (int(part) for part in value.split(":"))
        if local_now.weekday() != weekday or local_now.hour != hour or local_now.minute != minute:
            continue
        local_slot = datetime.combine(
            local_now.date(), time(hour, minute), tzinfo=zone
        )
        slots.append(local_slot.astimezone(timezone.utc))
    return sorted(set(slots))


def hourly_processing_slot(now_utc: datetime, *, timezone_name: str) -> datetime:
    """Return the idempotent hourly collection slot in UTC.

    Collection is intentionally decoupled from publication hours: every
    configured source is checked once per local clock hour, while delivery
    remains restricted to the project's selected schedule slots.
    """
    zone = ZoneInfo(timezone_name)
    local_now = now_utc.astimezone(zone)
    slot = local_now.replace(minute=0, second=0, microsecond=0)
    return slot.astimezone(timezone.utc)


def weekly_slot(now_utc: datetime, settings: Settings) -> datetime | None:
    zone = ZoneInfo(settings.timezone)
    local_now = now_utc.astimezone(zone)
    hour, minute = (int(value) for value in settings.weekly_report_time.split(":"))
    candidate = datetime.combine(local_now.date(), time(hour, minute), tzinfo=zone)
    if (
        local_now.weekday() == settings.weekly_report_weekday
        and candidate <= local_now < candidate + timedelta(hours=settings.missed_run_recovery_hours)
    ):
        return candidate.astimezone(timezone.utc)
    return None


async def scheduler_tick(settings: Settings, *, now: datetime | None = None) -> dict[str, object]:
    now = now or datetime.now(timezone.utc)
    schedule_times, _ = await scheduler_schedule_times(settings)
    schedule_slots, _ = await scheduler_schedule_config(settings)
    pipeline_results: list[dict[str, object]] = []
    async with SessionLocal() as session:
        assistants = (await session.execute(select(AssistantWorkspace.id, AssistantWorkspace.status, AssistantWorkspace.config))).all()
    scheduled_assistants: list[tuple[uuid.UUID | None, tuple[tuple[int, str], ...], bool, bool, str, bool, tuple[tuple[int, str], ...]]] = []
    for assistant_id, status, config in assistants:
        if status not in {"active", "testing"}:
            continue
        runtime = (config or {}).get("runtime") or {}
        raw_slots = runtime.get("schedule_slots")
        if raw_slots:
            try:
                assistant_slots = normalize_schedule_slots(raw_slots)
            except ValueError:
                LOGGER.warning("invalid schedule slots for assistant %s; using global schedule", assistant_id)
                assistant_slots = schedule_slots
        else:
            assistant_slots = schedule_slots
        raw_collection_slots = runtime.get("collection_schedule_slots")
        if raw_collection_slots:
            try:
                collection_slots = normalize_schedule_slots(raw_collection_slots)
            except ValueError:
                LOGGER.warning("invalid collection schedule for assistant %s; using default collection cadence", assistant_id)
                collection_slots = default_collection_schedule_slots()
        else:
            collection_slots = default_collection_schedule_slots()
        collection_enabled = runtime.get("collection_enabled", True) is not False
        assistant_timezone = str(runtime.get("timezone") or settings.timezone)
        try:
            ZoneInfo(assistant_timezone)
        except (ZoneInfoNotFoundError, ValueError):
            LOGGER.warning("invalid timezone for assistant %s; using service timezone", assistant_id)
            assistant_timezone = settings.timezone
        scheduled_assistants.append((assistant_id, assistant_slots, bool(runtime.get("bootstrap_pending")), (config or {}).get("product") == "bee_cfo", assistant_timezone, collection_enabled, collection_slots))
    if not scheduled_assistants:
        scheduled_assistants = [(None, schedule_slots, False, False, settings.timezone, True, default_collection_schedule_slots())]
    for assistant_id, assistant_slots, bootstrap_pending, is_bee_cfo, assistant_timezone, collection_enabled, collection_slots in scheduled_assistants:
        assistant_suffix = str(assistant_id) if assistant_id else "default"
        collection_due = current_schedule_slots(
            now,
            timezone_name=assistant_timezone,
            schedule_slots=collection_slots,
        )
        hourly_result: dict[str, object]
        if is_bee_cfo and assistant_id is not None:
            # Bee CFO has its own report contract and does not enter the
            # Researcher publication pipeline.  Its schedule is still claimed
            # with the shared job/idempotency mechanism and its adapter owns
            # collection, report persistence, alerts and forecasts.
            slots = current_schedule_slots(
                now,
                timezone_name=assistant_timezone,
                schedule_times=schedule_times,
                schedule_slots=assistant_slots,
            )
            for slot in slots:
                report_key = f"bee-cfo-scheduled-report:{assistant_suffix}:{slot.isoformat()}"
                report_job_id, report_claim = await _claim_job(
                    report_key,
                    "bee_cfo_report",
                    assistant_id=assistant_id,
                )
                if report_job_id is None:
                    pipeline_results.append({
                        "kind": "bee_cfo_report",
                        "slot": slot.isoformat(),
                        "status": "duplicate",
                        "claim": report_claim,
                    })
                    continue
                try:
                    report_result = await run_scheduled_reports(assistant_id=assistant_id, now=slot)
                    await _finish_job(report_job_id, status="succeeded", result=report_result)
                except Exception as exc:
                    failure_message = redact_sensitive_text(f"{type(exc).__name__}: {exc}", limit=500)
                    report_result = {"status": "failed", "error": failure_message}
                    await _finish_job(report_job_id, status="failed", result=report_result, error=failure_message)
                pipeline_results.append({"kind": "bee_cfo_report", "slot": slot.isoformat(), "report": report_result})
                STATUS.last_pipeline_slot = slot.isoformat()
                STATUS.last_pipeline_status = str(report_result.get("status"))
            continue
        # A newly-created workspace should not wait for an arbitrary clock
        # slot before its first catch-up. Once it is activated/testing, run a
        # forced ingestion using that workspace's freshness window, then fall
        # back to the configured collection cadence on subsequent ticks.
        if assistant_id is not None and bootstrap_pending and collection_enabled:
            bootstrap_key = f"bootstrap:{assistant_id}"
            result = await run_pipeline(
                assistant_id=assistant_id,
                force_ingestion=True,
                publish=False,
                idempotency_key=bootstrap_key,
            )
            pipeline_results.append(result)
            hourly_result = result
            if result.get("status") in {"completed", "duplicate"}:
                async with SessionLocal() as session:
                    assistant = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
                    if assistant is not None:
                        config = dict(assistant.config or {})
                        runtime = dict(config.get("runtime") or {})
                        runtime["bootstrap_pending"] = False
                        config["runtime"] = runtime
                        assistant.config = config
                        await session.commit()
            STATUS.last_pipeline_status = str(result.get("status"))
        elif collection_enabled and collection_due:
            # Collection is owner-configurable and independent from
            # publication.  The idempotency key makes the 30-second
            # scheduler poll safe and prevents duplicate work on restart.
            collection_slot = collection_due[-1]
            collection_key = f"collection:{assistant_suffix}:{collection_slot.isoformat()}"
            hourly_result = await run_pipeline(
                assistant_id=assistant_id,
                publish=False,
                idempotency_key=collection_key,
            )
            pipeline_results.append({
                "kind": "collection_analysis",
                "slot": collection_slot.isoformat(),
                "pipeline": hourly_result,
            })
            STATUS.last_pipeline_status = str(hourly_result.get("status"))
        else:
            hourly_result = {"status": "collection_disabled" if not collection_enabled else "collection_not_due"}
        # Delivery is intentionally strict: a scheduler restart or a missed
        # tick must not replay old slots and publish a backlog in one burst.
        # Processing remains hourly and can continue to collect/score up to
        # the daily processing budget independently of this delivery gate.
        slots = current_schedule_slots(
            now,
            timezone_name=assistant_timezone,
            schedule_times=schedule_times,
            schedule_slots=assistant_slots,
        )
        for slot in slots:
            # Claim the exact assistant/slot before delivery.  The scheduler
            # polls repeatedly during the same minute; without this claim,
            # every poll could publish another batch and exceed the cap.
            publication_key = f"scheduled-publication:{assistant_suffix}:{slot.isoformat()}"
            publication_job_id, publication_claim = await _claim_job(
                publication_key,
                "scheduled_publication",
                assistant_id=assistant_id,
            )
            if publication_job_id is None:
                pipeline_results.append({
                    "kind": "scheduled_publication",
                    "slot": slot.isoformat(),
                    "delivery": {"published": 0, "status": "duplicate", "claim": publication_claim},
                })
                continue
            try:
                # Only previews created during the current local hour are
                # eligible.  Older previews belong to a missed slot and are
                # deliberately left for review/manual publication instead of
                # being carried into the next scheduled burst.
                collection_anchor = latest_schedule_slot(
                    now,
                    timezone_name=assistant_timezone,
                    schedule_slots=collection_slots,
                ) or hourly_processing_slot(now, timezone_name=assistant_timezone)
                delivery = await publish_ready_previews(
                    settings,
                    limit=settings.max_items_per_run,
                    assistant_id=assistant_id,
                    created_after=collection_anchor,
                )
                await _finish_job(publication_job_id, status="succeeded", result=delivery)
            except Exception as exc:
                failure_message = redact_sensitive_text(f"{type(exc).__name__}: {exc}", limit=500)
                delivery = {"published": 0, "status": "failed", "error": failure_message}
                await _finish_job(publication_job_id, status="failed", result=delivery, error=failure_message)
            pipeline_results.append({
                "kind": "scheduled_publication",
                "slot": slot.isoformat(),
                "delivery": delivery,
            })
            STATUS.last_pipeline_slot = slot.isoformat()
            STATUS.last_pipeline_status = str(delivery.get("status", "completed"))

    weekly_result: dict[str, object] | None = None
    report_slot = weekly_slot(now, settings)
    if report_slot is not None:
        key = f"weekly:{report_slot.date().isoformat()}"
        job_id, state = await _claim_job(key, "weekly_report")
        if job_id is not None:
            try:
                weekly_result = await generate_weekly_report(now=report_slot)
                await _finish_job(job_id, status="succeeded", result=weekly_result)
            except Exception as exc:
                weekly_result = {"status": "failed", "error": redact_sensitive_text(f"{type(exc).__name__}: {exc}")}
                await _finish_job(
                    job_id,
                    status="failed",
                    result=weekly_result,
                    error=str(weekly_result["error"]),
                )
        else:
            weekly_result = {"status": "duplicate", "existing_status": state}

    retention_key = f"retention:{now.date().isoformat()}"
    retention_job_id, retention_state = await _claim_job(retention_key, "retention")
    retention_result: dict[str, object]
    if retention_job_id is not None:
        try:
            retention_result = dict(await apply_retention(settings))
            await _finish_job(retention_job_id, status="succeeded", result=retention_result)
        except Exception as exc:
            failure_message = redact_sensitive_text(f"{type(exc).__name__}: {exc}")
            retention_result = {"status": "failed", "error": failure_message}
            await _finish_job(
                retention_job_id,
                status="failed",
                result=retention_result,
                error=failure_message,
            )
    else:
        retention_result = {"status": "duplicate", "existing_status": retention_state}
    health_probe_key = f"health-probe:{now.date().isoformat()}"
    health_job_id, health_state = await _claim_job(health_probe_key, "source_health_probe")
    if health_job_id is not None:
        try:
            health_probe_result = await run_degraded_source_health_probe()
            await _finish_job(health_job_id, status="succeeded", result=health_probe_result)
        except Exception as exc:
            health_probe_result = {"status": "failed", "error": redact_sensitive_text(f"{type(exc).__name__}: {exc}")}
            await _finish_job(health_job_id, status="failed", result=health_probe_result, error=str(health_probe_result["error"]))
    else:
        health_probe_result = {"status": "duplicate", "existing_status": health_state}
    return {
        "pipeline_slots": [slot.isoformat() for slot in slots],
        "pipeline_results": pipeline_results,
        "weekly": weekly_result,
        "retention": retention_result,
        "degraded_source_health_probe": health_probe_result,
    }


async def scheduler_loop(settings: Settings, stop: asyncio.Event) -> None:
    STATUS.scheduler_running = True
    try:
        while not stop.is_set():
            try:
                result = await scheduler_tick(settings)
                STATUS.last_scheduler_tick = datetime.now(timezone.utc).isoformat()
                STATUS.last_scheduler_error = None
                pipeline_results_value = result.get("pipeline_results")
                if isinstance(pipeline_results_value, list) and pipeline_results_value:
                    last_result = pipeline_results_value[-1]
                    if isinstance(last_result, dict):
                        STATUS.last_pipeline_status = str(last_result.get("status"))
                    summaries = []
                    for item in pipeline_results_value:
                        if not isinstance(item, dict):
                            continue
                        delivery_value = item.get("delivery")
                        delivery = delivery_value if isinstance(delivery_value, dict) else {}
                        pipeline_value = item.get("pipeline")
                        pipeline = pipeline_value if isinstance(pipeline_value, dict) else {}
                        summaries.append({
                            "kind": item.get("kind", "pipeline"),
                            "status": delivery.get("status") or pipeline.get("status") or item.get("status"),
                            "published": delivery.get("published", 0),
                        })
                    _log_runtime_event(
                        "scheduler_tick",
                        result_count=len(pipeline_results_value),
                        results=summaries[:20],
                    )
            except Exception as exc:
                STATUS.last_scheduler_error = redact_sensitive_text(f"{type(exc).__name__}: {exc}")
                _log_runtime_event("scheduler_error", error=STATUS.last_scheduler_error)
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.scheduler_poll_seconds)
            except TimeoutError:
                pass
    finally:
        STATUS.scheduler_running = False


async def telegram_feedback_loop(settings: Settings, stop: asyncio.Event) -> None:
    if not settings.telegram_ready or not settings.telegram_polling_enabled:
        return
    STATUS.telegram_poller_running = True
    telegram = TelegramClient(settings)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    offset_key = queue_key("telegram_update_offset", settings=settings)
    try:
        stored_offset = await redis.get(offset_key)
        offset = int(stored_offset) if stored_offset else None
        while not stop.is_set():
            try:
                updates = await telegram.get_updates(offset)
                for update in updates:
                    raw_update_id = update.get("update_id", 0)
                    try:
                        update_id = int(raw_update_id) if isinstance(raw_update_id, (int, str)) else 0
                    except (TypeError, ValueError, OverflowError):
                        update_id = 0
                    offset = update_id + 1
                    STATUS.last_feedback_update_id = update_id
                    callback_value = update.get("callback_query")
                    callback = callback_value if isinstance(callback_value, dict) else {}
                    callback_id = str(callback.get("id") or "")
                    data = str(callback.get("data") or "")
                    user_value = callback.get("from")
                    user = user_value if isinstance(user_value, dict) else {}
                    username = str(user.get("username") or "").lower()
                    parts = data.split(":", 2)
                    if len(parts) != 3 or parts[0] != "mi" or parts[1] not in {"up", "down"}:
                        message = update.get("message") or {}
                        chat = message.get("chat") if isinstance(message, dict) else {}
                        sender = message.get("from") if isinstance(message, dict) else {}
                        text = str(message.get("text") or "") if isinstance(message, dict) else ""
                        username = str(sender.get("username") or "").strip().lower().lstrip("@") if isinstance(sender, dict) else ""
                        chat_id = str(chat.get("id") or "") if isinstance(chat, dict) else ""
                        private_chat = isinstance(chat, dict) and str(chat.get("type") or "") == "private"
                        command = WHY_CHANGED_COMMAND.fullmatch(text)
                        if not command or not private_chat or username not in settings.allowed_telegram_username_values or not chat_id:
                            continue
                        rate_key = queue_key(f"bee_cfo_why_{username}", settings=settings)
                        if not await redis.set(rate_key, "1", ex=60, nx=True):
                            await telegram.send_analysis(
                                "لطفاً یک دقیقه دیگر دوباره تلاش کنید.",
                                analysis_id=__import__("uuid").UUID(command.group(1)),
                                channel_id=chat_id,
                                include_feedback_buttons=False,
                                silent=True,
                                message_limit=1200,
                            )
                            continue
                        try:
                            result = await why_changed_for_report(
                                __import__("uuid").UUID(command.group(1)), requestor=username
                            )
                            await telegram.send_analysis(
                                str(result["message"]),
                                analysis_id=__import__("uuid").UUID(command.group(1)),
                                channel_id=chat_id,
                                include_feedback_buttons=False,
                                silent=True,
                                message_limit=1200,
                            )
                        except (KeyError, ValueError):
                            await telegram.send_analysis(
                                "شناسهٔ گزارش معتبر نیست یا به Bee CFO تعلق ندارد.",
                                analysis_id=__import__("uuid").UUID(command.group(1)),
                                channel_id=chat_id,
                                include_feedback_buttons=False,
                                silent=True,
                                message_limit=1200,
                            )
                        except Exception:
                            LOGGER.exception("unexpected Bee CFO why-changed command failure")
                            await telegram.send_analysis(
                                "پاسخ «چرا تغییر کرد؟» اکنون آماده نیست.",
                                analysis_id=__import__("uuid").UUID(command.group(1)),
                                channel_id=chat_id,
                                include_feedback_buttons=False,
                                silent=True,
                                message_limit=1200,
                            )
                        continue
                    try:
                        analysis_id = __import__("uuid").UUID(parts[2])
                        feedback_result = await record_feedback(
                            analysis_id,
                            actor_key=username,
                            value=parts[1],
                            source="telegram_callback",
                        )
                        if callback_id:
                            await telegram.answer_callback(
                                callback_id,
                                "این بازخورد قبلاً ثبت شده است."
                                if feedback_result.get("duplicate")
                                else "بازخورد ثبت شد.",
                            )
                    except ValueError as exc:
                        LOGGER.warning("feedback rejected: %s", redact_sensitive_text(str(exc), limit=300))
                        if callback_id:
                            await telegram.answer_callback(callback_id, str(exc))
                    except Exception:
                        LOGGER.exception("unexpected Telegram feedback failure")
                        if callback_id:
                            await telegram.answer_callback(callback_id, "ثبت بازخورد ناموفق بود.")
                if offset is not None:
                    await redis.set(offset_key, str(offset))
            except Exception:
                await asyncio.sleep(5)
    finally:
        STATUS.telegram_poller_running = False
        await redis.aclose()


def runtime_status() -> dict[str, object]:
    return asdict(STATUS)


def runtime_readiness(settings: Settings, *, now: datetime | None = None) -> dict[str, object]:
    """Return the process-local readiness signals used by ``/ready``.

    ``/health`` is intentionally a cheap liveness probe for the container
    runtime.  Readiness additionally needs to tell an operator whether the
    scheduler and Telegram poller have actually started and whether the
    scheduler heartbeat is fresh.  Keeping this calculation pure makes it
    deterministic in tests and avoids an external Telegram call on every
    health probe.
    """
    now = now or datetime.now(timezone.utc)
    status = runtime_status()
    scheduler_required = bool(settings.scheduler_enabled)
    last_tick = status.get("last_scheduler_tick")
    heartbeat_fresh = False
    if isinstance(last_tick, str):
        try:
            tick = datetime.fromisoformat(last_tick.replace("Z", "+00:00"))
            if tick.tzinfo is None:
                tick = tick.replace(tzinfo=timezone.utc)
            heartbeat_fresh = (now - tick.astimezone(timezone.utc)).total_seconds() <= max(
                90, settings.scheduler_poll_seconds * 4
            )
        except ValueError:
            heartbeat_fresh = False
    scheduler_state = (
        "healthy"
        if not scheduler_required or (bool(status.get("scheduler_running")) and heartbeat_fresh)
        else "starting" if bool(status.get("scheduler_running")) else "stopped"
    )
    telegram_required = bool(settings.telegram_ready and settings.telegram_polling_enabled)
    telegram_state = "healthy" if not telegram_required or bool(status.get("telegram_poller_running")) else "stopped"
    ready = scheduler_state == "healthy" and telegram_state == "healthy"
    return {
        "ready": ready,
        "scheduler": scheduler_state,
        "telegram_poller": telegram_state,
        "last_scheduler_tick": last_tick,
        "last_scheduler_error": status.get("last_scheduler_error"),
    }
