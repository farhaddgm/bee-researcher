from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Cookie, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import get_settings
from app.database import SessionLocal, check_database
from app.models import AssistantWorkspace
from app.ingestion_service import (
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
    pipeline_metrics,
    publish_publication,
    approve_borderline_publication,
    refresh_publication_previews,
    regenerate_fallback_analyses,
    reanalyze_fallback_articles,
    record_feedback,
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
)
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
from app.security_controls import (
    ADMIN_SESSION_COOKIE,
    CSRF_COOKIE,
    clear_login_failures,
    csrf_token_matches,
    login_attempts_exceeded,
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
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop = asyncio.Event()
    tasks: list[asyncio.Task] = []
    if settings.scheduler_enabled:
        tasks.append(asyncio.create_task(scheduler_loop(settings, stop)))
    if settings.telegram_ready and settings.telegram_polling_enabled:
        tasks.append(asyncio.create_task(telegram_feedback_loop(settings, stop)))
    try:
        yield
    finally:
        stop.set()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


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

# Bee CFO exposes an API/control contract only in phase one.  Its back-office
# UI is intentionally out of scope; the router remains independently removable
# when the bounded context is split into its own service.
app.include_router(bee_cfo_router)


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
        "original-policy",
        "source-file",
        "violated-directive",
    }
    items: list[dict[str, object]] = []
    for report in reports[:20]:
        if not isinstance(report, dict):
            continue
        cleaned: dict[str, object] = {}
        for key in allowed:
            if key not in report:
                continue
            value = report[key]
            if isinstance(value, str):
                cleaned[key] = redact_sensitive_text(value, limit=300)
            elif isinstance(value, (int, float)) and key == "line-number":
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

    raw = await request.body()
    if len(raw) > 64_000:
        return Response(status_code=413)
    if not raw:
        return Response(status_code=204)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return Response(status_code=400)
    items = _csp_report_items(payload)
    if items:
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

    await current_admin(token)
    raw = await request.body()
    if len(raw) > 1_024:
        return Response(status_code=413)
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return Response(status_code=400)
    if not isinstance(payload, dict):
        return Response(status_code=400)
    kind = str(payload.get("kind") or "unknown")[:32]
    view = str(payload.get("view") or "unknown")[:80]
    if kind not in {"window", "promise", "action", "unknown"}:
        kind = "unknown"
    def safe_token(value: object, limit: int = 64) -> str:
        token = str(value or "")[:limit]
        return token if re.fullmatch(r"[A-Za-z0-9_.:-]+", token or "") else "unknown"

    action = safe_token(payload.get("action")) if kind == "action" else ""
    phase = safe_token(payload.get("phase")) if kind == "action" else ""
    outcome = safe_token(payload.get("outcome")) if kind == "action" else ""
    route = safe_token(payload.get("route"), 96) if kind == "action" else ""
    status = payload.get("status") if kind == "action" else None
    duration = payload.get("duration_ms") if kind == "action" else None
    if not isinstance(status, int) or status < 0 or status > 999:
        status = 0
    if not isinstance(duration, int) or duration < 0 or duration > 120_000:
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
        client_host = request.client.host if request.client else ""
        try:
            address = ipaddress.ip_address(client_host)
        except ValueError:
            return False
        return address.is_private or address.is_loopback

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
            and request.cookies.get(ADMIN_SESSION_COOKIE)
        ):
            if not csrf_token_matches(
                request.cookies.get(CSRF_COOKIE),
                request.headers.get("x-csrf-token"),
                request.cookies.get(ADMIN_SESSION_COOKIE),
                settings,
            ):
                return JSONResponse(status_code=403, content={"detail": "csrf validation failed"})
    response = await call_next(request)
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
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
    # Keep the compatibility policy only while the inline migration is in
    # progress.  Deployments can opt into the strict policy after browser
    # smoke verification; strict mode never includes either unsafe-inline
    # exception.
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
    actor_key: str = Field(min_length=1, max_length=128)
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


@app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def admin_ui(request: Request) -> HTMLResponse:
    # ADMIN_HTML is a trusted static template. Nonces are injected only into
    # these known script/style tags; dynamic preview content is sanitized in
    # the browser and never receives this nonce.
    nonce = secrets.token_urlsafe(24)
    request.state.csp_nonce = nonce
    body = _inject_inline_nonce(ADMIN_HTML, nonce)
    return HTMLResponse(body, headers={"Cache-Control": "no-store"})


@app.get("/user", response_class=HTMLResponse, include_in_schema=False)
async def user_ui(request: Request) -> HTMLResponse:
    """Serve the read-only published-news portal."""
    nonce = secrets.token_urlsafe(24)
    request.state.csp_nonce = nonce
    body = _inject_inline_nonce(USER_HTML, nonce)
    return HTMLResponse(
        body,
        headers={
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex, nofollow, noarchive, nosnippet",
        },
    )


