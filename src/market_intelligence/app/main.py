from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import re
import secrets
import time
import uuid
from collections import deque
from collections.abc import Mapping
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from fastapi import Cookie, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import get_settings
from app.report_portal.ui import REPORT_HTML
from app.portals import portal_spec
from app.observability import configure_logging
from app.ui_assets import ASSETS as UI_ASSETS, externalize_document
from app.database import SessionLocal, check_database
from app.deployment_drain import engine as deployment_lease_engine, work_lease
from app.models import AssistantWorkspace
from app.ingestion_service import (
    DEFAULT_ASSISTANT_ID,
    list_sources,
    run_degraded_source_health_probe,
    run_ingestion,
    run_source_probe,
    run_source_health_probe,
)
from app.pipeline_service import (
    apply_retention,
    apply_feedback_ranking,
    feedback_daily_report,
    generate_weekly_report,
    list_publications,
    list_relevance_assessments,
    pipeline_metrics,
    publish_publication,
    approve_borderline_publication,
    refresh_publication_previews,
    regenerate_fallback_analyses,
    reanalyze_fallback_articles,
    rescore_existing_articles,
    run_pipeline,
    settings_for_assistant,
)
from app.insights import (
    activate_official_fallback,
    insights_snapshot,
    translate_analysis,
)
from app.queue_names import get_queue_names
from app.runtime import (
    default_collection_schedule_slots,
    normalize_schedule_slots,
    runtime_status,
    scheduler_loop,
    scheduler_schedule_config,
    scheduler_schedule_times,
    runtime_readiness,
    telegram_feedback_loop,
    update_scheduler_schedule_slots,
)
from app.security_controls import redact_sensitive_text
from app.telegram_delivery import TelegramClient
from app.whatsapp_delivery import WhatsAppClient
from app.bee_cfo.api import router as bee_cfo_router
from app.admin import (
    AdminUserManageUpdate,
    AdminUserPasswordUpdate,
    AdminUserRequest,
    AdminUserUpdate,
    AccountPreferencesUpdate,
    ReaderPreferencesUpdate,
    ReaderFeedbackRequest,
    UserPortalAccessUpdate,
    NewsViewRequest,
    PublicationBulkRequest,
    PublicationBulkUndoRequest,
    AssistantDraftRequest,
    AssistantCloneRequest,
    AssistantMemberRequest,
    AssistantRequest,
    AssistantRuntimeSettingsUpdate,
    RuntimeSettingsPreviewRequest,
    PublicationReviewRequest,
    ShareLinkCreateRequest,
    AssistantLimitsUpdate,
    AssistantUpdate,
    BusinessDraftRequest,
    BusinessProfileCreate,
    BusinessProfileUpdate,
    BusinessKnowledgeUpdate,
    CatalogDraftRequest,
    ChangePasswordRequest,
    LoginRequest,
    OrderMoveRequest,
    PublicSocialSourceCreate,
    SourceCreate,
    SourceUpdate,
    SupportTicketCreate,
    SupportTicketMessageCreate,
    SupportTicketUpdate,
    TelegramSettingsUpdate,
    TopicCreate,
    TopicUpdate,
    TemplateBlocksRequest,
    PrivacySettingsUpdate,
    _require_assistant_access,
    activate_assistant,
    assign_assistant_member,
    assistant_readiness,
    assistants,
    change_password,
    change_user_password,
    clone_assistant,
    create_admin_user,
    create_assistant,
    create_business_profile,
    create_source,
    create_public_social_source,
    create_source_suggestion,
    create_topic,
    current_admin,
    default_avatar_data,
    decide_source_suggestion,
    delete_admin_user,
    delete_assistant,
    permanently_delete_assistant,
    restore_assistant,
    delete_business_profile,
    delete_source,
    delete_topic,
    draft_business,
    draft_source,
    draft_topic,
    draft_assistant,
    effective_user_role,
    get_assistant_runtime_settings,
    get_assistant_limits,
    get_assistant_telegram,
    get_assistant_templates,
    get_account_preferences,
    get_business_profile,
    get_business_knowledge,
    update_business_knowledge,
    feedback_learning_center,
    rollback_feedback_ranking,
    list_event_clusters,
    get_privacy_settings,
    update_privacy_settings,
    export_assistant_data,
    is_global_admin,
    is_owner,
    list_active_sessions,
    list_admin_users,
    list_admin_notifications,
    list_support_tickets,
    list_admin_incidents,
    list_news_views,
    list_assistant_members,
    list_business_profiles,
    list_source_suggestions,
    list_topics,
    login as admin_login,
    logout as admin_logout,
    manage_admin_user,
    update_user_portal_access,
    mark_admin_notifications_read,
    save_news_view,
    delete_news_view,
    bulk_publications,
    undo_bulk_publications,
    close_admin_incident,
    move_source,
    move_topic,
    preview_assistant_template,
    remove_assistant_member,
    revoke_other_sessions,
    revoke_session,
    update_admin_user,
    update_assistant,
    update_assistant_runtime_settings,
    preview_assistant_runtime_settings,
    review_publication,
    publication_explanation,
    create_share_link,
    revoke_share_link,
    resolve_share_link,
    update_assistant_limits,
    update_assistant_template,
    update_assistant_telegram,
    update_account_preferences,
    update_business_profile,
    update_source,
    update_topic,
    create_support_ticket,
    add_support_ticket_message,
    update_support_ticket,
    USER_SESSION_COOKIE,
    current_reader,
    reader_assistants,
    user_portal_access_payload,
    record_reader_feedback,
    get_reader_preferences,
    list_reader_annotations,
    update_reader_preferences,
    update_reader_annotation,
    ReaderAnnotationUpdate,
    reader_login,
    reader_logout,
    GoogleAccessGrant,
    GoogleAccessUpdate,
    grant_google_access,
    list_google_access,
    login_with_google,
    record_admin_feedback,
    require_editor_role,
    revoke_google_access,
    set_admin_session_cookies,
    set_reader_session_cookie,
    update_google_access,
)
from app import accounts, google_auth
from app.admin_ui import ADMIN_HTML
from app.user_ui import USER_HTML


_INLINE_NONCE_TAG = re.compile(r"<(script|style)(?![^>]*\bnonce=)([^>]*)>")


def _inject_inline_nonce(body: str, nonce: str) -> str:
    """Attach the request nonce to every inline script/style opening tag.

    Late UI layers carry stable ``id`` attributes, so a bare-tag string
    replacement misses them and the browser blocks those layers under the
    nonce-based CSP.
    """

    return _INLINE_NONCE_TAG.sub(
        lambda match: f'<{match.group(1)} nonce="{nonce}"{match.group(2)}>',
        body,
    )
def _login_document(body: str, portal: str, *, password: bool = False) -> str:
    """Choose the auth UI before first paint; never expose a password fallback."""
    mode = "password" if password else "google"
    attrs = f'data-login-mode="{mode}" data-auth-portal="{portal}" data-google-ready="{str(settings.google_login_ready).lower()}"'
    body = body.replace("<body>", f"<body {attrs}>", 1)
    if portal == "admin":
        body = body.replace('</head>', '<link rel="stylesheet" href="/assets/news-chat/chat.css"></head>', 1).replace(
            '</body>', '<script src="/assets/news-chat/i18n.js"></script><script src="/assets/news-chat/admin.js"></script></body>', 1,
        )
    return externalize_document(body)


from app.security_controls import (
    ADMIN_SESSION_COOKIE,
    CSRF_COOKIE,
    clear_login_failures,
    csrf_token_matches,
    login_attempts_exceeded,
    login_ip_attempts_exceeded,
    record_ip_login_failure,
    record_login_failure,
)


_ADMIN_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_ADMIN_ASSETS = {
    "bee.svg": "image/svg+xml",
    "bee-researcher.svg": "image/svg+xml",
    "bee-researcher-grey.svg": "image/svg+xml",
    "Vazirmatn-Regular.woff2": "font/woff2",
    "Vazirmatn-Medium.woff2": "font/woff2",
    "Vazirmatn-SemiBold.woff2": "font/woff2",
    "Vazirmatn-Bold.woff2": "font/woff2",
    "Vazirmatn-ExtraBold.woff2": "font/woff2",
}


settings = get_settings()
configure_logging()
logger = logging.getLogger(__name__)

# Prime every process before its first request; an asset request may land on
# a different worker from the document request. Never rely on sticky routing.
externalize_document(ADMIN_HTML)
externalize_document(USER_HTML)
externalize_document(REPORT_HTML)


class _ClientErrorRateLimiter:
    """Bound authenticated browser telemetry without retaining session IDs.

    This endpoint is intentionally best-effort and its limiter is process-local:
    it protects the application log from a noisy/malfunctioning browser while
    keeping telemetry independent from Redis availability. Keys are one-way
    hashes of session tokens, never usernames, IP addresses or raw cookies.
    """

    def __init__(self, *, limit: int = 60, window_seconds: int = 300, max_clients: int = 2048) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_clients = max_clients
        self._events: dict[str, deque[float]] = {}

    def allow(self, session_token: str, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        key = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
        events = self._events.get(key)
        if events is None:
            if len(self._events) >= self.max_clients:
                expired = [client for client, samples in self._events.items() if not samples or samples[-1] <= current - self.window_seconds]
                for client in expired:
                    self._events.pop(client, None)
                if len(self._events) >= self.max_clients:
                    oldest = min(self._events, key=lambda client: self._events[client][-1] if self._events[client] else float("-inf"))
                    self._events.pop(oldest, None)
            events = self._events.setdefault(key, deque())
        cutoff = current - self.window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= self.limit:
            return False
        events.append(current)
        return True


_client_error_rate_limiter = _ClientErrorRateLimiter()
_csp_log_rate_limiter = _ClientErrorRateLimiter(limit=60, window_seconds=60, max_clients=1)


def _safe_telemetry_token(value: object, limit: int = 64) -> str:
    token_value = str(value or "")[:limit]
    return token_value if re.fullmatch(r"[A-Za-z0-9_.:-]+", token_value or "") else "unknown"


# A character whitelist is not a privacy boundary: passwords and account IDs
# can use that same alphabet. Accept only context defined by our own UI.
_TELEMETRY_VIEWS = frozenset({"assistants", "overview", "publications", "feedback",
    "businesses", "sources", "topics", "schedule", "content", "settings",
    "operations", "support", "accounts", "unknown"})
_TELEMETRY_ACTIONS = frozenset(re.findall(r'id=["\']([A-Za-z][A-Za-z0-9]*Btn)["\']', ADMIN_HTML)) | {
    "catalog_source", "catalog_topic", "unknown"}
_TELEMETRY_PHASES = frozenset({"click", "workspace", "replay_target", "replay",
    "modal", "handler", "request", "timeout", "unknown"})
_TELEMETRY_OUTCOMES = frozenset({"ok", "waiting", "error", "unknown"})


def _telemetry_enum(value: object, allowed: frozenset[str]) -> str:
    return value if isinstance(value, str) and value in allowed else "unknown"


def _telemetry_route(value: object) -> str:
    """Log a registered route template, never a caller's URL or identifiers."""
    if value == "client":
        return "client"
    if not isinstance(value, str) or len(value) > 512:
        return "unknown"
    path = value.split("?", 1)[0]
    for route in app.routes:
        template = getattr(route, "path", "")
        if not template.startswith("/admin/api/"):
            continue
        pattern = re.sub(r"\\\{[^}]+\\\}", r"[^/]+", re.escape(template))
        if re.fullmatch(pattern, path):
            return re.sub(r"\{[^}]+\}", ":id", template)
    return "unknown"


def _reader_assistant_is_accessible(
    available: Mapping[str, object], assistant_id: uuid.UUID
) -> bool:
    """Fail closed if the workspace service returns a malformed access list."""
    assistant_rows = available.get("assistants")
    return isinstance(assistant_rows, list) and any(
        isinstance(item, Mapping) and str(item.get("id") or "") == str(assistant_id)
        for item in assistant_rows
    )


async def _read_bounded_request_body(request: Request, limit: int) -> bytes | None:
    """Read only small telemetry payloads without buffering arbitrary bodies."""
    content_length = request.headers.get("content-length", "").strip()
    if content_length:
        try:
            if int(content_length) > limit:
                return None
        except ValueError:
            return None
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop = asyncio.Event()
    tasks: list[asyncio.Task] = []
    report_tasks: list[asyncio.Task] = []
    if settings.deployment_drain_enabled:
        from app.pipeline_service import reconcile_jobs_before_startup
        boot_time = datetime.now(timezone.utc)
        async def recovery():
            # A deploy may still hold admission while the new HTTP server
            # starts. Retry after release instead of deadlocking readiness.
            while not stop.is_set():
                try:
                    count = await reconcile_jobs_before_startup(started_before=boot_time)
                    logger.info("startup_job_reconciliation completed=%d", count)
                    return
                except Exception as exc:
                    logger.info("startup_job_reconciliation deferred type=%s", type(exc).__name__)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=30)
                except TimeoutError:
                    pass
        tasks.append(asyncio.create_task(recovery()))
    if settings.news_chat_enabled:
        from app.news_chat.service import worker, maintenance
        tasks.extend(asyncio.create_task(worker(stop)) for _ in range(4))
        tasks.append(asyncio.create_task(maintenance(stop)))
    if settings.report_portal_enabled:
        from app.report_portal.service import worker as report_worker, maintenance as report_maintenance
        from app.report_portal.policy import enabled as report_enabled
        from app.report_portal.deletions import prepare as prepare_report_registry
        report_enabled()
        await prepare_report_registry()
        report_tasks.extend(asyncio.create_task(report_worker(stop)) for _ in range(settings.report_worker_concurrency))
        report_tasks.append(asyncio.create_task(report_maintenance(stop)))
        tasks.extend(report_tasks)
    from app.contenter import connection_status, sync_loop
    if connection_status(settings)["configured"]:
        tasks.append(asyncio.create_task(sync_loop(settings, stop)))
    if settings.scheduler_enabled:
        tasks.append(asyncio.create_task(scheduler_loop(settings, stop)))
    if settings.telegram_ready and settings.telegram_polling_enabled:
        tasks.append(asyncio.create_task(telegram_feedback_loop(settings, stop)))
    try:
        yield
    finally:
        stop.set()
        for task in report_tasks:
            # Abandoned private leases are reconciled without paid retry.
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await deployment_lease_engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    docs_url=None if settings.environment == "production" else "/docs",
    redoc_url=None,
    lifespan=lifespan,
)

_allowed_hosts = [host for host in (settings.domain, settings.legacy_domain) if host]
if _allowed_hosts:
    _allowed_hosts.extend(["localhost", "127.0.0.1", "[::1]", "testserver"])
else:
    # Test/local installations without an explicit public domain retain the
    # existing host flexibility; production deployments should set DOMAIN.
    _allowed_hosts = ["*"]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts)
# The admin shell is intentionally self-contained so it can load atomically,
# but that also makes its HTML response large. Compress text responses at the
# application boundary; browsers that do not advertise gzip are unchanged.
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.middleware("http")
async def deployment_admission(request: Request, call_next):
    if request.method in {"GET", "HEAD", "OPTIONS"} or not settings.deployment_drain_enabled:
        return await call_next(request)
    try:
        async with work_lease(enabled=True):
            return await call_next(request)
    except HTTPException as exc:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)

# Bee CFO exposes an API/control contract only in phase one.  Its back-office
# UI is intentionally out of scope; the router remains independently removable
# when the bounded context is split into its own service.
app.include_router(bee_cfo_router)