@app.get("/user/settings", response_class=HTMLResponse, include_in_schema=False)
async def user_settings_ui(request: Request) -> HTMLResponse:
    """Serve the same reader shell with its personal settings as a page."""
    nonce = secrets.token_urlsafe(24)
    request.state.csp_nonce = nonce
    body = USER_HTML.replace("<body>", '<body data-user-page="settings">', 1)
    body = _inject_inline_nonce(body, nonce)
    return HTMLResponse(
        body,
        headers={
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex, nofollow, noarchive, nosnippet",
        },
    )


@app.post("/user/api/login")
async def user_api_login(payload: LoginRequest, response: Response) -> dict[str, object]:
    return await reader_login(payload, response)


@app.post("/user/api/logout")
async def user_api_logout(response: Response, token: str | None = Cookie(default=None, alias=USER_SESSION_COOKIE)) -> dict[str, str]:
    return await reader_logout(response, token)


@app.get("/user/api/me")
async def user_api_me(token: str | None = Cookie(default=None, alias=USER_SESSION_COOKIE)) -> dict[str, object]:
    user = await current_reader(token)
    return {"id": str(user.id), "username": user.username, **user_portal_access_payload(user)}


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
    if str(assistant_id) not in {str(item["id"]) for item in available["assistants"]}:
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
    if peer_address.is_private or peer_address.is_loopback:
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        try:
            candidate = ipaddress.ip_address(forwarded)
        except ValueError:
            return peer
        if candidate.is_global:
            return str(candidate)
    return peer


@app.post("/admin/api/login")
async def admin_api_login(payload: LoginRequest, response: Response, http_request: Request) -> dict[str, object]:
    username = payload.username.strip().lower()
    client_address = _login_client_address(http_request)
    if await login_attempts_exceeded(settings, username, client_address):
        raise HTTPException(
            status_code=429,
            detail="too many login attempts",
            headers={"Retry-After": str(settings.login_window_seconds)},
        )
    try:
        result = await admin_login(payload, response)
    except HTTPException as exc:
        if exc.status_code == 401:
            await record_login_failure(settings, username, client_address)
        raise
    await clear_login_failures(settings, username, client_address)
    return result


@app.post("/admin/api/logout")
async def admin_api_logout(response: Response, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, str]:
    result = await admin_logout(response, token)
    response.headers["Clear-Site-Data"] = '"cache", "cookies", "storage"'
    return result