@app.exception_handler(RequestValidationError)
async def private_validation_errors(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/report/api/"):
        allowed={"business_id","assistant_id","title","text","tags","reporter","event_date","language","classification","revision","draft_key","idempotency_key","confirmed","models","daily_cap","daily_budget_usd","retention_days","report_id","offset"}
        return JSONResponse(status_code=422, content={"detail": "report_invalid_fields",
            "fields": list(dict.fromkeys(str(e["loc"][1]) for e in exc.errors() if len(e["loc"])>1 and str(e["loc"][1]) in allowed))[:16]})
    return await request_validation_exception_handler(request, exc)


def _redact_http_detail(value):
    """Prevent exception text from becoming a credential-bearing API reply."""
    if isinstance(value, str):
        return redact_sensitive_text(value, limit=500)
    if isinstance(value, list):
        return [_redact_http_detail(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_http_detail(item) for key, item in value.items()}
    return value


def _csp_report_items(payload: object) -> list[dict[str, object]]:
    """Keep only bounded, non-sensitive fields from browser CSP reports."""

    if isinstance(payload, dict):
        reports = payload.get("csp-report", payload.get("body", payload))
    else:
        reports = payload
    if isinstance(reports, dict):
        reports = [reports]
    if not isinstance(reports, list):
        return []
    allowed = {
        "blocked-uri",
        "document-uri",
        "effective-directive",
        "line-number",
        "source-file",
        "violated-directive",
    }
    items: list[dict[str, object]] = []
    for report in reports[:20]:
        if not isinstance(report, dict):
            continue
        if isinstance(report.get("body"), dict):
            report = report["body"]
        aliases = {
            "blockedURL": "blocked-uri", "documentURL": "document-uri",
            "effectiveDirective": "effective-directive", "lineNumber": "line-number",
            "sourceFile": "source-file", "violatedDirective": "violated-directive",
        }
        report = {aliases.get(key, key): value for key, value in report.items()}
        cleaned: dict[str, object] = {}
        for key in allowed:
            if key not in report:
                continue
            value = report[key]
            if isinstance(value, str):
                if key in {"blocked-uri", "document-uri", "source-file"}:
                    try:
                        parsed = urlsplit(value)
                    except ValueError:
                        continue
                    if parsed.scheme in {"http", "https"} and parsed.hostname:
                        # Queries/fragments/userinfo may include private search
                        # text, OAuth codes or credentials. Retain only the
                        # origin and a known application path, not user IDs.
                        path = parsed.path if parsed.path in {"/admin", "/user", "/user/settings"} else "/"
                        cleaned[key] = f"{parsed.scheme}://{parsed.hostname}{path}"[:300]
                    elif value in {"inline", "eval", "self", "none"}:
                        cleaned[key] = value
                    elif parsed.scheme in {"data", "blob"}:
                        cleaned[key] = parsed.scheme
                elif re.fullmatch(r"[a-z-]{1,48}", value):
                    cleaned[key] = value
            elif isinstance(value, int) and not isinstance(value, bool) and key == "line-number" and 0 <= value <= 1_000_000:
                cleaned[key] = value
        if cleaned:
            items.append(cleaned)
    return items


@app.exception_handler(HTTPException)
async def redact_http_exception(_request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": _redact_http_detail(exc.detail)},
        headers=exc.headers,
    )


@app.post("/admin/api/security/csp-report", include_in_schema=False)
async def csp_report(request: Request) -> Response:
    """Receive bounded report-only CSP violations without requiring a session."""

    raw = await _read_bounded_request_body(request, 64_000)
    if raw is None:
        return Response(status_code=413)
    if not raw:
        return Response(status_code=204)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return Response(status_code=400)
    items = _csp_report_items(payload)
    if items and _csp_log_rate_limiter.allow("csp-log"):
        logger.info("csp_report_only_violation count=%d reports=%s", len(items), items)
    return Response(status_code=204)


@app.post("/admin/api/security/client-error", include_in_schema=False)
async def client_error_report(
    request: Request,
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> Response:
    """Record a bounded, authenticated browser error signal.

    The browser deliberately sends only a coarse kind and the active route;
    stack traces and exception text can contain customer content and must not
    be collected in access or application logs.  This replaces the previous
    ``/health?client_error=...`` beacon, which polluted health telemetry.
    """

    # Apply the per-session ceiling before the database-backed session lookup
    # so a noisy client cannot turn its own error beacon into an unbounded DB
    # workload. Missing/invalid sessions still receive the normal auth error.
    if not token:
        await current_admin(token)
        return Response(status_code=401)
    if not _client_error_rate_limiter.allow(token):
        return Response(status_code=429, headers={"Retry-After": "60"})
    await current_admin(token)
    raw = await _read_bounded_request_body(request, 1_024)
    if raw is None:
        return Response(status_code=413)
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return Response(status_code=400)
    if not isinstance(payload, dict):
        return Response(status_code=400)
    kind = str(payload.get("kind") or "unknown")[:32]
    if kind not in {"window", "promise", "action", "unknown"}:
        kind = "unknown"
    # Browser context is useful for triage, but never trust arbitrary text from
    # the client: it could contain user content, control characters or a
    # username. Restrict it to the same low-risk token alphabet as actions.
    view = _telemetry_enum(payload.get("view"), _TELEMETRY_VIEWS)
    action = _telemetry_enum(payload.get("action"), _TELEMETRY_ACTIONS) if kind == "action" else ""
    phase = _telemetry_enum(payload.get("phase"), _TELEMETRY_PHASES) if kind == "action" else ""
    outcome = _telemetry_enum(payload.get("outcome"), _TELEMETRY_OUTCOMES) if kind == "action" else ""
    route = _telemetry_route(payload.get("route")) if kind == "action" else ""
    status = payload.get("status") if kind == "action" else None
    duration = payload.get("duration_ms") if kind == "action" else None
    if type(status) is not int or status < 0 or status > 999:
        status = 0
    if type(duration) is not int or duration < 0 or duration > 120_000:
        duration = 0
    # This is client-side telemetry rather than a server fault.  Keep it out of
    # the warning stream so expected browser reports do not mask real incidents.
    if kind == "action":
        logger.info(
            "authenticated_client_error kind=action view=%s action=%s phase=%s outcome=%s route=%s status=%d duration_ms=%d",
            view,
            action,
            phase,
            outcome,
            route,
            status,
            duration,
        )
    else:
        logger.info("authenticated_client_error kind=%s view=%s", kind, view)
    return Response(status_code=204)


from app.security_controls import USER_CSRF_COOKIE, request_activity, is_trusted_proxy
from app.admin import canonical_login_identity
from app.security_events import record_security_event, client_hash

@app.middleware("http")
async def private_indexing_headers(request: Request, call_next):
    """Keep the control plane private and reject cross-origin mutations."""
    mutating = request.method in {"POST", "PUT", "PATCH", "DELETE"}
    content_length = request.headers.get("content-length", "").strip()
    if content_length:
        try:
            if int(content_length) > settings.max_request_body_bytes:
                return JSONResponse(status_code=413, content={"detail": "request body too large"})
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "invalid content length"})

    def trusted_proxy() -> bool:
        return is_trusted_proxy(request.client.host if request.client else "", settings)

    def forwarded_value(name: str) -> str:
        return request.headers.get(name, "").split(",", 1)[0].strip()

    def allowed_origins() -> set[str]:
        # The direct host is useful for local/test traffic. Public production
        # origins come from the configured host, not from arbitrary headers.
        origins = {f"{request.url.scheme}://{request.url.netloc}".rstrip("/")}
        domains = [settings.domain, settings.legacy_domain]
        for domain in domains:
            if domain:
                origins.add(f"https://{domain}".rstrip("/"))
                if settings.environment.strip().lower() != "production":
                    origins.add(f"http://{domain}".rstrip("/"))
        # Caddy is on a private Docker network. Only then is its forwarded
        # public host/protocol trusted; a direct client cannot spoof them.
        if trusted_proxy():
            proto = forwarded_value("x-forwarded-proto") or request.url.scheme
            host = forwarded_value("x-forwarded-host") or request.headers.get("host", request.url.netloc)
            if proto in {"http", "https"} and host:
                origins.add(f"{proto}://{host}".rstrip("/"))
        return origins

    # The control plane uses cookie authentication. Origin validation blocks
    # cross-site requests when browsers send Origin; the double-submit token
    # below closes the common gap where Origin is absent.
    if mutating:
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse(status_code=403, content={"detail": "cross-origin request blocked"})
        origin = request.headers.get("origin", "").strip()
        if origin:
            parsed_origin = urlsplit(origin)
            normalized_origin = origin.rstrip("/")
            if (
                parsed_origin.scheme not in {"http", "https"}
                or parsed_origin.username
                or parsed_origin.password
                or parsed_origin.path not in {"", "/"}
                or normalized_origin not in allowed_origins()
            ):
                return JSONResponse(status_code=403, content={"detail": "cross-origin request blocked"})
        # Any browser request that carries the admin session must also carry
        # the readable double-submit token. This covers operational,
        # publication and Bee CFO mutations in addition to /admin/api/*.
        if (
            request.url.path not in {"/admin/api/login", "/admin/api/security/csp-report"}
            and not request.url.path.startswith("/user/api/")
            and not request.url.path.startswith("/report/api/")
            and request.cookies.get(ADMIN_SESSION_COOKIE)
        ):
            if not csrf_token_matches(
                request.cookies.get(CSRF_COOKIE),
                request.headers.get("x-csrf-token"),
                request.cookies.get(ADMIN_SESSION_COOKIE),
                settings,
            ):
                await record_security_event("request.csrf_denied", severity="warning")
                return JSONResponse(status_code=403, content={"detail": "csrf validation failed"})
    if mutating and request.url.path.startswith("/user/api/") and request.url.path != "/user/api/login" and request.cookies.get("research_bee_user_session"):
        if not csrf_token_matches(request.cookies.get(USER_CSRF_COOKIE), request.headers.get("x-csrf-token"), request.cookies.get("research_bee_user_session"), settings):
            await record_security_event("reader.csrf_denied", severity="warning")
            return JSONResponse(status_code=403, content={"detail": "csrf validation failed"})
    spec = portal_spec("report")
    if mutating and request.url.path.startswith("/report/api/") and request.url.path != "/report/api/login" and request.cookies.get(spec.session):
        if not csrf_token_matches(request.cookies.get(spec.csrf), request.headers.get("x-csrf-token"), request.cookies.get(spec.session), settings):
            return JSONResponse(status_code=403, content={"detail": "csrf validation failed"})
    activity_token = request_activity.set(mutating or request.headers.get("x-user-activity") == "1")
    try:
        response = await call_next(request)
    finally:
        request_activity.reset(activity_token)
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    if request.url.path.startswith("/report"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    response.headers["X-DNS-Prefetch-Control"] = "off"
    response.headers["Origin-Agent-Cluster"] = "?1"
    nonce = getattr(request.state, "csp_nonce", "")
    script_source = f"'self' 'nonce-{nonce}'" if nonce else "'self'"
    # Fonts are packaged with the application.  Keeping the stylesheet and
    # font directives self-only avoids a third-party render dependency and
    # makes the strict CSP reflect what the UI actually loads.
    style_source = f"'self' 'nonce-{nonce}'" if nonce else "'self'"
    policy_base = (
        f"default-src 'self'; script-src {script_source}; "
        f"style-src {style_source}; font-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )
    # Compatibility mode remains an explicit emergency rollback only. Strict
    # CSP is the default and never includes either unsafe-inline exception.
    compatibility_policy = (
        f"default-src 'self'; script-src {script_source}; script-src-attr 'unsafe-inline'; "
        f"style-src {style_source}; style-src-attr 'unsafe-inline'; "
        "font-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )
    response.headers["Content-Security-Policy"] = policy_base if settings.csp_strict else compatibility_policy
    if settings.csp_report_only:
        response.headers["Content-Security-Policy-Report-Only"] = (
            f"{policy_base}; report-uri {settings.csp_report_uri}"
        )
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    if request.url.path.startswith("/admin") or request.url.path.startswith("/bee-cfo") or request.url.path not in {
        "/health",
        "/robots.txt",
        "/favicon.ico",
        "/favicon.svg",
    } and not request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "no-store"
    forwarded_proto = forwarded_value("x-forwarded-proto") if trusted_proxy() else ""
    if request.url.scheme == "https" or forwarded_proto == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


class IngestionRequest(BaseModel):
    source_keys: list[str] | None = Field(default=None, max_length=20)
    force: bool = False


class PipelineRequest(BaseModel):
    source_keys: list[str] | None = Field(default=None, max_length=20)
    force_ingestion: bool = False
    publish: bool | None = None
    max_candidates: int | None = Field(default=None, ge=1, le=1000)
    idempotency_key: str | None = Field(default=None, max_length=128)
    assistant_id: uuid.UUID | None = None


class FeedbackRequest(BaseModel):
    analysis_id: uuid.UUID
    # Optional and informational: it must equal the signed-in username.
    actor_key: str | None = Field(default=None, max_length=128)
    value: str
    note: str | None = Field(default=None, max_length=1000)


class InsightTranslationRequest(BaseModel):
    analysis_id: uuid.UUID
    target_language: str = Field(default="fa", pattern="^(fa|en)$")


class SchedulerSettingsRequest(BaseModel):
    schedule_times: list[str] | None = Field(default=None, max_length=24)
    schedule_slots: list[dict[str, object]] | None = Field(default=None, max_length=168)


async def check_redis() -> None:
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        if not await client.ping():
            raise RuntimeError("Redis ping returned false")
    finally:
        await client.aclose()


async def require_workspace_scope(
    token: str | None,
    assistant_id: uuid.UUID | None,
    *,
    write: bool = False,
) -> None:
    """Protect backoffice data routes and enforce per-project membership."""
    user = await current_admin(token)
    if assistant_id is None:
        if not is_global_admin(user):
            raise HTTPException(status_code=403, detail="assistant_id is required")
        return
    await _require_assistant_access(assistant_id, user, write=write)


@app.get("/health")
async def health() -> JSONResponse:
    checks = await asyncio.gather(
        check_database(),
        check_redis(),
        return_exceptions=True,
    )
    names = ("postgres", "redis")
    dependencies = {
        name: "healthy" if not isinstance(result, Exception) else "unhealthy"
        for name, result in zip(names, checks, strict=True)
    }
    healthy = all(value == "healthy" for value in dependencies.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "healthy" if healthy else "degraded",
            "service": "market-intelligence",
            "version": settings.version,
            "dependencies": dependencies,
            # Liveness remains cheap and stable for Docker.  Consumers that
            # need to gate traffic must use /ready, which also checks the
            # process-local scheduler/poller state.
            "readiness_endpoint": "/ready",
        },
    )


@app.get("/ready")
async def ready() -> JSONResponse:
    """Report whether the service is ready to receive production traffic.

    Unlike /health this endpoint includes the scheduler and Telegram poller
    startup/heartbeat signals.  It intentionally does not perform a network
    call to Telegram, so frequent probes cannot consume Telegram rate limits.
    """
    checks = await asyncio.gather(
        check_database(),
        check_redis(),
        return_exceptions=True,
    )
    names = ("postgres", "redis")
    dependencies = {
        name: "healthy" if not isinstance(result, Exception) else "unhealthy"
        for name, result in zip(names, checks, strict=True)
    }
    runtime = runtime_readiness(settings)
    ready_state = all(value == "healthy" for value in dependencies.values()) and bool(runtime["ready"])
    return JSONResponse(
        status_code=200 if ready_state else 503,
        content={
            "status": "ready" if ready_state else "not_ready",
            "service": "market-intelligence",
            "version": settings.version,
            "dependencies": dependencies,
            "runtime": runtime,
        },
    )


from app.contenter import router as contenter_router
app.include_router(contenter_router)
from app.research_context import router as research_context_router
app.include_router(research_context_router)


@app.get("/robots.txt", include_in_schema=False)
async def robots_txt() -> PlainTextResponse:
    """Explicitly disallow every crawler path for the private backoffice."""
    return PlainTextResponse(
        "User-agent: *\nDisallow: /\n",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/", include_in_schema=False)
async def root_redirect() -> RedirectResponse:
    """Keep the service root useful for health probes and human visitors."""
    return RedirectResponse(url="/admin", status_code=307)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    """Serve the Bee mark as the browser favicon."""
    return FileResponse(_ADMIN_ASSETS_DIR / "bee.svg", media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/favicon.svg", include_in_schema=False)
async def favicon_svg() -> FileResponse:
    """SVG favicon endpoint used by the admin document."""
    return FileResponse(_ADMIN_ASSETS_DIR / "bee.svg", media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/assets/{asset_name}", include_in_schema=False)
async def admin_asset(asset_name: str) -> FileResponse:
    """Serve only the explicitly allow-listed admin branding assets."""
    media_type = _ADMIN_ASSETS.get(asset_name)
    if media_type is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(_ADMIN_ASSETS_DIR / asset_name, media_type=media_type, headers={"Cache-Control": "public, max-age=86400"})


@app.get("/assets/ui/{asset_name}", include_in_schema=False)
async def trusted_ui_asset(asset_name: str) -> Response:
    asset = UI_ASSETS.get(asset_name)
    if asset is None:
        raise HTTPException(404, "Asset not found")
    return Response(asset[0], media_type=asset[1], headers={
        "Cache-Control": "public, max-age=31536000, immutable",
        "X-Content-Type-Options": "nosniff",
    })


@app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def admin_ui(request: Request) -> HTMLResponse:
    # ADMIN_HTML is a trusted static template. Nonces are injected only into
    # these known script/style tags; dynamic preview content is sanitized in
    # the browser and never receives this nonce.
    nonce = secrets.token_urlsafe(24)
    request.state.csp_nonce = nonce
    body = _inject_inline_nonce(_login_document(ADMIN_HTML, "admin"), nonce)
    return HTMLResponse(body, headers={"Cache-Control": "no-store"})


@app.get("/admin/login-up", response_class=HTMLResponse, include_in_schema=False)
async def admin_password_login_ui(request: Request) -> HTMLResponse:
    """Unlinked page that also offers username/password sign-in.

    Hiding the address is not a security boundary: the password API stays
    rate limited and is protected exactly like the Google flow.
    """
    nonce = secrets.token_urlsafe(24)
    request.state.csp_nonce = nonce
    body = _login_document(ADMIN_HTML, "admin", password=True)
    return HTMLResponse(_inject_inline_nonce(body, nonce), headers={"Cache-Control": "no-store"})


@app.get("/user/login-up", response_class=HTMLResponse, include_in_schema=False)
async def user_password_login_ui(request: Request) -> HTMLResponse:
    nonce = secrets.token_urlsafe(24)
    request.state.csp_nonce = nonce
    body = _login_document(USER_HTML, "user", password=True)
    return HTMLResponse(
        _inject_inline_nonce(body, nonce),
        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow, noarchive, nosnippet"},
    )


@app.get("/user/news/{publication_id}", response_class=HTMLResponse, include_in_schema=False)
@app.get("/user", response_class=HTMLResponse, include_in_schema=False)
async def user_ui(request: Request) -> HTMLResponse:
    """Serve the read-only published-news portal."""
    nonce = secrets.token_urlsafe(24)
    request.state.csp_nonce = nonce
    body = _inject_inline_nonce(_login_document(USER_HTML, "user"), nonce)
    return HTMLResponse(
        body,
        headers={
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex, nofollow, noarchive, nosnippet",
        },
    )


from app.news_chat.api import router as news_chat_router
app.include_router(news_chat_router)
from app.report_portal.api import router as report_router
app.include_router(report_router)


@app.get("/report", response_class=HTMLResponse, include_in_schema=False)
@app.get("/report/login-up", response_class=HTMLResponse, include_in_schema=False)
async def report_ui(request: Request):
    nonce = secrets.token_urlsafe(24)
    request.state.csp_nonce = nonce
    return HTMLResponse(_inject_inline_nonce(_login_document(REPORT_HTML, "report", password=request.url.path.endswith("login-up")), nonce),
        headers={"Cache-Control": "no-store"})


@app.post("/report/api/login")
async def report_login(payload: LoginRequest, response: Response, http_request: Request):
    from app.report_portal.auth import login
    return await _rate_limited_password_login(payload, response, http_request, login)


@app.get("/user/api/publications/{publication_id}/detail")
async def user_news_detail(publication_id: uuid.UUID, token: str | None = Cookie(default=None, alias=USER_SESSION_COOKIE)):
    from app.news_chat.service import publication
    from app.models import ArticleAnalysis, NormalizedArticle, SourceItem, Source
    from sqlalchemy import select
    user = await current_reader(token)
    async with SessionLocal() as session:
        item = await publication(session, publication_id, user)
        source_name = await session.scalar(select(Source.name).join(SourceItem, SourceItem.source_id == Source.id)
            .join(NormalizedArticle, NormalizedArticle.source_item_id == SourceItem.id)
            .join(ArticleAnalysis, ArticleAnalysis.article_id == NormalizedArticle.id)
            .where(ArticleAnalysis.id == item.analysis_id, ArticleAnalysis.assistant_id == item.assistant_id,
                   NormalizedArticle.assistant_id == item.assistant_id, SourceItem.assistant_id == item.assistant_id, Source.assistant_id == item.assistant_id))
        return {"id": str(item.id), "assistant_id": str(item.assistant_id), "message_text": item.message_text,
                "source_name": source_name or "",
                "published_at": item.published_at.isoformat() if item.published_at else None}


@app.get("/user/settings", response_class=HTMLResponse, include_in_schema=False)
async def user_settings_ui(request: Request) -> HTMLResponse:
    """Serve the same reader shell with its personal settings as a page."""
    nonce = secrets.token_urlsafe(24)
    request.state.csp_nonce = nonce
    body = _login_document(USER_HTML, "user").replace('<body ', '<body data-user-page="settings" ', 1)
    body = _inject_inline_nonce(body, nonce)
    return HTMLResponse(
        body,
        headers={
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex, nofollow, noarchive, nosnippet",
        },
    )


@app.post("/user/api/login")
async def user_api_login(payload: LoginRequest, response: Response, http_request: Request) -> dict[str, object]:
    # Same account directory and passwords as the back-office, so the same
    # (shared) brute-force budget must apply here.
    return await _rate_limited_password_login(payload, response, http_request, reader_login)


@app.post("/user/api/logout")
async def user_api_logout(response: Response, token: str | None = Cookie(default=None, alias=USER_SESSION_COOKIE)) -> dict[str, str]:
    return await reader_logout(response, token)


@app.get("/user/api/me")
async def user_api_me(response: Response, token: str | None = Cookie(default=None, alias=USER_SESSION_COOKIE)) -> dict[str, object]:
    user = await current_reader(token)
    if token:
        set_reader_session_cookie(response, token)
    return {"id": str(user.id), "username": user.username, "display_name": user.display_name or user.username,
            "email": user.email, "login_method": user.login_method, **user_portal_access_payload(user)}


@app.get("/user/api/assistants")
async def user_api_assistants(token: str | None = Cookie(default=None, alias=USER_SESSION_COOKIE)) -> dict[str, object]:
    return await reader_assistants(await current_reader(token))


@app.get("/user/api/preferences")
async def user_api_preferences(token: str | None = Cookie(default=None, alias=USER_SESSION_COOKIE)) -> dict[str, object]:
    return await get_reader_preferences(await current_reader(token))


@app.patch("/user/api/preferences")
async def user_api_update_preferences(
    payload: ReaderPreferencesUpdate,
    token: str | None = Cookie(default=None, alias=USER_SESSION_COOKIE),
) -> dict[str, object]:
    return await update_reader_preferences(payload, await current_reader(token))


@app.get("/user/api/assistants/{assistant_id}/reading-state")
async def user_api_reading_state(
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias=USER_SESSION_COOKIE),
) -> dict[str, object]:
    """Return private highlights, notes, tags and read-later state for a reader."""

    return await list_reader_annotations(assistant_id, await current_reader(token))


@app.put("/user/api/publications/{publication_id}/reading-state")
async def user_api_update_reading_state(
    publication_id: uuid.UUID,
    payload: ReaderAnnotationUpdate,
    token: str | None = Cookie(default=None, alias=USER_SESSION_COOKIE),
) -> dict[str, object]:
    """Update one reader-owned deep-reading state; publication content is immutable."""

    return await update_reader_annotation(publication_id, payload, await current_reader(token))


@app.post("/user/api/publications/{publication_id}/feedback")
async def user_api_feedback(
    publication_id: uuid.UUID,
    payload: ReaderFeedbackRequest,
    token: str | None = Cookie(default=None, alias=USER_SESSION_COOKIE),
) -> dict[str, object]:
    """Record a feedback signal when the account has the explicit grant."""

    return await record_reader_feedback(publication_id, payload, await current_reader(token))


@app.get("/user/api/assistants/{assistant_id}/publications")
async def user_api_publications(
    assistant_id: uuid.UUID,
    limit: int = Query(default=200, ge=1, le=200),
    query: str | None = Query(default=None, max_length=200),
    touch: bool = Query(default=True),
    token: str | None = Cookie(default=None, alias=USER_SESSION_COOKIE),
) -> dict[str, object]:
    # Notification polling validates the session without renewing its idle
    # deadline. Interactive requests keep the normal sliding timeout.
    user = await current_reader(token, touch=touch)
    # Reuse the same project membership boundary as the back-office, while
    # exposing only the final Telegram-ready message and no settings.
    available = await reader_assistants(user)
    if not _reader_assistant_is_accessible(available, assistant_id):
        raise HTTPException(status_code=403, detail="workspace access denied")
    rows = await list_publications(status="published", limit=limit, assistant_id=assistant_id, query=query)
    return {
        "count": len(rows),
        "publications": [
            {
                "id": row["id"],
                "message_text": row["message_text"],
                "source_name": row["source_name"],
                "created_at": row["created_at"],
                "published_at": row["published_at"],
                "article_published_at": row["article_published_at"],
                "relevance_score": row["relevance_score"],
            }
            for row in rows
        ],
    }


def _login_client_address(request: Request) -> str:
    """Use X-Forwarded-For only when the immediate peer is a private proxy."""
    peer = (request.client.host if request.client else "unknown") or "unknown"
    try:
        peer_address = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if is_trusted_proxy(peer, settings):
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        try:
            candidate = ipaddress.ip_address(forwarded)
        except ValueError:
            return peer
        if candidate.is_global:
            return str(candidate)
    return peer


async def _rate_limited_password_login(payload: LoginRequest, response: Response, http_request: Request, login_fn) -> dict[str, object]:
    """Apply the shared per-account and per-client budget to a password login."""
    username = payload.username.strip().lower()
    if "@" in username:
        username = google_auth.normalize_email(username)
    username = await canonical_login_identity(username)
    client_address = _login_client_address(http_request)
    if await login_attempts_exceeded(settings, username, client_address):
        await record_security_event("login.rate_limited", severity="warning", details={"client_hash": client_hash(client_address)})
        raise HTTPException(
            status_code=429,
            detail="too many login attempts",
            headers={"Retry-After": str(settings.login_window_seconds)},
        )
    try:
        result = await login_fn(payload, response)
    except HTTPException as exc:
        if exc.status_code == 401:
            await record_security_event("login.failed", severity="warning", details={"client_hash": client_hash(client_address)})
            await record_login_failure(settings, username, client_address)
        raise
    await clear_login_failures(settings, username, client_address)
    return result


@app.post("/admin/api/login")
async def admin_api_login(payload: LoginRequest, response: Response, http_request: Request) -> dict[str, object]:
    return await _rate_limited_password_login(payload, response, http_request, admin_login)


@app.get("/auth/providers", include_in_schema=False)
async def auth_providers() -> dict[str, bool]:
    """Public: tells the login pages whether to show the Google button."""
    return {"google": settings.google_login_ready}


def _google_login_error(portal: str, code: str) -> RedirectResponse:
    target = portal_spec(portal).path
    response = RedirectResponse(url=f"{target}?login_error={code}", status_code=302)
    response.delete_cookie(google_auth.FLOW_COOKIE, path=google_auth.FLOW_COOKIE_PATH)
    return response


@app.get("/auth/google/start", include_in_schema=False)
async def google_login_start(request: Request, portal: str = Query(default="admin", pattern="^(admin|user|report)$"), redirectTo: str | None = Query(default=None, max_length=1024)) -> RedirectResponse:
    """Browser navigation target: redirect to Google's account chooser."""
    # The flow cookie must be set on the host Google redirects back to.
    # Start on that canonical host (e.g. from the legacy domain) first.
    callback = urlsplit(settings.google_redirect_uri or "")
    if callback.hostname and (request.url.hostname or "").lower() != callback.hostname.lower():
        query = {"portal": portal}
        if redirectTo:
            query["redirectTo"] = google_auth.safe_redirect(portal, redirectTo)
        return RedirectResponse(url=f"{callback.scheme}://{callback.netloc}/auth/google/start?{urlencode(query)}", status_code=302)
    try:
        if await login_ip_attempts_exceeded(settings, _login_client_address(request)):
            raise google_auth.GoogleAuthError("rate_limited")
        url, flow_cookie = google_auth.start_flow(settings, portal, redirectTo)
    except google_auth.GoogleAuthError as exc:
        return _google_login_error(portal, exc.code)
    except HTTPException:
        return _google_login_error(portal, "failed")
    response = RedirectResponse(url=url, status_code=302)
    # SameSite=Lax: Google's redirect back is a cross-site top-level GET.
    response.set_cookie(
        google_auth.FLOW_COOKIE,
        flow_cookie,
        max_age=google_auth.FLOW_TTL_SECONDS,
        httponly=True,
        secure=settings.admin_cookie_secure or settings.environment.strip().lower() == "production",
        samesite="lax",
        path=google_auth.FLOW_COOKIE_PATH,
    )
    return response


@app.get("/auth/google/callback", include_in_schema=False)
async def google_login_callback(
    request: Request,
    code: str | None = Query(default=None, max_length=2048),
    state: str | None = Query(default=None, max_length=256),
    error: str | None = Query(default=None, max_length=256),
) -> RedirectResponse:
    """Google redirects here; success sets the portal session and returns home."""
    portal = "admin"
    client_address = _login_client_address(request)
    try:
        flow = google_auth.read_flow(settings, request.cookies.get(google_auth.FLOW_COOKIE))
        portal = google_auth.flow_portal(flow)
        if await login_ip_attempts_exceeded(settings, client_address):
            raise google_auth.GoogleAuthError("rate_limited")
        identity = await google_auth.finish_flow(settings, code=code, state=state, error=error, flow=flow)
        raw, _user = await login_with_google(identity, portal=portal)
    except google_auth.GoogleAuthError as exc:
        if exc.code in {"not_allowed", "not_gmail", "inactive", "failed"}:
            await record_ip_login_failure(settings, client_address)
        if exc.code == "failed":
            logger.warning("google sign-in failed: %s", redact_sensitive_text(str(exc), limit=300))
        await accounts.admin._audit(None, "auth.google.failed", details={"portal": portal, "reason": exc.code})
        return _google_login_error(portal, exc.code)
    except HTTPException:
        return _google_login_error(portal, "failed")
    response = RedirectResponse(url=google_auth.safe_redirect(portal, flow.get("redirect_to")), status_code=302)
    response.delete_cookie(google_auth.FLOW_COOKIE, path=google_auth.FLOW_COOKIE_PATH)
    if portal == "user":
        set_reader_session_cookie(response, raw)
    elif portal == "report":
        from app.report_portal.auth import cookies as report_cookies
        report_cookies(response, raw)
    else:
        set_admin_session_cookies(response, raw)
    return response


@app.get("/admin/api/owner/google-access")
async def admin_api_google_access(token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await list_google_access(await current_admin(token))


@app.post("/admin/api/owner/google-access")
async def admin_api_grant_google_access(payload: GoogleAccessGrant, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await grant_google_access(payload, await current_admin(token))


@app.patch("/admin/api/owner/google-access/{user_id}")
async def admin_api_update_google_access(user_id: uuid.UUID, payload: GoogleAccessUpdate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await update_google_access(user_id, payload, await current_admin(token))


@app.delete("/admin/api/owner/google-access/{user_id}")
async def admin_api_revoke_google_access(user_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await revoke_google_access(user_id, await current_admin(token))


@app.post("/admin/api/logout")
async def admin_api_logout(response: Response, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, str]:
    result = await admin_logout(response, token)
    # Do not delete the independent User portal's cookie on Admin logout.
    response.headers["Clear-Site-Data"] = '"cache"'
    return result


@app.get("/admin/api/me")
async def admin_api_me(response: Response, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    if token:
        set_admin_session_cookies(response, token)
    return {"id": str(user.id), "username": user.username, "role": effective_user_role(user), "stored_role": user.role, "is_owner": is_owner(user), "login_method": user.login_method, "email": user.email, "display_name": user.display_name or user.username, "has_password": bool(user.password_hash), "avatar_url": (user.preferences or {}).get("avatar_url") or default_avatar_data(user.id), "mfa_required": False, **user_portal_access_payload(user)}


@app.get("/admin/api/accounts")
async def account_list(q: str = Query(default="", max_length=120), page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100), token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict:
    return await accounts.list_accounts(await current_admin(token), q=q, page=page, page_size=page_size)


@app.post("/admin/api/accounts")
async def account_create(payload: accounts.AccountCreate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict:
    return await accounts.create_account(payload, await current_admin(token))


@app.patch("/admin/api/accounts/{uid}")
async def account_update(uid: uuid.UUID, payload: accounts.AccountUpdate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict:
    return await accounts.update_account(uid, payload, await current_admin(token))


@app.delete("/admin/api/accounts/{uid}")
async def account_remove(uid: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict:
    return await accounts.remove_account(uid, await current_admin(token))


@app.get("/admin/api/account/preferences")
async def admin_api_account_preferences(token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await get_account_preferences(user)


@app.put("/admin/api/account/preferences")
async def admin_api_update_account_preferences(payload: AccountPreferencesUpdate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await update_account_preferences(payload, user)


@app.get("/admin/api/support/tickets")
async def admin_api_support_tickets(
    status: str | None = Query(default=None, max_length=24),
    priority: str | None = Query(default=None, max_length=16),
    search: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=100, ge=1, le=200),
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    return await list_support_tickets(
        await current_admin(token), status=status, priority=priority, search=search, limit=limit
    )


@app.post("/admin/api/support/tickets")
async def admin_api_create_support_ticket(payload: SupportTicketCreate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await create_support_ticket(payload, await current_admin(token))


@app.patch("/admin/api/support/tickets/{ticket_id}")
async def admin_api_update_support_ticket(ticket_id: uuid.UUID, payload: SupportTicketUpdate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await update_support_ticket(ticket_id, payload, await current_admin(token))


@app.post("/admin/api/support/tickets/{ticket_id}/messages")
async def admin_api_add_support_ticket_message(ticket_id: uuid.UUID, payload: SupportTicketMessageCreate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await add_support_ticket_message(ticket_id, payload, await current_admin(token))


@app.put("/admin/api/password")
async def admin_api_change_password(payload: ChangePasswordRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, str]:
    user = await current_admin(token)
    return await change_password(user, payload)


@app.get("/admin/api/assistants")
async def admin_api_assistants(token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await assistants(user)


@app.post("/admin/api/assistants")
async def admin_api_create_assistant(payload: AssistantRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    if not is_global_admin(user):
        raise HTTPException(status_code=403, detail="admin role required")
    return await create_assistant(payload, user)


@app.post("/admin/api/assistants/draft")
async def admin_api_draft_assistant(payload: AssistantDraftRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    """Owner shortcut: suggest a complete editable assistant configuration."""
    return await draft_assistant(payload, await current_admin(token))


@app.patch("/admin/api/assistants/{assistant_id}")
async def admin_api_update_assistant(assistant_id: uuid.UUID, payload: AssistantUpdate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await update_assistant(assistant_id, payload, user)


@app.delete("/admin/api/assistants/{assistant_id}")
async def admin_api_delete_assistant(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, str]:
    user = await current_admin(token)
    return await delete_assistant(assistant_id, user)

@app.post("/admin/api/assistants/{assistant_id}/restore")
async def admin_api_restore_assistant(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, str]:
    return await restore_assistant(assistant_id, await current_admin(token))

@app.delete("/admin/api/assistants/{assistant_id}/permanent")
async def admin_api_permanent_delete_assistant(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, str]:
    return await permanently_delete_assistant(assistant_id, await current_admin(token))


@app.get("/admin/api/assistants/{assistant_id}/telegram")
async def admin_api_get_assistant_telegram(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await get_assistant_telegram(assistant_id, user)


@app.get("/admin/api/assistants/{assistant_id}/readiness")
async def admin_api_assistant_readiness(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await assistant_readiness(assistant_id, user)


@app.put("/admin/api/assistants/{assistant_id}/telegram")
async def admin_api_update_assistant_telegram(assistant_id: uuid.UUID, payload: TelegramSettingsUpdate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await update_assistant_telegram(assistant_id, payload, user)


@app.get("/admin/api/assistants/{assistant_id}/templates")
async def admin_api_assistant_templates(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await get_assistant_templates(assistant_id, user)


@app.put("/admin/api/assistants/{assistant_id}/templates/{channel}")
async def admin_api_update_assistant_template(assistant_id: uuid.UUID, channel: str, payload: TemplateBlocksRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await update_assistant_template(assistant_id, channel, payload, user)


@app.post("/admin/api/assistants/{assistant_id}/templates/{channel}/preview")
async def admin_api_preview_assistant_template(assistant_id: uuid.UUID, channel: str, payload: TemplateBlocksRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await preview_assistant_template(assistant_id, channel, payload, user)


@app.post("/admin/api/assistants/{assistant_id}/clone")
async def admin_api_clone_assistant(assistant_id: uuid.UUID, payload: AssistantCloneRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    if not is_global_admin(user):
        raise HTTPException(status_code=403, detail="admin role required")
    return await clone_assistant(assistant_id, payload, user)


@app.post("/admin/api/assistants/{assistant_id}/activate")
async def admin_api_activate_assistant(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await activate_assistant(assistant_id, user)


@app.get("/admin/api/assistants/{assistant_id}/members")
async def admin_api_assistant_members(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await list_assistant_members(assistant_id, user)


@app.put("/admin/api/assistants/{assistant_id}/members")
async def admin_api_assign_assistant_member(assistant_id: uuid.UUID, payload: AssistantMemberRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await assign_assistant_member(assistant_id, payload, user)


@app.delete("/admin/api/assistants/{assistant_id}/members/{user_id}")
async def admin_api_remove_assistant_member(assistant_id: uuid.UUID, user_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, str]:
    user = await current_admin(token)
    return await remove_assistant_member(assistant_id, user_id, user)


@app.patch("/admin/api/sources/{source_id}")
async def admin_api_update_source(source_id: uuid.UUID, payload: SourceUpdate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    require_editor_role(user)
    return await update_source(source_id, payload, user)


@app.post("/admin/api/assistants/{assistant_id}/sources")
async def admin_api_create_source(assistant_id: uuid.UUID, payload: SourceCreate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    require_editor_role(user)
    return await create_source(assistant_id, payload, user)


@app.post("/admin/api/assistants/{assistant_id}/public-social-sources")
async def admin_api_create_public_social_source(
    assistant_id: uuid.UUID,
    payload: PublicSocialSourceCreate,
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    """Create a public social source from a platform handle in the back-office."""
    user = await current_admin(token)
    require_editor_role(user)
    try:
        return await create_public_social_source(assistant_id, payload, user)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/admin/api/assistants/{assistant_id}/sources/draft")
async def admin_api_draft_source(assistant_id: uuid.UUID, payload: CatalogDraftRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    require_editor_role(user)
    return await draft_source(assistant_id, payload, user)


@app.post("/admin/api/assistants/{assistant_id}/sources/{source_id}/probe")
async def admin_api_probe_source(
    assistant_id: uuid.UUID,
    source_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    """Run a bounded source check without creating a publication."""
    await require_workspace_scope(token, assistant_id, write=True)
    try:
        return await run_source_probe(source_id, assistant_id=assistant_id, limit=20)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("source probe failed")
        raise HTTPException(status_code=502, detail="source probe failed") from exc


@app.get("/admin/api/assistants/{assistant_id}/source-suggestions")
async def admin_api_source_suggestions(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await list_source_suggestions(assistant_id, user)


@app.post("/admin/api/assistants/{assistant_id}/source-suggestions")
async def admin_api_create_source_suggestion(assistant_id: uuid.UUID, payload: CatalogDraftRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await create_source_suggestion(assistant_id, payload, user)


@app.post("/admin/api/assistants/{assistant_id}/source-suggestions/{suggestion_id}/approve")
async def admin_api_approve_source_suggestion(assistant_id: uuid.UUID, suggestion_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await decide_source_suggestion(assistant_id, suggestion_id, approve=True, user=user)


@app.post("/admin/api/assistants/{assistant_id}/source-suggestions/{suggestion_id}/reject")
async def admin_api_reject_source_suggestion(assistant_id: uuid.UUID, suggestion_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await decide_source_suggestion(assistant_id, suggestion_id, approve=False, user=user)


@app.delete("/admin/api/sources/{source_id}")
async def admin_api_delete_source(source_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, str]:
    user = await current_admin(token)
    require_editor_role(user)
    return await delete_source(source_id, user)


@app.post("/admin/api/sources/{source_id}/move")
async def admin_api_move_source(source_id: uuid.UUID, payload: OrderMoveRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    require_editor_role(user)
    return await move_source(source_id, payload, user)


@app.patch("/admin/api/topics/{topic_id}")
async def admin_api_update_topic(topic_id: uuid.UUID, payload: TopicUpdate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    require_editor_role(user)
    return await update_topic(topic_id, payload, user)


@app.post("/admin/api/assistants/{assistant_id}/topics")
async def admin_api_create_topic(assistant_id: uuid.UUID, payload: TopicCreate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    require_editor_role(user)
    return await create_topic(assistant_id, payload, user)


@app.post("/admin/api/assistants/{assistant_id}/topics/draft")
async def admin_api_draft_topic(assistant_id: uuid.UUID, payload: CatalogDraftRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    require_editor_role(user)
    return await draft_topic(assistant_id, payload, user)


@app.delete("/admin/api/topics/{topic_id}")
async def admin_api_delete_topic(topic_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, str]:
    user = await current_admin(token)
    require_editor_role(user)
    return await delete_topic(topic_id, user)


@app.post("/admin/api/topics/{topic_id}/move")
async def admin_api_move_topic(topic_id: uuid.UUID, payload: OrderMoveRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    require_editor_role(user)
    return await move_topic(topic_id, payload, user)


@app.get("/admin/api/topics")
async def admin_api_topics(assistant_id: uuid.UUID | None = None, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await list_topics(user, assistant_id=assistant_id)


@app.get("/admin/api/business-profile")
async def admin_api_business_profile(assistant_id: uuid.UUID | None = None, profile_id: int | None = None, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await get_business_profile(user, assistant_id=assistant_id, profile_id=profile_id)


@app.get("/admin/api/assistants/{assistant_id}/businesses")
async def admin_api_businesses(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await list_business_profiles(assistant_id, user)


@app.post("/admin/api/assistants/{assistant_id}/businesses")
async def admin_api_create_business(assistant_id: uuid.UUID, payload: BusinessProfileCreate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await create_business_profile(assistant_id, payload, user)


@app.post("/admin/api/assistants/{assistant_id}/businesses/draft")
async def admin_api_draft_business(assistant_id: uuid.UUID, payload: BusinessDraftRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    require_editor_role(user)
    return await draft_business(assistant_id, payload, user)


@app.patch("/admin/api/assistants/{assistant_id}/businesses/{profile_id}")
async def admin_api_update_business(assistant_id: uuid.UUID, profile_id: int, payload: BusinessProfileUpdate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await update_business_profile(payload, user, assistant_id=assistant_id, profile_id=profile_id)


@app.delete("/admin/api/assistants/{assistant_id}/businesses/{profile_id}")
async def admin_api_delete_business(assistant_id: uuid.UUID, profile_id: int, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await delete_business_profile(assistant_id, profile_id, user)


@app.patch("/admin/api/business-profile")
async def admin_api_update_business_profile(payload: BusinessProfileUpdate, assistant_id: uuid.UUID | None = None, profile_id: int | None = None, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    require_editor_role(user)
    return await update_business_profile(payload, user, assistant_id=assistant_id, profile_id=profile_id)


@app.get("/admin/api/assistants/{assistant_id}/business-knowledge")
async def admin_api_business_knowledge(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await get_business_knowledge(assistant_id, await current_admin(token))


@app.put("/admin/api/assistants/{assistant_id}/business-knowledge")
async def admin_api_update_business_knowledge(assistant_id: uuid.UUID, payload: BusinessKnowledgeUpdate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await update_business_knowledge(assistant_id, payload, await current_admin(token))


@app.get("/admin/api/assistants/{assistant_id}/clusters")
async def admin_api_event_clusters(assistant_id: uuid.UUID, limit: int = Query(default=50, ge=1, le=100), token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await list_event_clusters(assistant_id, await current_admin(token), limit=limit)


@app.get("/admin/api/assistants/{assistant_id}/privacy")
async def admin_api_privacy_settings(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await get_privacy_settings(assistant_id, await current_admin(token))


@app.put("/admin/api/assistants/{assistant_id}/privacy")
async def admin_api_update_privacy_settings(assistant_id: uuid.UUID, payload: PrivacySettingsUpdate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await update_privacy_settings(assistant_id, payload, await current_admin(token))


@app.get("/admin/api/assistants/{assistant_id}/privacy/export")
async def admin_api_export_assistant_data(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await export_assistant_data(assistant_id, await current_admin(token))


@app.get("/admin/api/assistants/{assistant_id}/runtime-settings")
async def admin_api_runtime_settings(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await get_assistant_runtime_settings(assistant_id, user)


@app.put("/admin/api/assistants/{assistant_id}/runtime-settings")
async def admin_api_update_runtime_settings(assistant_id: uuid.UUID, payload: AssistantRuntimeSettingsUpdate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    require_editor_role(user)
    return await update_assistant_runtime_settings(assistant_id, payload, user)


@app.post("/admin/api/assistants/{assistant_id}/runtime-settings/preview")
async def admin_api_preview_runtime_settings(assistant_id: uuid.UUID, payload: RuntimeSettingsPreviewRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    require_editor_role(user)
    return await preview_assistant_runtime_settings(assistant_id, payload, user)


@app.post("/admin/api/assistants/{assistant_id}/share-links")
async def admin_api_create_share_link(assistant_id: uuid.UUID, payload: ShareLinkCreateRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await create_share_link(assistant_id, payload, await current_admin(token))


@app.delete("/admin/api/assistants/{assistant_id}/share-links/{link_id}")
async def admin_api_revoke_share_link(assistant_id: uuid.UUID, link_id: str, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await revoke_share_link(assistant_id, link_id, await current_admin(token))


@app.get("/admin/api/assistants/{assistant_id}/limits")
async def admin_api_assistant_limits(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await get_assistant_limits(assistant_id, user)


@app.put("/admin/api/assistants/{assistant_id}/limits")
async def admin_api_update_assistant_limits(assistant_id: uuid.UUID, payload: AssistantLimitsUpdate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await update_assistant_limits(assistant_id, payload, user)


@app.get("/admin/api/notifications")
async def admin_api_notifications(token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await list_admin_notifications(user)


@app.post("/admin/api/notifications/read")
async def admin_api_notifications_read(token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await mark_admin_notifications_read(user)


@app.get("/admin/api/incidents")
async def admin_api_incidents(assistant_id: uuid.UUID | None = None, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await list_admin_incidents(await current_admin(token), assistant_id=assistant_id)


@app.post("/admin/api/incidents/{incident_id}/close")
async def admin_api_close_incident(incident_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await close_admin_incident(incident_id, await current_admin(token))


@app.get("/admin/api/assistants/{assistant_id}/news-views")
async def admin_api_news_views(assistant_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await list_news_views(assistant_id, await current_admin(token))


@app.post("/admin/api/assistants/{assistant_id}/news-views")
async def admin_api_save_news_view(assistant_id: uuid.UUID, payload: NewsViewRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await save_news_view(assistant_id, payload, await current_admin(token))


@app.delete("/admin/api/assistants/{assistant_id}/news-views/{view_id}")
async def admin_api_delete_news_view(assistant_id: uuid.UUID, view_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await delete_news_view(assistant_id, view_id, await current_admin(token))


@app.post("/admin/api/assistants/{assistant_id}/publications/bulk")
async def admin_api_bulk_publications(assistant_id: uuid.UUID, payload: PublicationBulkRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await bulk_publications(assistant_id, payload, await current_admin(token))


@app.post("/admin/api/assistants/{assistant_id}/publications/bulk/undo")
async def admin_api_undo_bulk_publications(assistant_id: uuid.UUID, payload: PublicationBulkUndoRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await undo_bulk_publications(assistant_id, payload, await current_admin(token))


@app.get("/admin/api/users")
async def admin_api_users(token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await list_admin_users(user)


@app.post("/admin/api/users")
async def admin_api_create_user(payload: AdminUserRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await create_admin_user(payload, user)


@app.patch("/admin/api/users/{user_id}")
async def admin_api_update_user(user_id: uuid.UUID, payload: AdminUserUpdate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await update_admin_user(user_id, payload, user)


@app.put("/admin/api/users/{user_id}/manage")
async def admin_api_manage_user(user_id: uuid.UUID, payload: AdminUserManageUpdate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await manage_admin_user(user_id, payload, user)


@app.put("/admin/api/users/{user_id}/user-portal-access")
async def admin_api_user_portal_access(user_id: uuid.UUID, payload: UserPortalAccessUpdate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await update_user_portal_access(user_id, payload, user)


@app.delete("/admin/api/users/{user_id}")
async def admin_api_delete_user(user_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, str]:
    user = await current_admin(token)
    return await delete_admin_user(user_id, user)


@app.put("/admin/api/users/{user_id}/password")
async def admin_api_change_user_password(user_id: uuid.UUID, payload: AdminUserPasswordUpdate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, str]:
    user = await current_admin(token)
    return await change_user_password(user_id, payload, user)


@app.get("/admin/api/sessions")
async def admin_api_sessions(token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await list_active_sessions(user, token)


# The literal route must be registered before the parameterised one;
# otherwise "others" is parsed as a session UUID and rejected with 422.
@app.delete("/admin/api/sessions/others")
async def admin_api_revoke_other_sessions(token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await revoke_other_sessions(user, token)


@app.delete("/admin/api/sessions/{session_id}")
async def admin_api_revoke_session(session_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, str]:
    user = await current_admin(token)
    return await revoke_session(session_id, user, token)


@app.get("/meta")
async def metadata(token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    # Metadata contains deployment and queue details used by the back-office;
    # it is not a public discovery endpoint.
    await current_admin(token)
    queues = get_queue_names(settings)
    whatsapp = WhatsAppClient(settings).readiness()
    return {
        "service": "market-intelligence",
        "version": settings.version,
        "source_revision": settings.build_revision,
        # Deployment tooling injects the immutable promoted digest; the
        # running process must not guess it from a mutable image tag.
        "image_digest": settings.image_digest,
        "environment": settings.environment,
        "business_name": settings.business_name,
        "database_schema": settings.database_schema,
        "redis_database": settings.redis_database,
        "queue_namespace": settings.queue_namespace,
        "queues": {
            "runs": queues.runs,
            "dead_letter": queues.dead_letter,
            "scheduler_lock": queues.scheduler_lock,
        },
        "timezone": settings.timezone,
        "schedule_times": list(settings.schedule_time_values),
        "max_items_per_run": settings.max_items_per_run,
        "publish_max_items_per_run": settings.max_items_per_run,
            "processing_max_items_per_day": settings.processing_max_items_per_day,
        "freshness_window_days": settings.freshness_window_days,
        "admin_session_idle_hours": settings.session_idle_minutes / 60,
        "session_idle_minutes": settings.session_idle_minutes,
        "session_absolute_hours": settings.session_absolute_hours,
        "account_session_ttl_days": settings.account_session_ttl_days,
        "user_session_cutoff_local": "02:00",
        "ingestion": {
            "adapters": ["rss", "html", "json", "telegram_public", "telegram_private", "instagram_public", "instagram_private", "x_public", "x_private"],
            "max_items_per_source": settings.fetch_max_items_per_source,
            "concurrency": settings.fetch_concurrency,
            "robots_default": "respect",
        },
        "pipeline": {
            "phases": [
                "MI-004 extraction",
                "MI-005 relevance-and-clustering",
                "MI-006 business-analysis",
                "MI-007 telegram",
                "MI-008 scheduler",
                "MI-009 pilot",
                "MI-010 operations",
                "MI-011 formal Telegram presentation",
            ],
            "pilot_mode": settings.pilot_mode,
            "auto_publish": settings.auto_publish,
            "scheduler_enabled": settings.scheduler_enabled,
            "relevance_threshold": settings.relevance_threshold,
            "clustering_threshold": settings.clustering_threshold,
            "model": settings.analysis_model,
            "embedding_model": settings.embedding_model,
            "daily_model_request_cap": settings.model_daily_request_cap,
            "daily_input_char_cap": settings.model_daily_input_char_cap,
            "max_candidates_per_run": settings.pipeline_max_candidates_per_run,
            "collection_frequency": "hourly",
            "publication_limit_per_slot": settings.max_items_per_run,
            "borderline_review_margin": 0.10,
            "external_analysis_approved": settings.external_analysis_approved,
        },
        "secrets_configured": {
            "openai": settings.openai_api_key is not None,
            "telegram": settings.telegram_bot_token is not None,
            "telegram_channel": settings.telegram_channel_id is not None,
            "telegram_observer_channel": settings.telegram_observer_channel_id is not None,
        },
        "whatsapp": whatsapp.safe_dict(),
    }


@app.get("/sources")
async def sources(
    assistant_id: uuid.UUID | None = None,
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    await require_workspace_scope(token, assistant_id)
    rows = await list_sources(assistant_id=assistant_id)
    return {"count": len(rows), "sources": rows}


@app.post("/ingestion/run")
async def ingestion_run(
    request: IngestionRequest,
    assistant_id: uuid.UUID | None = None,
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    await require_workspace_scope(token, assistant_id, write=True)
    if assistant_id is None:
        return await run_ingestion(request.source_keys, force=request.force)
    return await run_ingestion(request.source_keys, force=request.force, assistant_id=assistant_id)


@app.post("/sources/health-probe")
async def source_health_probe(
    assistant_id: uuid.UUID | None = None,
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    await require_workspace_scope(token, assistant_id, write=True)
    if assistant_id is None:
        return await run_degraded_source_health_probe()
    return await run_source_health_probe(assistant_id=assistant_id, force=True)


@app.post("/pipeline/run")
async def pipeline_run(request: PipelineRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    await require_workspace_scope(token, request.assistant_id, write=True)
    # Telegram delivery is an owner decision (same as /publications/{id}/publish).
    # Everyone else may collect and prepare previews; ``publish`` is forced
    # off so neither an explicit flag nor the auto-publish default applies.
    if request.publish and not is_owner(await current_admin(token)):
        raise HTTPException(status_code=403, detail="owner role required to publish")
    publish = request.publish if request.publish else False
    try:
        return await run_pipeline(
            source_keys=request.source_keys,
            force_ingestion=request.force_ingestion,
            publish=publish,
            max_candidates=request.max_candidates,
            idempotency_key=request.idempotency_key,
            assistant_id=request.assistant_id,
        )
    except Exception as exc:
        logger.exception("pipeline execution failed")
        raise HTTPException(status_code=500, detail="pipeline execution failed") from exc


@app.post("/pipeline/manual-publish")
async def pipeline_manual_publish(request: PipelineRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    """Collect, then publish exactly one fresh item immediately (owner only)."""
    await require_workspace_scope(token, request.assistant_id, write=True)
    if not is_owner(await current_admin(token)):
        raise HTTPException(status_code=403, detail="owner role required to publish")
    try:
        return await run_pipeline(
            source_keys=request.source_keys,
            force_ingestion=True,
            publish=True,
            publish_limit=1,
            idempotency_key=request.idempotency_key or f"manual-publish:{uuid.uuid4()}",
            assistant_id=request.assistant_id,
        )
    except Exception as exc:
        logger.exception("manual publication failed")
        raise HTTPException(status_code=500, detail="manual publication failed") from exc


@app.get("/metrics")
async def metrics(
    assistant_id: uuid.UUID | None = None,
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    await require_workspace_scope(token, assistant_id)
    return await pipeline_metrics(assistant_id=assistant_id)


@app.get("/operations/status")
async def product_operations_status(
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    from app.product_status import operations_status

    await require_workspace_scope(token, assistant_id)
    result = await operations_status(assistant_id=assistant_id)
    if not is_owner(await current_admin(token)):
        result.pop("budgets", None)
        result.pop("budget_day_start", None)
    return result


@app.post("/relevance/rescore")
async def relevance_rescore(
    limit: int = Query(default=1000, ge=1, le=5000),
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    if not is_owner(await current_admin(token)):
        raise HTTPException(status_code=403, detail="owner role required")
    return await rescore_existing_articles(limit=limit)


@app.post("/analysis/regenerate-fallbacks")
async def analysis_regenerate_fallbacks(
    limit: int = Query(default=200, ge=1, le=1000),
    assistant_id: uuid.UUID | None = None,
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, int]:
    if not is_owner(await current_admin(token)):
        raise HTTPException(status_code=403, detail="owner role required")
    await require_workspace_scope(token, assistant_id, write=True)
    return await regenerate_fallback_analyses(limit=limit, assistant_id=assistant_id)


@app.post("/analysis/reanalyze-fallbacks")
async def analysis_reanalyze_fallbacks(
    limit: int = Query(default=5, ge=1, le=20),
    assistant_id: uuid.UUID | None = None,
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    if not is_owner(await current_admin(token)):
        raise HTTPException(status_code=403, detail="owner role required")
    try:
        await require_workspace_scope(token, assistant_id, write=True)
        return await reanalyze_fallback_articles(settings, limit=limit, assistant_id=assistant_id)
    except Exception as exc:
        logger.exception("fallback reanalysis failed")
        raise HTTPException(status_code=500, detail="fallback reanalysis failed") from exc


@app.get("/scheduler/status")
async def scheduler_status(
    assistant_id: uuid.UUID | None = None,
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    await require_workspace_scope(token, assistant_id)
    user = await current_admin(token)
    schedule_times, overridden = await scheduler_schedule_times(settings)
    schedule_slots, _ = await scheduler_schedule_config(settings)
    collection_enabled = True
    collection_slots = default_collection_schedule_slots()
    if assistant_id is not None:
        async with SessionLocal() as session:
            assistant = await session.get(AssistantWorkspace, assistant_id)
        runtime = ((assistant.config if assistant else {}) or {}).get("runtime") or {}
        collection_enabled = runtime.get("collection_enabled", True) is not False
        raw_collection_slots = runtime.get("collection_schedule_slots")
        if raw_collection_slots:
            try:
                collection_slots = normalize_schedule_slots(raw_collection_slots)
            except (TypeError, ValueError):
                collection_slots = default_collection_schedule_slots()
    response: dict[str, object] = {
        **runtime_status(),
        "enabled": settings.scheduler_enabled,
        "timezone": settings.timezone,
        "schedule_times": list(schedule_times),
        "schedule_slots": [{"weekday": weekday, "time": value} for weekday, value in schedule_slots],
        "schedule_override": overridden,
        "missed_run_recovery_hours": settings.missed_run_recovery_hours,
        "collection_owner_only": True,
        "publication_boundary": "selected_schedule_slots",
    }
    if is_owner(user):
        response.update({
            "collection_enabled": collection_enabled,
            "collection_schedule_slots": [{"weekday": weekday, "time": value} for weekday, value in collection_slots],
            "collection_frequency": "owner_configured_slots",
        })
    return response


@app.get("/admin/api/scheduler/settings")
async def admin_api_scheduler_settings(token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="owner role required")
    schedule_times, overridden = await scheduler_schedule_times(settings)
    schedule_slots, _ = await scheduler_schedule_config(settings)
    return {
        "schedule_times": list(schedule_times),
        "schedule_slots": [{"weekday": weekday, "time": value} for weekday, value in schedule_slots],
        "timezone": settings.timezone,
        "schedule_override": overridden,
        "source": "redis" if overridden else "environment",
    }


@app.put("/admin/api/scheduler/settings")
async def admin_api_update_scheduler_settings(payload: SchedulerSettingsRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="owner role required")
    try:
        if payload.schedule_slots:
            schedule_slots = await update_scheduler_schedule_slots(settings, payload.schedule_slots)
        elif payload.schedule_times:
            schedule_slots = await update_scheduler_schedule_slots(settings, [{"weekday": weekday, "time": value} for weekday in range(7) for value in payload.schedule_times])
        else:
            raise ValueError("schedule_slots or schedule_times is required")
    except ValueError as exc:
        if str(exc) == "feedback actor is not authorized":
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    times = sorted({value for _, value in schedule_slots}, key=lambda value: (int(value[:2]), int(value[3:])))
    return {"schedule_times": times, "schedule_slots": [{"weekday": weekday, "time": value} for weekday, value in schedule_slots], "timezone": settings.timezone, "schedule_override": True}


@app.get("/telegram/readiness")
async def telegram_readiness(
    assistant_id: uuid.UUID | None = None,
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    await require_workspace_scope(token, assistant_id)
    resolved_settings = await settings_for_assistant(settings, assistant_id)
    status = await TelegramClient(resolved_settings).check_permissions()
    return {
        "configured": resolved_settings.telegram_ready,
        "pilot_mode": resolved_settings.pilot_mode,
        "auto_publish": resolved_settings.auto_publish,
        "permission": {
            "ready": status.ready,
            "bot_username": status.bot_username,
            "member_status": status.member_status,
            "can_post": status.can_post,
            "can_edit": status.can_edit,
            "can_delete": status.can_delete,
            "error": status.error,
        },
    }


@app.get("/whatsapp/readiness")
async def whatsapp_readiness_endpoint(
    assistant_id: uuid.UUID | None = None,
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    """Return a secret-free WhatsApp gate; this endpoint never sends a message."""
    await require_workspace_scope(token, assistant_id)
    resolved_settings = await settings_for_assistant(settings, assistant_id)
    return WhatsAppClient(resolved_settings).readiness().safe_dict()


@app.get("/publications")
async def publications(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    assistant_id: uuid.UUID | None = None,
    query: str | None = Query(default=None, max_length=200),
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    await require_workspace_scope(token, assistant_id)
    rows = await list_publications(status=status, limit=limit, assistant_id=assistant_id, query=query)
    return {"count": len(rows), "publications": rows}


@app.get("/publications/relevance-assessments")
async def relevance_assessments(
    assistant_id: uuid.UUID,
    limit: int = Query(default=200, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=500),
    state: str | None = Query(default=None, pattern="^(selected|borderline|rejected|pending)$"),
    query: str | None = Query(default=None, max_length=200),
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    await require_workspace_scope(token, assistant_id)
    return await list_relevance_assessments(assistant_id=assistant_id, limit=limit, offset=offset, state=state, query=query)


@app.get("/insights")
async def insights(
    assistant_id: uuid.UUID | None = None,
    days: int = Query(default=7, ge=1, le=30),
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    """Return review-first priority, quality, conflict, trend and source-health data."""
    await require_workspace_scope(token, assistant_id)
    if assistant_id is None:
        raise HTTPException(status_code=422, detail="assistant_id is required")
    return await insights_snapshot(assistant_id=assistant_id, days=days)


@app.post("/insights/translate")
async def insights_translate(
    request: InsightTranslationRequest,
    assistant_id: uuid.UUID | None = None,
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    await require_workspace_scope(token, assistant_id)
    if assistant_id is None:
        raise HTTPException(status_code=422, detail="assistant_id is required")
    try:
        resolved = await settings_for_assistant(settings, assistant_id)
        return await translate_analysis(
            settings=resolved,
            analysis_id=request.analysis_id,
            assistant_id=assistant_id,
            target_language=request.target_language,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/admin/api/sources/{source_id}/official-fallback")
async def admin_api_source_official_fallback(
    source_id: uuid.UUID,
    assistant_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    """Select a configured public homepage as a reviewed, non-paywall fallback."""
    user = await current_admin(token)
    await _require_assistant_access(assistant_id, user, write=True)
    try:
        return await activate_official_fallback(source_id=source_id, assistant_id=assistant_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/publications/refresh-previews")
async def publications_refresh_previews(
    limit: int = Query(default=200, ge=1, le=1000),
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, int]:
    if not is_owner(await current_admin(token)):
        raise HTTPException(status_code=403, detail="owner role required")
    return await refresh_publication_previews(limit=limit)


@app.post("/publications/{publication_id}/publish")
async def publication_publish(
    publication_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    if not is_owner(await current_admin(token)):
        raise HTTPException(status_code=403, detail="owner role required")
    try:
        return await publish_publication(publication_id, allow_stale_claim=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/publications/{publication_id}/approve-borderline")
async def publication_approve_borderline(
    publication_id: uuid.UUID,
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    if not is_owner(await current_admin(token)):
        raise HTTPException(status_code=403, detail="owner role required")
    try:
        return await approve_borderline_publication(publication_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/admin/api/assistants/{assistant_id}/publications/{publication_id}/review")
async def admin_api_review_publication(assistant_id: uuid.UUID, publication_id: uuid.UUID, payload: PublicationReviewRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await review_publication(assistant_id, publication_id, payload, await current_admin(token))


@app.get("/admin/api/assistants/{assistant_id}/analyses/{analysis_id}/explanation")
async def admin_api_publication_explanation(assistant_id: uuid.UUID, analysis_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await publication_explanation(assistant_id, analysis_id, await current_admin(token))


@app.get("/shared/reports/{raw_token}")
async def shared_report(raw_token: str) -> dict[str, object]:
    if len(raw_token) < 32 or len(raw_token) > 128:
        raise HTTPException(status_code=404, detail="report not found")
    return await resolve_share_link(raw_token)


@app.post("/feedback")
async def feedback(
    request: FeedbackRequest,
    token: str | None = Cookie(default=None, alias=ADMIN_SESSION_COOKIE),
) -> dict[str, object]:
    # Telegram feedback buttons are processed in the private polling loop and
    # do not use this HTTP endpoint. The HTTP fallback records feedback only
    # as the signed-in account, on a workspace that account can access.
    return await record_admin_feedback(
        request.analysis_id,
        value=request.value,
        note=request.note,
        actor_key=request.actor_key,
        user=await current_admin(token),
    )


@app.post("/weekly-reports/run")
async def weekly_report_run(
    assistant_id: uuid.UUID | None = None,
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    if not is_owner(await current_admin(token)):
        raise HTTPException(status_code=403, detail="owner role required")
    await require_workspace_scope(token, assistant_id or DEFAULT_ASSISTANT_ID)
    return await generate_weekly_report(assistant_id=assistant_id)


@app.get("/feedback/report")
async def feedback_report(
    days: int = Query(default=1, ge=1, le=30),
    assistant_id: uuid.UUID | None = None,
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    user = await current_admin(token)
    if assistant_id is None:
        if not is_global_admin(user):
            raise HTTPException(status_code=403, detail="assistant_id is required")
    else:
        await _require_assistant_access(assistant_id, user)
    return await feedback_daily_report(days=days, assistant_id=assistant_id)


@app.post("/feedback/ranking/apply")
async def feedback_ranking_apply(
    idempotency_key: str | None = None,
    min_samples: int = Query(default=3, ge=1, le=100),
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    user = await current_admin(token)
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="owner role required")
    return await apply_feedback_ranking(idempotency_key=idempotency_key, min_samples=min_samples)


@app.get("/feedback/learning")
async def feedback_learning(
    assistant_id: uuid.UUID,
    days: int = Query(default=30, ge=1, le=30),
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    return await feedback_learning_center(assistant_id, await current_admin(token), days=days)


@app.post("/feedback/ranking/rollback")
async def feedback_ranking_rollback(token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    return await rollback_feedback_ranking(await current_admin(token))


@app.post("/retention/run")
async def retention_run(token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    if not is_owner(await current_admin(token)):
        raise HTTPException(status_code=403, detail="owner role required")
    return await apply_retention(settings)