@app.get("/admin/api/me")
async def admin_api_me(token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return {"id": str(user.id), "username": user.username, "role": effective_user_role(user), "stored_role": user.role, "is_owner": is_owner(user), "avatar_url": (user.preferences or {}).get("avatar_url") or default_avatar_data(user.id), "mfa_required": False, **user_portal_access_payload(user)}


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
    if user.role not in {"admin", "assistant_admin", "editor"}: raise HTTPException(status_code=403, detail="editor role required")
    return await update_source(source_id, payload, user)


@app.post("/admin/api/assistants/{assistant_id}/sources")
async def admin_api_create_source(assistant_id: uuid.UUID, payload: SourceCreate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    if user.role not in {"owner", "admin", "assistant_admin", "editor"}:
        raise HTTPException(status_code=403, detail="editor role required")
    return await create_source(assistant_id, payload, user)


@app.post("/admin/api/assistants/{assistant_id}/public-social-sources")
async def admin_api_create_public_social_source(
    assistant_id: uuid.UUID,
    payload: PublicSocialSourceCreate,
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    """Create a public social source from a platform handle in the back-office."""
    user = await current_admin(token)
    if user.role not in {"owner", "admin", "assistant_admin", "editor"}:
        raise HTTPException(status_code=403, detail="editor role required")
    try:
        return await create_public_social_source(assistant_id, payload, user)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/admin/api/assistants/{assistant_id}/sources/draft")
async def admin_api_draft_source(assistant_id: uuid.UUID, payload: CatalogDraftRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    if user.role not in {"owner", "admin", "assistant_admin", "editor"}:
        raise HTTPException(status_code=403, detail="editor role required")
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
    if user.role not in {"owner", "admin", "assistant_admin", "editor"}:
        raise HTTPException(status_code=403, detail="editor role required")
    return await delete_source(source_id, user)


@app.post("/admin/api/sources/{source_id}/move")
async def admin_api_move_source(source_id: uuid.UUID, payload: OrderMoveRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    if user.role not in {"owner", "admin", "assistant_admin", "editor"}:
        raise HTTPException(status_code=403, detail="editor role required")
    return await move_source(source_id, payload, user)


@app.patch("/admin/api/topics/{topic_id}")
async def admin_api_update_topic(topic_id: uuid.UUID, payload: TopicUpdate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    if user.role not in {"owner", "admin", "assistant_admin", "editor"}: raise HTTPException(status_code=403, detail="editor role required")
    return await update_topic(topic_id, payload, user)


@app.post("/admin/api/assistants/{assistant_id}/topics")
async def admin_api_create_topic(assistant_id: uuid.UUID, payload: TopicCreate, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    if user.role not in {"owner", "admin", "assistant_admin", "editor"}:
        raise HTTPException(status_code=403, detail="editor role required")
    return await create_topic(assistant_id, payload, user)


@app.post("/admin/api/assistants/{assistant_id}/topics/draft")
async def admin_api_draft_topic(assistant_id: uuid.UUID, payload: CatalogDraftRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    if user.role not in {"owner", "admin", "assistant_admin", "editor"}:
        raise HTTPException(status_code=403, detail="editor role required")
    return await draft_topic(assistant_id, payload, user)


@app.delete("/admin/api/topics/{topic_id}")
async def admin_api_delete_topic(topic_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, str]:
    user = await current_admin(token)
    if user.role not in {"admin", "assistant_admin", "editor"}:
        raise HTTPException(status_code=403, detail="editor role required")
    return await delete_topic(topic_id, user)


@app.post("/admin/api/topics/{topic_id}/move")
async def admin_api_move_topic(topic_id: uuid.UUID, payload: OrderMoveRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    if user.role not in {"admin", "assistant_admin", "editor"}:
        raise HTTPException(status_code=403, detail="editor role required")
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
    if user.role not in {"owner", "admin", "assistant_admin", "editor"}:
        raise HTTPException(status_code=403, detail="editor role required")
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
    if user.role not in {"admin", "assistant_admin", "editor"}: raise HTTPException(status_code=403, detail="editor role required")
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
    if not (is_owner(user) or user.role in {"admin", "assistant_admin", "editor"}):
        raise HTTPException(status_code=403, detail="editor role required")
    return await update_assistant_runtime_settings(assistant_id, payload, user)


@app.post("/admin/api/assistants/{assistant_id}/runtime-settings/preview")
async def admin_api_preview_runtime_settings(assistant_id: uuid.UUID, payload: RuntimeSettingsPreviewRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    if not (is_owner(user) or user.role in {"admin", "assistant_admin", "editor"}):
        raise HTTPException(status_code=403, detail="editor role required")
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


@app.delete("/admin/api/sessions/{session_id}")
async def admin_api_revoke_session(session_id: uuid.UUID, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, str]:
    user = await current_admin(token)
    return await revoke_session(session_id, user, token)


@app.delete("/admin/api/sessions/others")
async def admin_api_revoke_other_sessions(token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    user = await current_admin(token)
    return await revoke_other_sessions(user, token)


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
        "admin_session_idle_hours": min(settings.admin_session_ttl_hours, 6),
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
    try:
        return await run_pipeline(
            source_keys=request.source_keys,
            force_ingestion=request.force_ingestion,
            publish=request.publish,
            max_candidates=request.max_candidates,
            idempotency_key=request.idempotency_key,
            assistant_id=request.assistant_id,
        )
    except Exception as exc:
        logger.exception("pipeline execution failed")
        raise HTTPException(status_code=500, detail="pipeline execution failed") from exc


@app.post("/pipeline/manual-publish")
async def pipeline_manual_publish(request: PipelineRequest, token: str | None = Cookie(default=None, alias="research_bee_admin_session")) -> dict[str, object]:
    """Prepare at most one fresh item and publish it immediately, outside scheduler slots."""
    await require_workspace_scope(token, request.assistant_id, write=True)
    try:
        return await run_pipeline(
            source_keys=request.source_keys,
            force_ingestion=True,
            publish=True,
            max_candidates=1,
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
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, int]:
    if not is_owner(await current_admin(token)):
        raise HTTPException(status_code=403, detail="owner role required")
    return await regenerate_fallback_analyses(limit=limit)


@app.post("/analysis/reanalyze-fallbacks")
async def analysis_reanalyze_fallbacks(
    limit: int = Query(default=5, ge=1, le=20),
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    if not is_owner(await current_admin(token)):
        raise HTTPException(status_code=403, detail="owner role required")
    try:
        return await reanalyze_fallback_articles(settings, limit=limit)
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
        return await publish_publication(publication_id)
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
    # do not use this HTTP endpoint. Keep the HTTP fallback authenticated so a
    # caller cannot forge an allowed actor key and mutate feedback state.
    await current_admin(token)
    try:
        actor = request.actor_key.strip().lower().lstrip("@")
        return await record_feedback(
            request.analysis_id,
            actor_key=actor,
            value=request.value,
            note=request.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/weekly-reports/run")
async def weekly_report_run(
    assistant_id: uuid.UUID | None = None,
    token: str | None = Cookie(default=None, alias="research_bee_admin_session"),
) -> dict[str, object]:
    if not is_owner(await current_admin(token)):
        raise HTTPException(status_code=403, detail="owner role required")
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
