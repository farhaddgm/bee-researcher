from __future__ import annotations

import asyncio
import base64
import difflib
import hashlib
import hmac
import json
import math
import re
import secrets
import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, Literal
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Cookie, HTTPException, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import case, delete, func, or_, select, text, true, update
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    AdminAuditLog,
    AdminSession,
    AdminUser,
    ArticleAnalysis,
    ArticleTopic,
    AssistantMember,
    AssistantWorkspace,
    BusinessProfile,
    ClusterMember,
    EventCluster,
    Feedback,
    JobRun,
    NormalizedArticle,
    Publication,
    Source,
    SourceFetchRun,
    SourceItem,
    SupportTicket,
    SupportTicketMessage,
    Topic,
)
from app.openai_client import OpenAIClient
from app.fetchers import FetchFailure, SourceFetcher, SourceSpec, validate_connector_binding, validate_public_url_syntax
from app.google_auth import GoogleAuthError, GoogleIdentity, is_gmail, normalize_email
from app.media_discovery import discover_media, publisher_host
from app.retention import MIN_RETENTION_DAYS, effective_retention_days
from app.security_controls import CSRF_COOKIE, new_csrf_token
from app.telegram_delivery import render_analysis_message

COOKIE = "research_bee_admin_session"
USER_SESSION_COOKIE = "research_bee_user_session"
_WORKSPACE_WRITE_ROLES = frozenset({"admin", "owner", "assistant_admin", "editor"})
_ROLE_RANK = {"viewer": 1, "analyst": 2, "editor": 3, "assistant_admin": 4, "admin": 5, "owner": 6}
DEFAULT_ASSISTANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
OUTPUT_LANGUAGE_CODES = ("source", "fa", "en", "tr", "ar", "it", "es", "de", "fr")


def _object_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _object_list(value: object) -> list[object]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _mapping_rows(value: object) -> list[dict[str, object]]:
    return [dict(item) for item in _object_list(value) if isinstance(item, Mapping)]


def _string_values(value: object) -> list[str]:
    return [item for item in _object_list(value) if isinstance(item, str)]


def _safe_int_value(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_float_value(value: object, *, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default

# Collection/analysis controls are deliberately a separate contract from
# publication controls.  They are owner-only even when a project editor may
# change publication hours.  Keep this list central so the API and the
# persistence layer cannot accidentally grant a lower role one of these keys.
COLLECTION_RUNTIME_FIELDS = frozenset({
    "collection_enabled",
    "collection_schedule_slots",
    "collection_max_items_per_source",
    "collection_max_items_per_run",
    "collection_max_items_per_day",
})

# Product guardrails are stored per workspace so the owner can tune capacity
# without changing deployment-wide environment variables.  These defaults
# preserve the current behaviour (seven publications per slot and a seven-day
# freshness window) while making catalog and account limits explicit.
DEFAULT_ASSISTANT_LIMITS: dict[str, int] = {
    "max_sources": 10,
    "max_topics": 20,
    "max_freshness_window_days": 7,
    "max_items_per_run": 7,
    "max_business_profiles": 5,
    "max_projects_per_user": 10,
}


def assistant_limits(config: dict | None) -> dict[str, int]:
    raw = (config or {}).get("limits") if isinstance(config, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    limits: dict[str, int] = {}
    bounds = {
        "max_sources": (1, 100),
        "max_topics": (1, 100),
        "max_freshness_window_days": (1, 7),
        "max_items_per_run": (1, 7),
        "max_business_profiles": (1, 50),
        "max_projects_per_user": (1, 100),
    }
    for key, default in DEFAULT_ASSISTANT_LIMITS.items():
        try:
            value = int(raw.get(key, default))
        except (TypeError, ValueError):
            value = default
        low, high = bounds[key]
        limits[key] = min(max(value, low), high)
    return limits

# Some installations were upgraded from the single-workspace MVP and may
# still have one or more assistant foreign keys without an effective CASCADE
# action.  Keep deletion deterministic by removing workspace-owned rows first
# in dependency order; this also makes the admin action safe during a rolling
# migration instead of surfacing a generic 500 from PostgreSQL.
_ASSISTANT_DATA_DELETE_ORDER = (
    "bee_cfo_forecast_evaluations",
    "bee_cfo_alerts",
    "bee_cfo_forecasts",
    "bee_cfo_deliveries",
    "bee_cfo_reports",
    "bee_cfo_snapshots",
    "bee_cfo_watches",
    "bee_cfo_sources",
    "bee_cfo_profiles",
    "bee_cfo_infrastructure_audits",
    "feedback",
    "publications",
    "article_topics",
    "cluster_members",
    "article_analyses",
    "event_clusters",
    "normalized_articles",
    "source_fetch_runs",
    "source_items",
    "sources",
    "topics",
    "weekly_reports",
    "business_profiles",
    "job_runs",
    "assistant_members",
)


def workspace_write_allowed(user_role: str, member_role: str | None) -> bool:
    """Return whether a user role may mutate a workspace resource.

    ``user_role`` must be the *effective* role (see ``effective_user_role``);
    the stored role column can never contain ``owner``.
    """
    if user_role == "owner":
        return True
    if member_role is None:
        return False
    # The account role is authoritative: a viewer/analyst must remain
    # read-only even if an old membership row still carries an elevated role.
    if user_role in {"admin", "assistant_admin"}:
        return member_role in {"admin", "assistant_admin"}
    return user_role == "editor" and member_role == "editor"


def workspace_delete_allowed(user_role: str, member_role: str | None, *, owner: bool = False) -> bool:
    """Return whether a user may delete this specific project.

    Project deletion is narrower than ordinary project editing: only a
    project administrator with an explicit administrator membership may do
    it.  The configured owner remains the sole account-wide exception.
    """
    if owner or user_role == "owner":
        return True
    return user_role in {"admin", "assistant_admin"} and member_role in {"admin", "assistant_admin"}


def owner_email() -> str:
    return normalize_email(str(getattr(get_settings(), "owner_email", "") or ""))


def is_owner(user: AdminUser) -> bool:
    """The owner is exactly the account carrying the configured e-mail.

    Usernames and the stored role are editable and are never an ownership
    signal.  Only the owner can attach an e-mail address to an account, and
    the owner address itself can never be assigned to another account.
    """
    email = normalize_email(str(getattr(user, "email", "") or ""))
    configured = owner_email()
    return bool(email and configured and hmac.compare_digest(email, configured))


def is_global_admin(user: AdminUser) -> bool:
    # ``admin`` is deliberately project-scoped.  Only the configured owner
    # may operate without an explicit project membership.
    return is_owner(user)


def effective_user_role(user: AdminUser) -> str:
    return "owner" if is_owner(user) else user.role


def role_rank(user: AdminUser) -> int:
    return _ROLE_RANK.get(effective_user_role(user), 0)


def has_editor_role(user: AdminUser) -> bool:
    """Account-level gate for catalog mutations; membership is checked later."""
    return effective_user_role(user) in {"owner", "admin", "assistant_admin", "editor"}


def require_editor_role(user: AdminUser) -> None:
    if not has_editor_role(user):
        raise HTTPException(status_code=403, detail="editor role required")


def ensure_can_manage_account(actor: AdminUser, target: AdminUser) -> None:
    """Only a strictly higher effective role may manage another account.

    Applies to password resets, (de)activation, renames, role and membership
    changes and session revocation.  The owner outranks everyone; an account
    may always manage itself through the self-service paths.
    """
    if actor.id == target.id or is_owner(actor):
        return
    if is_owner(target) or role_rank(target) >= role_rank(actor):
        raise HTTPException(status_code=403, detail="cannot manage an account with an equal or higher role")


def _user_portal_preference_values(user: AdminUser) -> tuple[bool, bool]:
    """Return effective reader-portal and reader-feedback permissions.

    The owner and the ``admin`` account role can always enter the User
    service (the same account directory is intentionally reused).  Everyone
    else is opt-in and must be explicitly granted access by an owner/global
    admin.  Feedback is a separate, stricter grant and is never implied by
    read access.
    """

    preferences = getattr(user, "preferences", None)
    raw = preferences.get("user_portal_access") if isinstance(preferences, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    default_portal = is_owner(user) or getattr(user, "role", None) == "admin"
    portal_enabled = default_portal or bool(raw.get("enabled", False))
    feedback_enabled = portal_enabled and bool(raw.get("feedback_enabled", False))
    return portal_enabled, feedback_enabled


def user_portal_access_allowed(user: AdminUser) -> bool:
    return _user_portal_preference_values(user)[0]


def user_feedback_access_allowed(user: AdminUser) -> bool:
    return _user_portal_preference_values(user)[1]


def user_portal_access_payload(user: AdminUser) -> dict[str, bool]:
    portal_enabled, feedback_enabled = _user_portal_preference_values(user)
    return {
        "user_portal_access": portal_enabled,
        "user_feedback_access": feedback_enabled,
    }


def can_view_admin_user(viewer: AdminUser, target: AdminUser) -> bool:
    """Enforce hierarchy when showing accounts in the security page.

    Visibility is one-way: an account can see accounts at or below its
    effective role, while every account can always see itself.  The owner
    identity may still be represented by a legacy stored ``admin`` role, so
    the effective role (rather than the raw database value) is authoritative.
    """
    if viewer.id == target.id:
        return True
    viewer_role = effective_user_role(viewer)
    target_role = effective_user_role(target)
    if viewer_role == "owner":
        return True
    if target_role == "owner":
        return False
    return _ROLE_RANK.get(target_role, 0) <= _ROLE_RANK.get(viewer_role, 0)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)


class MfaCodeRequest(BaseModel):
    """A six-digit TOTP or one-time recovery code."""

    code: str = Field(default="", max_length=64)
    recovery_code: str | None = Field(default=None, max_length=64)

class AssistantRequest(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    name: str = Field(min_length=1, max_length=160)
    # A workspace can be created before its optional business profile exists.
    # Keep the database value as an empty string (the column is intentionally
    # non-null for backwards compatibility) and let the owner add a profile
    # later when business-specific relevance is needed.
    business_name: str = Field(default="", min_length=0, max_length=160)
    description: str = Field(default="", max_length=4000)
    config: dict = Field(default_factory=dict)


class AssistantUpdate(BaseModel):
    # Stable, globally unique project identifier editable by project admins.
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    name: str | None = Field(default=None, min_length=1, max_length=160)
    business_name: str | None = Field(default=None, min_length=0, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    status: Literal["draft", "testing", "active", "paused", "archived"] | None = None
    config: dict | None = None


class AssistantCloneRequest(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    name: str = Field(min_length=1, max_length=160)
    business_name: str = Field(default="", min_length=0, max_length=160)
    description: str = Field(default="", max_length=4000)
    sandbox: bool = False


class AssistantMemberRequest(BaseModel):
    user_id: uuid.UUID
    role: Literal["editor", "viewer", "admin", "assistant_admin", "analyst"] = "viewer"


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    homepage_url: str | None = Field(default=None, min_length=8, max_length=2048)
    fetch_url: str | None = Field(default=None, min_length=8, max_length=2048)
    adapter: Literal["rss", "html", "json", "telegram_public", "telegram_private", "instagram_public", "instagram_private", "x_public", "x_private"] | None = None
    access_policy: Literal["public_only", "private_authenticated"] | None = None
    credential_ref: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    account_ref: str | None = Field(default=None, max_length=256)
    # Keep the detected source language editable independently from the
    # publication language.  The latter controls generated summaries and is
    # intentionally not inferred from this field.
    language: str | None = Field(default=None, min_length=2, max_length=16)
    output_language: Literal["source", "fa", "en", "tr", "ar", "it", "es", "de", "fr"] | None = None
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    rate_limit_seconds: int | None = Field(default=None, ge=1, le=3600)
    access_notes: str | None = Field(default=None, max_length=4000)
    display_order: int | None = Field(default=None, ge=0, le=100000)

    @field_validator("homepage_url", "fetch_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return validate_public_url_syntax(value.strip())
        except ValueError as exc:
            raise ValueError("homepage and feed URLs must be valid public http(s) URLs") from exc

    @model_validator(mode="after")
    def validate_connector_policy(self):
        if self.adapter and self.adapter.endswith("_private") and self.access_policy == "public_only":
            raise ValueError("private connector requires private_authenticated access policy")
        return self


class SourceCreate(BaseModel):
    # Keys are generated by the server.  Keep this optional for old API
    # clients, but never trust or persist a caller supplied value.
    source_key: str | None = Field(default=None, pattern=r"^S-\d{3}$")
    name: str = Field(min_length=1, max_length=160)
    homepage_url: str = Field(min_length=8, max_length=2048)
    fetch_url: str = Field(min_length=8, max_length=2048)
    adapter: Literal["rss", "html", "json", "telegram_public", "telegram_private", "instagram_public", "instagram_private", "x_public", "x_private"] = "rss"
    access_policy: Literal["public_only", "private_authenticated"] = "public_only"
    credential_ref: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    account_ref: str | None = Field(default=None, max_length=256)
    language: str = Field(default="fa", min_length=2, max_length=16)
    output_language: Literal["source", "fa", "en", "tr", "ar", "it", "es", "de", "fr"] = "source"
    region: str = Field(default="IR", min_length=2, max_length=16)
    priority: int = Field(default=3, ge=1, le=5)
    enabled: bool = True
    access_notes: str | None = Field(default=None, max_length=4000)

    @field_validator("homepage_url", "fetch_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        """Fail early with a clear 422 instead of creating an unusable source."""
        try:
            return validate_public_url_syntax(value.strip())
        except ValueError as exc:
            raise ValueError("homepage and feed URLs must be valid public http(s) URLs") from exc

    @model_validator(mode="after")
    def validate_connector_policy(self):
        if self.adapter.endswith("_private") and self.access_policy != "private_authenticated":
            raise ValueError("private connector requires private_authenticated access policy")
        if self.adapter.endswith("_public") and self.access_policy != "public_only":
            raise ValueError("public connector requires public_only access policy")
        validate_connector_binding(self.adapter, self.credential_ref, self.fetch_url, get_settings())
        return self


class PublicSocialSourceCreate(BaseModel):
    """Minimal public social-source form; operational URLs are server-built."""

    platform: Literal["telegram", "instagram", "x"]
    handle_or_url: str = Field(min_length=1, max_length=2048)
    name: str | None = Field(default=None, max_length=160)
    language: str = Field(default="en", min_length=2, max_length=16)
    region: str = Field(default="global", min_length=2, max_length=16)
    priority: int = Field(default=3, ge=1, le=5)


def _public_social_handle(platform: str, value: str) -> str:
    """Extract one public handle without accepting credentials or paths."""
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("a public account or channel is required")
    if raw.startswith("@"):
        raw = raw[1:]
    if "://" in raw:
        parsed = urlsplit(validate_public_url_syntax(raw))
        host = (parsed.hostname or "").lower().removeprefix("www.")
        allowed_hosts = {
            "telegram": {"t.me", "telegram.me"},
            "instagram": {"instagram.com"},
            "x": {"x.com", "twitter.com"},
        }[platform]
        if host not in allowed_hosts:
            raise ValueError("the URL does not belong to the selected public platform")
        parts = [part for part in parsed.path.split("/") if part]
        if platform == "telegram" and parts and parts[0].lower() == "s":
            parts = parts[1:]
        if len(parts) != 1:
            raise ValueError("enter one public account or channel URL")
        raw = parts[0].lstrip("@")
    if platform == "telegram":
        pattern = r"[A-Za-z0-9_]{5,32}"
        reserved = {"joinchat", "addstickers", "share", "login"}
    elif platform == "instagram":
        pattern = r"[A-Za-z0-9._]{1,30}"
        reserved = {"accounts", "about", "explore", "direct", "reels", "stories"}
    else:
        pattern = r"[A-Za-z0-9_]{1,15}"
        reserved = {"i", "intent", "share", "search", "home", "explore"}
    if raw.casefold() in reserved or not re.fullmatch(pattern, raw):
        raise ValueError("public account or channel handle is invalid")
    return raw


def public_social_source_config(
    platform: str,
    handle_or_url: str,
    *,
    name: str | None = None,
    language: str = "en",
    region: str = "global",
    priority: int = 3,
) -> dict[str, object]:
    """Build a safe, provider-specific public connector configuration."""
    platform = str(platform or "").strip().lower()
    if platform not in {"telegram", "instagram", "x"}:
        raise ValueError("public platform is invalid")
    handle = _public_social_handle(platform, handle_or_url)
    if platform == "telegram":
        adapter = "telegram_public"
        homepage_url = f"https://t.me/{handle}"
        fetch_url = f"https://t.me/s/{handle}"
        credential_ref = None
        display_name = name or f"Telegram · @{handle}"
        access_notes = "Public Telegram preview is fetched from the official public page; private channels are not accepted here."
    elif platform == "instagram":
        adapter = "instagram_public"
        # Business Discovery is the official public-media API. ``/me`` is
        # resolved by the server-side Meta credential and the user only
        # supplies the public username.
        fields = f"business_discovery.username({handle}){{media.limit(50){{id,caption,permalink,timestamp}}}}"
        homepage_url = f"https://www.instagram.com/{handle}/"
        fetch_url = "https://graph.facebook.com/v21.0/me?fields=" + quote(fields, safe="(),{}")
        credential_ref = "MARKET_INTELLIGENCE_INSTAGRAM_SOURCE_ACCESS_TOKEN"
        display_name = name or f"Instagram · @{handle}"
        access_notes = "Public profile media uses Meta Business Discovery; private profiles and scraping are not supported."
    else:
        adapter = "x_public"
        homepage_url = f"https://x.com/{handle}"
        # The fetcher resolves this public handle to a numeric ID and then
        # requests the timeline, so users never need to know provider IDs.
        fetch_url = f"https://api.x.com/2/users/by/username/{handle}"
        credential_ref = "MARKET_INTELLIGENCE_X_SOURCE_BEARER_TOKEN"
        display_name = name or f"X · @{handle}"
        access_notes = "Public posts use the official X API; private accounts and scraping are not supported."
    return {
        "name": str(display_name).strip()[:160],
        "homepage_url": validate_public_url_syntax(homepage_url),
        "fetch_url": validate_public_url_syntax(fetch_url),
        "adapter": adapter,
        "access_policy": "public_only",
        "credential_ref": credential_ref,
        "account_ref": handle,
        "language": str(language).strip()[:16] or "en",
        "region": str(region).strip()[:16] or "global",
        "priority": int(priority),
        "access_notes": access_notes,
    }


def _server_secret_configured(value: object | None) -> bool:
    """Return whether a server-only SecretStr (or test string) is non-empty."""
    if value is None:
        return False
    resolved = value.get_secret_value() if hasattr(value, "get_secret_value") else str(value)
    return bool(str(resolved).strip())


class TopicCreate(BaseModel):
    topic_key: str | None = Field(default=None, pattern=r"^T-\d{3}$")
    name: str = Field(min_length=1, max_length=200)
    definition: str = Field(default="", max_length=10000)
    positive_terms: list[str] = Field(default_factory=list, max_length=100)
    negative_terms: list[str] = Field(default_factory=list, max_length=100)
    importance: int = Field(default=3, ge=1, le=5)
    threshold: float = Field(default=0.45, ge=0, le=1)
    enabled: bool = True


class TelegramSettingsUpdate(BaseModel):
    feedback_channel_id: str | None = Field(default=None, max_length=32)
    observer_channel_id: str | None = Field(default=None, max_length=32)
    bot_display_name: str | None = Field(default=None, max_length=80)
    bot_username: str | None = Field(default=None, max_length=32)
    bot_id: str | None = Field(default=None, max_length=24)

    @field_validator("feedback_channel_id", "observer_channel_id")
    @classmethod
    def valid_channel_id(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not re.fullmatch(r"(?:-100\d{6,20}|\d{5,20})", value):
            raise ValueError("destination id must be a numeric private chat or channel id")
        return value

    @field_validator("bot_username")
    @classmethod
    def valid_bot_username(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip().lstrip("@")
        if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", value):
            raise ValueError("bot username must be a valid Telegram username")
        return value

    @field_validator("bot_display_name")
    @classmethod
    def normalize_bot_display_name(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    @field_validator("bot_id")
    @classmethod
    def valid_bot_id(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not re.fullmatch(r"\d{5,20}", value):
            raise ValueError("bot id must be numeric")
        return value


class TopicUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    definition: str | None = None
    positive_terms: list[str] | None = None
    negative_terms: list[str] | None = None
    importance: int | None = Field(default=None, ge=1, le=5)
    threshold: float | None = Field(default=None, ge=0, le=1)
    enabled: bool | None = None
    display_order: int | None = Field(default=None, ge=0, le=100000)


class BusinessProfileUpdate(BaseModel):
    business_name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    products_services: str | None = None
    target_customers: str | None = None
    markets: str | None = None
    revenue_model: str | None = None
    strategic_goals: str | None = None
    competitors: list[str] | None = None
    sensitivities: list[str] | None = None
    output_language: str | None = Field(default=None, max_length=16)
    output_tone: str | None = None


class BusinessProfileCreate(BusinessProfileUpdate):
    business_name: str = Field(min_length=1, max_length=160)
    description: str = ""
    products_services: str = ""
    target_customers: str = ""
    markets: str = ""
    output_language: str = "fa"
    output_tone: str = "کوتاه، تحلیلی، اجرایی و رسمی"


class CatalogDraftRequest(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    instruction: str = Field(default="", max_length=4000)
    page: int = Field(default=0, ge=0, le=9)
    exclude_urls: list[str] = Field(default_factory=list, max_length=100)


class AssistantDraftRequest(BaseModel):
    """Short natural-language mission used by the owner shortcut."""

    mission: str = Field(min_length=8, max_length=2000)
    language: str = Field(default="fa", min_length=2, max_length=16)


class BusinessKnowledgeUpdate(BaseModel):
    """Project-scoped, reviewable knowledge for better business context."""

    facts: list[str] = Field(default_factory=list, max_length=50)
    products_services: list[str] = Field(default_factory=list, max_length=50)
    markets: list[str] = Field(default_factory=list, max_length=50)
    differentiators: list[str] = Field(default_factory=list, max_length=50)
    strategic_goals: list[str] = Field(default_factory=list, max_length=50)
    sensitivities: list[str] = Field(default_factory=list, max_length=50)
    source_urls: list[str] = Field(default_factory=list, max_length=50)


class PrivacySettingsUpdate(BaseModel):
    retention_days: int | None = Field(default=None, ge=MIN_RETENTION_DAYS, le=3650)
    data_region: str | None = Field(default=None, min_length=2, max_length=64)
    export_enabled: bool | None = None


class TemplateBlocksRequest(BaseModel):
    """Safe, owner-managed content template blocks for a destination."""

    blocks: list[dict[str, object]] = Field(min_length=1, max_length=12)
    publish: bool = True


class AccountPreferencesUpdate(BaseModel):
    theme: Literal["system", "light", "dark", "default", "honey", "forest", "slate", "blackyellow", "red"] | None = None
    accent_color: Literal["blue", "teal", "purple", "orange", "red", "gray"] | None = None
    density: Literal["comfortable", "compact"] | None = None
    sidebar_collapsed: bool | None = None
    default_view: Literal["assistants", "overview", "content"] | None = None
    auto_refresh: bool | None = None
    show_technical_details: bool | None = None
    avatar_url: str | None = Field(default=None, max_length=500_000)

    @field_validator("avatar_url")
    @classmethod
    def validate_avatar_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not re.fullmatch(r"data:image/(?:png|jpe?g|webp|gif);base64,[A-Za-z0-9+/=]+", value):
            raise ValueError("avatar must be a PNG, JPEG, WEBP or GIF image")
        return value


class ReaderPreferencesUpdate(BaseModel):
    """Preferences that a reader may change for their own /user session.

    These values are deliberately separate from account/workspace settings:
    a reader can tune presentation and notifications without gaining access
    to sources, credentials, scheduling or publishing controls.
    """

    columns: Literal[2, 3, 4] | None = None
    text_direction: Literal["auto", "ltr", "rtl"] | None = None
    notifications: bool | None = None
    theme: Literal["honey", "default", "dark", "red"] | None = None


class ReaderAnnotationUpdate(BaseModel):
    """A reader's private deep-reading state for one published item.

    An annotation is deliberately scoped to the authenticated reader.  It
    never changes the publication, workspace ranking, or the shared pipeline.
    """

    note: str = Field(default="", max_length=6000)
    tags: list[str] = Field(default_factory=list, max_length=12)
    highlights: list[str] = Field(default_factory=list, max_length=20)
    read_later: bool = False

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        for item in value:
            normalized = " ".join(str(item or "").split())[:48]
            if normalized and normalized.casefold() not in {tag.casefold() for tag in result}:
                result.append(normalized)
        return result[:12]

    @field_validator("highlights")
    @classmethod
    def normalize_highlights(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        for item in value:
            normalized = " ".join(str(item or "").split())[:800]
            if normalized and normalized not in result:
                result.append(normalized)
        return result[:20]


class BusinessDraftRequest(BaseModel):
    business_name: str = Field(min_length=1, max_length=160)
    instruction: str = Field(default="", max_length=4000)


class AssistantRuntimeSettingsUpdate(BaseModel):
    relevance_threshold: float | None = Field(default=None, ge=0, le=1)
    max_items_per_run: int | None = Field(default=None, ge=1, le=7)
    freshness_window_days: int | None = Field(default=None, ge=1, le=7)
    telegram_silent_notifications: bool | None = None
    analysis_model: str | None = Field(default=None, min_length=1, max_length=64)
    allowed_feedback_usernames: list[str] | None = Field(default=None, max_length=100)
    schedule_slots: list[dict[str, object]] | None = Field(default=None, max_length=168)
    # Source collection and model analysis run on their own cadence.  These
    # fields are accepted by the shared runtime endpoint but are authorized
    # and persisted only for the account owner (see COLLECTION_RUNTIME_FIELDS).
    collection_enabled: bool | None = None
    collection_schedule_slots: list[dict[str, object]] | None = Field(default=None, max_length=168)
    collection_max_items_per_source: int | None = Field(default=None, ge=1, le=200)
    collection_max_items_per_run: int | None = Field(default=None, ge=1, le=1000)
    collection_max_items_per_day: int | None = Field(default=None, ge=1, le=1000)
    active_business_id: int | None = Field(default=None, ge=1)
    deactivate_business: bool = False
    timezone: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("analysis_model")
    @classmethod
    def validate_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        # Keep the selector explicit and auditable; arbitrary model strings
        # must never be able to bypass the deployment's supported set.
        allowed = {"gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.5", "gpt-5.4"}
        if value not in allowed:
            raise ValueError("analysis_model is not in the supported model list")
        return value

    @field_validator("allowed_feedback_usernames")
    @classmethod
    def normalize_feedback_users(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = sorted({str(item).strip().lower().lstrip("@") for item in value if str(item).strip()})
        if any(not re.fullmatch(r"[a-zA-Z0-9_.-]{3,128}", item) for item in cleaned):
            raise ValueError("allowed feedback usernames must be Telegram usernames")
        return cleaned

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("timezone must be a valid IANA timezone") from None
        return value

    @field_validator("schedule_slots")
    @classmethod
    def normalize_hourly_schedule(cls, value: list[dict[str, object]] | None) -> list[dict[str, object]] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("schedule_slots must contain at least one publishing hour")
        slots: set[tuple[int, str]] = set()
        for item in value:
            try:
                weekday = _safe_int_value(item.get("weekday"), default=-1)
                time = str(item["time"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("each schedule slot requires weekday and time") from exc
            if weekday not in range(7) or not re.fullmatch(r"(?:[01]\d|2[0-3]):00", time):
                raise ValueError("schedule slots must use weekday 0..6 and whole-hour HH:00 values")
            slots.add((weekday, time))
        return [{"weekday": weekday, "time": time} for weekday, time in sorted(slots)]

    @field_validator("collection_schedule_slots")
    @classmethod
    def normalize_collection_schedule(cls, value: list[dict[str, object]] | None) -> list[dict[str, object]] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("collection_schedule_slots must contain at least one collection hour")
        slots: set[tuple[int, str]] = set()
        for item in value:
            try:
                weekday = _safe_int_value(item.get("weekday"), default=-1)
                slot_time = str(item["time"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("each collection slot requires weekday and time") from exc
            if weekday not in range(7) or not re.fullmatch(r"(?:[01]\d|2[0-3]):00", slot_time):
                raise ValueError("collection slots must use weekday 0..6 and whole-hour HH:00 values")
            slots.add((weekday, slot_time))
        return [{"weekday": weekday, "time": slot_time} for weekday, slot_time in sorted(slots)]


class RuntimeSettingsPreviewRequest(AssistantRuntimeSettingsUpdate):
    """Non-mutating settings proposal used by the dry-run preview."""


class PublicationReviewRequest(BaseModel):
    state: Literal["draft", "review", "approved", "rejected"]
    note: str | None = Field(default=None, max_length=2000)


class ShareLinkCreateRequest(BaseModel):
    expiry_hours: int = Field(default=24, ge=1, le=168)
    publication_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)
    label: str | None = Field(default=None, max_length=120)


class AssistantLimitsUpdate(BaseModel):
    """Owner-managed per-project capacity guardrails."""

    max_sources: int = Field(ge=1, le=100)
    max_topics: int = Field(ge=1, le=100)
    max_freshness_window_days: int = Field(ge=1, le=7)
    max_items_per_run: int = Field(ge=1, le=7)
    max_business_profiles: int = Field(ge=1, le=50)
    max_projects_per_user: int = Field(ge=1, le=100)


class NewsViewRequest(BaseModel):
    """A personal, project-scoped News List view."""

    view_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=80)
    filters: dict[str, object] = Field(default_factory=dict)
    is_default: bool = False


class PublicationBulkRequest(BaseModel):
    """Safe batch actions for the review queue.

    Bulk Telegram publishing is intentionally represented but blocked until a
    separate safety gate is approved.  Archive/reject/label never send a
    message and are bounded to 50 selected rows.
    """

    ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    action: Literal["archive", "reject", "label", "approve"]
    label: str | None = Field(default=None, max_length=40)


class PublicationBulkUndoRequest(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


class AdminUserRequest(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9_.-]{3,128}$")
    password: str = Field(min_length=12, max_length=256)
    role: Literal["admin", "editor", "viewer", "assistant_admin", "analyst"] = "viewer"
    assistant_ids: list[uuid.UUID] | None = None
    user_portal_access: bool | None = None
    user_feedback_access: bool | None = None


class AdminUserUpdate(BaseModel):
    username: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_.-]{3,128}$")
    role: Literal["admin", "editor", "viewer", "assistant_admin", "analyst"] | None = None
    active: bool | None = None
    user_portal_access: bool | None = None
    user_feedback_access: bool | None = None


class AdminUserManageUpdate(BaseModel):
    username: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_.-]{3,128}$")
    role: Literal["admin", "editor", "viewer", "assistant_admin", "analyst"] | None = None
    active: bool | None = None
    new_password: str | None = Field(default=None, min_length=12, max_length=256)
    current_password: str | None = Field(default=None, min_length=8, max_length=256)
    assistant_ids: list[uuid.UUID] | None = None
    user_portal_access: bool | None = None
    user_feedback_access: bool | None = None


class UserPortalAccessUpdate(BaseModel):
    """Owner/global-admin controlled access to the reader portal.

    These flags are account preferences rather than project configuration, so
    changing them never changes memberships or the back-office role itself.
    """

    enabled: bool
    feedback_enabled: bool = False

    @model_validator(mode="after")
    def feedback_requires_portal(self):
        if self.feedback_enabled and not self.enabled:
            raise ValueError("feedback access requires User-service access")
        return self


class ReaderFeedbackRequest(BaseModel):
    value: Literal["up", "down"]
    note: str | None = Field(default=None, max_length=1000)


class AdminUserPasswordUpdate(BaseModel):
    new_password: str = Field(min_length=12, max_length=256)


class OrderMoveRequest(BaseModel):
    direction: Literal["up", "down"]


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=8, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class SupportTicketCreate(BaseModel):
    subject: str | None = Field(default=None, min_length=3, max_length=200)
    category: Literal["account_access", "project_setup", "media_sources", "topics_analysis", "schedule_publishing", "telegram_whatsapp", "feedback_quality", "billing_security", "other"] = "other"
    other_subject: str | None = Field(default=None, max_length=200)
    body: str = Field(min_length=10, max_length=10000)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    assistant_id: uuid.UUID | None = None

    @field_validator("subject", "other_subject", "body", mode="before")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("body")
    @classmethod
    def require_non_blank_body(cls, value: str) -> str:
        if len(value) < 10:
            raise ValueError("support ticket description must contain at least 10 characters")
        return value


class SupportTicketUpdate(BaseModel):
    status: Literal["open", "in_progress", "waiting_user", "answered", "resolved", "closed"] | None = None
    owner_reply: str | None = Field(default=None, max_length=10000)

    @field_validator("owner_reply", mode="before")
    @classmethod
    def trim_owner_reply(cls, value):
        return value.strip() if isinstance(value, str) else value


class SupportTicketMessageCreate(BaseModel):
    """A new immutable message in a support ticket conversation."""

    body: str = Field(min_length=1, max_length=10000)

    @field_validator("body", mode="before")
    @classmethod
    def trim_message(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("body")
    @classmethod
    def require_non_blank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("support ticket message cannot be blank")
        return value


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


_DUMMY_PASSWORD_HASH = _hash_password(secrets.token_urlsafe(24))


def _check_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        # Google-only accounts have no password. Still spend the same scrypt
        # work so response timing does not reveal the account type.
        _check_password(password, _DUMMY_PASSWORD_HASH)
        return False
    try:
        _, salt_hex, digest_hex = encoded.split("$", 2)
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
        return hmac.compare_digest(actual.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def password_login_allowed(user: AdminUser) -> bool:
    return getattr(user, "login_method", "password") in {"password", "both"} and bool(user.password_hash)


def _mfa_enabled(user: AdminUser) -> bool:
    config = (user.preferences or {}).get("mfa") if isinstance(user.preferences, dict) else None
    return bool(isinstance(config, dict) and config.get("enabled") is True and config.get("secret"))


def _mfa_key() -> bytes:
    """Resolve the at-rest key without ever persisting the TOTP secret plain.

    A dedicated ``MARKET_INTELLIGENCE_MFA_ENCRYPTION_SECRET`` is preferred.
    The existing CSRF signing secret is a backwards-compatible fallback for
    installations that have not provisioned the dedicated key yet.
    """
    settings = get_settings()
    candidate = getattr(settings, "mfa_encryption_secret", None) or getattr(settings, "csrf_signing_secret", None)
    raw = candidate.get_secret_value() if candidate else ""
    if len(raw) < 32:
        raise HTTPException(status_code=503, detail="mfa encryption secret is not configured")
    return hashlib.sha256(b"bee-researcher:mfa:v1:" + raw.encode()).digest()


def _mfa_decrypt(value: str) -> str | None:
    try:
        blob = base64.urlsafe_b64decode(value.encode("ascii"))
        nonce, tag, ciphertext = blob[:16], blob[16:32], blob[32:]
        key = _mfa_key()
        expected = hmac.new(key, b"mfa" + nonce + ciphertext, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(tag, expected):
            return None
        stream = bytearray()
        counter = 0
        while len(stream) < len(ciphertext):
            stream.extend(hmac.new(key, b"stream" + nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
            counter += 1
        return bytes(a ^ b for a, b in zip(ciphertext, stream)).decode("utf-8")
    except (ValueError, TypeError, UnicodeDecodeError, HTTPException):
        return None


def _totp_code(secret: str, counter: int | None = None) -> str:
    padded = secret.upper() + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded, casefold=True)
    counter = int(time.time() // 30) if counter is None else int(counter)
    digest = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def _verify_totp(secret: str, code: str, *, last_counter: int = -1) -> int | None:
    normalized = re.sub(r"\s+", "", str(code or ""))
    if not re.fullmatch(r"\d{6}", normalized):
        return None
    now_counter = int(time.time() // 30)
    for offset in (0, -1, 1):
        counter = now_counter + offset
        if counter <= last_counter:
            continue
        if hmac.compare_digest(_totp_code(secret, counter), normalized):
            return counter
    return None


def _recovery_hash(code: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]", "", str(code or "")).upper()
    return hmac.new(_mfa_key(), b"recovery:" + normalized.encode(), hashlib.sha256).hexdigest()


def _admin_session_idle_hours() -> int:
    """Return the effective idle timeout, never exceeding the security cap."""
    # Keep the setting name backwards-compatible for existing deployments,
    # while enforcing the new six-hour maximum even if a legacy value is
    # supplied through an older environment file.
    configured = getattr(get_settings(), "admin_session_ttl_hours", 6)
    try:
        return min(max(int(configured), 1), 6)
    except (TypeError, ValueError):
        return 6


def _reader_nightly_expiry(created_at: datetime) -> datetime:
    """Return the first 02:00 cutoff after a reader session is created.

    Reader sessions have a predictable daily boundary in the service's
    configured IANA timezone.  Keeping this deadline derived from
    ``created_at`` means a browser cannot extend a session past the next
    nightly cutoff simply by polling the news feed.
    """
    configured_timezone = getattr(get_settings(), "timezone", "Europe/Berlin")
    try:
        zone: tzinfo = ZoneInfo(configured_timezone)
    except (ZoneInfoNotFoundError, TypeError):
        zone = timezone.utc
    aware_created_at = created_at
    if aware_created_at.tzinfo is None:
        aware_created_at = aware_created_at.replace(tzinfo=timezone.utc)
    local_created_at = aware_created_at.astimezone(zone)
    cutoff = local_created_at.replace(hour=2, minute=0, second=0, microsecond=0)
    if local_created_at >= cutoff:
        cutoff_date = local_created_at.date() + timedelta(days=1)
        cutoff = datetime(cutoff_date.year, cutoff_date.month, cutoff_date.day, 2, tzinfo=zone)
    return cutoff.astimezone(timezone.utc)


async def _audit(user_id: uuid.UUID | None, action: str, *, assistant_id: uuid.UUID | None = None, details: dict | None = None) -> None:
    async with SessionLocal() as session:
        session.add(AdminAuditLog(user_id=user_id, assistant_id=assistant_id, action=action, details=details or {}))
        await session.commit()


async def authenticate(
    request: LoginRequest,
    *,
    require_mfa: bool = True,
    nightly_reader_expiry: bool = False,
) -> tuple[str, AdminUser]:
    settings = get_settings()
    username = request.username.strip().lower()
    async with SessionLocal() as session:
        user = (await session.execute(select(AdminUser).where(AdminUser.username == username))).scalar_one_or_none()
        if (
            user is None
            and settings.admin_bootstrap_password
            and username == settings.admin_bootstrap_username.strip().lower()
            and int(await session.scalar(select(func.count(AdminUser.id))) or 0) == 0
        ):
            # First installation only: the bootstrap password creates the
            # owner account (identified by the owner e-mail). Once any
            # account exists this path is closed permanently.
            user = AdminUser(
                username=username,
                email=owner_email(),
                login_method="both",
                password_hash=_hash_password(settings.admin_bootstrap_password.get_secret_value()),
                role="admin",
            )
            session.add(user)
            await session.flush()
        # Verify the password before revealing the account state, so a
        # disabled or Google-only account cannot be discovered without it.
        password_ok = _check_password(request.password, user.password_hash if user is not None else None)
        if user is None or not password_ok or not password_login_allowed(user):
            raise HTTPException(status_code=401, detail="invalid credentials")
        if not user.active:
            # Return a stable machine-readable code. The backoffice translates
            # it into the selected language without exposing account details.
            raise HTTPException(status_code=403, detail="account_disabled")
        raw = _add_session(session, user, nightly_reader_expiry=nightly_reader_expiry, mfa_required=require_mfa and _mfa_enabled(user))
        await session.commit()
    await _audit(user.id, "admin.login", details={"method": "password"})
    return raw, user


def _add_session(session, user: AdminUser, *, nightly_reader_expiry: bool = False, mfa_required: bool = False) -> str:
    """Stage a new server-side session row and return its raw token."""
    raw = secrets.token_urlsafe(40)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=_admin_session_idle_hours())
    if nightly_reader_expiry:
        expires_at = min(expires_at, _reader_nightly_expiry(now))
    session.add(
        AdminSession(
            user_id=user.id,
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            expires_at=expires_at,
            mfa_verified=not mfa_required,
        )
    )
    return raw


def _cookie_secure() -> bool:
    return get_settings().admin_cookie_secure or get_settings().environment.strip().lower() == "production"


def set_admin_session_cookies(response: Response, raw: str) -> None:
    # Server-side idle expiry is authoritative. A persistent cookie would
    # turn this into an absolute timeout, so use a browser-session cookie and
    # let current_admin enforce the six-hour inactivity boundary.
    response.set_cookie(COOKIE, raw, httponly=True, secure=_cookie_secure(), samesite="strict", path="/")
    # The session token stays HttpOnly. The separate, non-sensitive token is
    # readable by the browser only so the UI can send it in a custom header;
    # cross-site pages cannot read it and therefore cannot forge mutations.
    response.set_cookie(CSRF_COOKIE, new_csrf_token(raw, get_settings()), httponly=False, secure=_cookie_secure(), samesite="strict", path="/")


def set_reader_session_cookie(response: Response, raw: str) -> None:
    response.set_cookie(USER_SESSION_COOKIE, raw, httponly=True, secure=_cookie_secure(), samesite="strict", path="/user")


async def _unique_username(session, base: str) -> str:
    base = re.sub(r"[^a-z0-9_.-]+", "", base.lower())[:60] or "user"
    if len(base) < 3:
        base = f"{base}-user"
    candidate = base
    for _ in range(20):
        if await session.scalar(select(AdminUser.id).where(AdminUser.username == candidate)) is None:
            return candidate
        candidate = f"{base}-{secrets.token_hex(2)}"
    raise HTTPException(status_code=409, detail="could not allocate a username")


async def login_with_google(identity: GoogleIdentity, *, portal: str) -> tuple[str, AdminUser]:
    """Resolve a verified Google identity against the owner-managed allowlist.

    The owner account is created on the first Google sign-in. Every other
    address must have been granted by the owner; the first successful sign-in
    binds the Google subject so a recycled address cannot take the account.
    """
    email = normalize_email(identity.email)
    if not identity.email_verified or not is_gmail(email):
        raise GoogleAuthError("not_gmail")
    owner = email == owner_email()
    async with SessionLocal() as session:
        user = (await session.execute(select(AdminUser).where(AdminUser.email == email).with_for_update())).scalar_one_or_none()
        if user is None and owner:
            user = AdminUser(
                username=await _unique_username(session, email.split("@", 1)[0]),
                email=email,
                login_method="google",
                password_hash=None,
                role="admin",
                active=True,
            )
            session.add(user)
            await session.flush()
        if user is None or (not owner and user.login_method not in {"google", "both"}):
            raise GoogleAuthError("not_allowed")
        if user.google_sub and not hmac.compare_digest(user.google_sub, identity.sub):
            raise GoogleAuthError("not_allowed", "Google account subject does not match")
        if owner:
            # The owner can never be locked out by another administrator.
            user.active = True
            if user.login_method == "password":
                user.login_method = "both"
        if not user.active:
            raise GoogleAuthError("inactive")
        if portal == "user" and not user_portal_access_allowed(user):
            raise GoogleAuthError("not_allowed", "user portal access denied")
        user.google_sub = identity.sub
        raw = _add_session(session, user, nightly_reader_expiry=portal == "user")
        await session.commit()
    await _audit(user.id, "admin.login", details={"method": "google", "portal": portal})
    return raw, user


async def current_admin(token: str | None) -> AdminUser:
    if not token:
        raise HTTPException(status_code=401, detail="authentication required")
    digest = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        result = await session.execute(
            select(AdminSession, AdminUser)
            .join(AdminUser, AdminUser.id == AdminSession.user_id)
            .where(AdminSession.token_hash == digest)
        )
        row = result.one_or_none()
        if row is None:
            raise HTTPException(status_code=401, detail="session expired")
        session_row, user = row
        if not user.active:
            # Deactivation immediately invalidates any race-winning request.
            await session.delete(session_row)
            await session.commit()
            raise HTTPException(status_code=403, detail="account_disabled")
        if session_row.expires_at <= now:
            await session.delete(session_row)
            await session.commit()
            raise HTTPException(status_code=401, detail="session expired")
        # Sliding idle timeout: every authenticated request gets at most six
        # more hours, so six hours without a request always closes the session.
        session_row.expires_at = now + timedelta(hours=_admin_session_idle_hours())
        await session.commit()
    return user


async def reader_login(request: LoginRequest, response: Response) -> dict[str, object]:
    """Create a separate browser session for the read-only news portal.

    The portal deliberately reuses the existing account directory and
    password policy, but stores its token in a different cookie so a reader
    session can never accidentally bootstrap the back-office shell.
    """
    # The reader portal intentionally uses the same password login as the
    # back-office.  Two-step verification is not part of this read-only
    # experience; its endpoint and challenge were removed from the portal.
    raw, user = await authenticate(request, require_mfa=False, nightly_reader_expiry=True)
    if not user_portal_access_allowed(user):
        # ``authenticate`` has already created a session so the normal login
        # flow can remain shared with the admin service. Remove that session
        # immediately when the account has no User-service grant.
        async with SessionLocal() as session:
            await session.execute(
                delete(AdminSession).where(
                    AdminSession.token_hash == hashlib.sha256(raw.encode()).hexdigest()
                )
            )
            await session.commit()
        raise HTTPException(status_code=403, detail="user portal access denied")
    set_reader_session_cookie(response, raw)
    return {"id": str(user.id), "username": user.username, "mfa_required": False, **user_portal_access_payload(user)}


async def current_reader(token: str | None, *, touch: bool = True) -> AdminUser:
    """Resolve a reader session and optionally renew its idle deadline.

    Background notification polling validates the session without touching it,
    so an abandoned browser still expires.  Every request also enforces the
    fixed 02:00 nightly cutoff for the session's creation date.
    """
    if not token:
        raise HTTPException(status_code=401, detail="authentication required")
    digest = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        result = await session.execute(
            select(AdminSession, AdminUser)
            .join(AdminUser, AdminUser.id == AdminSession.user_id)
            .where(AdminSession.token_hash == digest)
        )
        row = result.one_or_none()
        if row is None:
            raise HTTPException(status_code=401, detail="session expired")
        session_row, user = row
        if not user.active:
            await session.delete(session_row)
            await session.commit()
            raise HTTPException(status_code=403, detail="account_disabled")
        if not user_portal_access_allowed(user):
            await session.delete(session_row)
            await session.commit()
            raise HTTPException(status_code=403, detail="user portal access denied")
        if session_row.expires_at <= now or _reader_nightly_expiry(session_row.created_at) <= now:
            await session.delete(session_row)
            await session.commit()
            raise HTTPException(status_code=401, detail="session expired")
        if touch:
            session_row.expires_at = min(
                now + timedelta(hours=_admin_session_idle_hours()),
                _reader_nightly_expiry(session_row.created_at),
            )
            await session.commit()
    return user


async def reader_logout(response: Response, token: str | None) -> dict[str, str]:
    if token:
        async with SessionLocal() as session:
            await session.execute(
                delete(AdminSession).where(
                    AdminSession.token_hash == hashlib.sha256(token.encode()).hexdigest()
                )
            )
            await session.commit()
    response.delete_cookie(USER_SESSION_COOKIE, path="/user")
    return {"status": "logged_out"}


async def verify_mfa_session(code: str, recovery_code: str | None, token: str | None) -> dict[str, object]:
    if not token:
        raise HTTPException(status_code=401, detail="authentication required")
    digest = hashlib.sha256(token.encode()).hexdigest()
    async with SessionLocal() as session:
        row = (await session.execute(select(AdminSession, AdminUser).join(AdminUser, AdminUser.id == AdminSession.user_id).where(AdminSession.token_hash == digest).with_for_update())).one_or_none()
        if row is None:
            raise HTTPException(status_code=401, detail="session expired")
        session_row, user = row
        now = datetime.now(timezone.utc)
        if not user.active:
            await session.delete(session_row)
            await session.commit()
            raise HTTPException(status_code=403, detail="account_disabled")
        if session_row.expires_at <= now:
            await session.delete(session_row)
            await session.commit()
            raise HTTPException(status_code=401, detail="session expired")
        config = (user.preferences or {}).get("mfa") if isinstance(user.preferences, dict) else None
        config = config if isinstance(config, dict) else {}
        if config.get("enabled") is not True or not config.get("secret"):
            session_row.mfa_verified = True
            await session.commit()
            return {"status": "verified", "username": user.username}
        accepted = False
        used_recovery = False
        next_counter = None
        secret = _mfa_decrypt(str(config.get("secret") or ""))
        if secret:
            next_counter = _verify_totp(secret, code, last_counter=int(config.get("last_used_counter") or -1))
            accepted = next_counter is not None
        if not accepted and recovery_code:
            candidate = _recovery_hash(recovery_code)
            hashes = [str(value) for value in config.get("recovery_hashes") or []]
            match = next((value for value in hashes if hmac.compare_digest(value, candidate)), None)
            if match:
                config["recovery_hashes"] = [value for value in hashes if value != match]
                accepted = True
                used_recovery = True
        if not accepted:
            raise HTTPException(status_code=422, detail="invalid mfa code")
        if next_counter is not None:
            config["last_used_counter"] = next_counter
        preferences = dict(user.preferences or {})
        preferences["mfa"] = config
        user.preferences = preferences
        session_row.mfa_verified = True
        session_row.expires_at = now + timedelta(hours=_admin_session_idle_hours())
        await session.commit()
    await _audit(user.id, "admin.mfa.verify", details={"method": "recovery" if used_recovery else "totp"})
    return {"status": "verified", "username": user.username, "used_recovery": used_recovery}


async def reader_assistants(user: AdminUser) -> dict[str, object]:
    """Return only workspaces that the current reader is allowed to follow."""
    if not user_portal_access_allowed(user):
        raise HTTPException(status_code=403, detail="user portal access denied")
    async with SessionLocal() as session:
        statement = select(AssistantWorkspace).where(
            AssistantWorkspace.deleted_at.is_(None),
            AssistantWorkspace.status.in_(("active", "testing")),
        )
        if not is_owner(user):
            statement = (
                statement.join(
                    AssistantMember,
                    AssistantMember.assistant_id == AssistantWorkspace.id,
                )
                .where(AssistantMember.user_id == user.id)
            )
        rows = (await session.execute(statement.order_by(AssistantWorkspace.name))).scalars().unique().all()
    rows = [row for row in rows if str((row.config or {}).get("product") or "").strip().lower() != "bee_cfo"]
    return {
        "count": len(rows),
        "assistants": [
            {
                "id": str(row.id),
                "slug": row.slug,
                "name": row.name,
                "business_name": row.business_name,
                "status": row.status,
            }
            for row in rows
        ],
    }


def _reader_preferences_from_user(user: AdminUser) -> dict[str, object]:
    raw = (user.preferences or {}).get("reader_portal") if isinstance(user.preferences, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    try:
        columns = int(raw.get("columns", 2))
    except (TypeError, ValueError):
        columns = 2
    if columns not in {2, 3, 4}:
        columns = 2
    direction = str(raw.get("text_direction") or "auto")
    if direction not in {"auto", "ltr", "rtl"}:
        direction = "auto"
    theme = str(raw.get("theme") or "honey")
    if theme not in {"honey", "default", "dark", "red"}:
        theme = "honey"
    return {
        "columns": columns,
        "text_direction": direction,
        "notifications": bool(raw.get("notifications", False)),
        "theme": theme,
    }


async def get_reader_preferences(user: AdminUser) -> dict[str, object]:
    """Return only presentation preferences for the authenticated reader."""
    return _reader_preferences_from_user(user)


async def update_reader_preferences(payload: ReaderPreferencesUpdate, user: AdminUser) -> dict[str, object]:
    """Persist reader-owned presentation settings without exposing workspace data."""
    async with SessionLocal() as session:
        item = await session.get(AdminUser, user.id, with_for_update=True)
        if item is None or not item.active:
            raise HTTPException(status_code=401, detail="authentication required")
        current = _reader_preferences_from_user(item)
        changes = payload.model_dump(exclude_none=True)
        current.update(changes)
        preferences = dict(item.preferences or {})
        preferences["reader_portal"] = current
        item.preferences = preferences
        await session.commit()
    await _audit(user.id, "reader.preferences.update", details={"fields": sorted(changes)})
    return current


def _reader_annotation_payload(value: object) -> dict[str, object]:
    """Normalize one private reading state before returning it to the UI."""

    raw = value if isinstance(value, dict) else {}
    return {
        "note": str(raw.get("note") or "")[:6000],
        "tags": [str(item)[:48] for item in (raw.get("tags") or []) if str(item).strip()][:12],
        "highlights": [str(item)[:800] for item in (raw.get("highlights") or []) if str(item).strip()][:20],
        "read_later": bool(raw.get("read_later", False)),
        "updated_at": raw.get("updated_at"),
    }


def _reader_annotation_map(user: AdminUser) -> dict[str, dict[str, object]]:
    raw = (user.preferences or {}).get("reader_annotations") if isinstance(user.preferences, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {str(key): _reader_annotation_payload(value) for key, value in raw.items() if isinstance(value, dict)}


async def list_reader_annotations(assistant_id: uuid.UUID, user: AdminUser) -> dict[str, object]:
    """Return the authenticated reader's private states for one workspace."""

    async with SessionLocal() as session:
        workspace = await session.get(AssistantWorkspace, assistant_id)
        if workspace is None or workspace.deleted_at is not None or workspace.status not in {"active", "testing"}:
            raise HTTPException(status_code=404, detail="assistant not found")
        if str((workspace.config or {}).get("product") or "").strip().lower() == "bee_cfo":
            raise HTTPException(status_code=403, detail="workspace access denied")
        if not is_owner(user):
            member = (
                await session.execute(
                    select(AssistantMember).where(
                        AssistantMember.assistant_id == assistant_id,
                        AssistantMember.user_id == user.id,
                    )
                )
            ).scalar_one_or_none()
            if member is None:
                raise HTTPException(status_code=403, detail="workspace access denied")
        publication_ids = {
            str(value)
            for value in (
                await session.scalars(
                    select(Publication.id).where(
                        Publication.assistant_id == assistant_id,
                        Publication.status == "published",
                    ).order_by(Publication.created_at.desc()).limit(500)
                )
            ).all()
        }
        account = await session.get(AdminUser, user.id)
        states = _reader_annotation_map(account or user)
    states = {key: value for key, value in states.items() if key in publication_ids}
    return {"assistant_id": str(assistant_id), "states": states}


async def update_reader_annotation(
    publication_id: uuid.UUID,
    payload: ReaderAnnotationUpdate,
    user: AdminUser,
) -> dict[str, object]:
    """Persist private deep-reading state after validating publication access."""

    now = datetime.now(timezone.utc).isoformat()
    async with SessionLocal() as session:
        publication = await session.get(Publication, publication_id)
        if publication is None or publication.status != "published":
            raise HTTPException(status_code=404, detail="published item not found")
        workspace = await session.get(AssistantWorkspace, publication.assistant_id)
        if workspace is None or workspace.deleted_at is not None or workspace.status not in {"active", "testing"}:
            raise HTTPException(status_code=403, detail="workspace access denied")
        if str((workspace.config or {}).get("product") or "").strip().lower() == "bee_cfo":
            raise HTTPException(status_code=403, detail="workspace access denied")
        if not is_owner(user):
            member = (
                await session.execute(
                    select(AssistantMember).where(
                        AssistantMember.assistant_id == publication.assistant_id,
                        AssistantMember.user_id == user.id,
                    )
                )
            ).scalar_one_or_none()
            if member is None:
                raise HTTPException(status_code=403, detail="workspace access denied")
        account = await session.get(AdminUser, user.id, with_for_update=True)
        if account is None or not account.active:
            raise HTTPException(status_code=401, detail="authentication required")
        preferences = dict(account.preferences) if isinstance(account.preferences, dict) else {}
        raw_annotations = preferences.get("reader_annotations")
        annotations = dict(raw_annotations) if isinstance(raw_annotations, dict) else {}
        state = {
            "note": payload.note.strip(),
            "tags": list(payload.tags),
            "highlights": list(payload.highlights),
            "read_later": bool(payload.read_later),
            "assistant_id": str(publication.assistant_id),
            "updated_at": now,
        }
        annotations[str(publication_id)] = state
        # Keep the account profile bounded even after long-term use.  The
        # newest 500 article states are enough for a reader and prevent an
        # unbounded JSON profile from slowing every authenticated request.
        if len(annotations) > 500:
            ordered = sorted(
                annotations.items(),
                key=lambda item: str((item[1] or {}).get("updated_at") or ""),
                reverse=True,
            )[:500]
            annotations = dict(ordered)
        preferences["reader_annotations"] = annotations
        account.preferences = preferences
        await session.commit()
    await _audit(
        user.id,
        "reader.annotation.update",
        assistant_id=publication.assistant_id,
        details={
            "publication_id": str(publication_id),
            "has_note": bool(payload.note.strip()),
            "tag_count": len(payload.tags),
            "highlight_count": len(payload.highlights),
            "read_later": bool(payload.read_later),
        },
    )
    return {"publication_id": str(publication_id), "state": _reader_annotation_payload(state)}


async def record_reader_feedback(
    publication_id: uuid.UUID,
    payload: ReaderFeedbackRequest,
    user: AdminUser,
) -> dict[str, object]:
    """Record one user-portal signal for a published item.

    Feedback access is deliberately independent from private reading notes.
    The account username is the stable actor key, so repeated clicks update
    the user's existing signal instead of creating duplicate rows.
    """

    if not user_feedback_access_allowed(user):
        raise HTTPException(status_code=403, detail="user feedback access denied")
    actor_key = str(user.username or "").strip().lower().lstrip("@")[:128]
    if not actor_key:
        raise HTTPException(status_code=422, detail="feedback actor is required")
    async with SessionLocal() as session:
        publication = await session.get(Publication, publication_id)
        if publication is None or publication.status != "published":
            raise HTTPException(status_code=404, detail="published item not found")
        workspace = await session.get(AssistantWorkspace, publication.assistant_id)
        if workspace is None or workspace.deleted_at is not None or workspace.status not in {"active", "testing"}:
            raise HTTPException(status_code=403, detail="workspace access denied")
        if str((workspace.config or {}).get("product") or "").strip().lower() == "bee_cfo":
            raise HTTPException(status_code=403, detail="workspace access denied")
        if not is_owner(user):
            member = (await session.execute(select(AssistantMember).where(AssistantMember.assistant_id == publication.assistant_id, AssistantMember.user_id == user.id))).scalar_one_or_none()
            if member is None:
                raise HTTPException(status_code=403, detail="workspace access denied")
        analysis = await session.get(ArticleAnalysis, publication.analysis_id)
        if analysis is None:
            raise HTTPException(status_code=404, detail="analysis not found")
        item = (await session.execute(select(Feedback).where(Feedback.analysis_id == publication.analysis_id, Feedback.actor_key == actor_key).with_for_update())).scalar_one_or_none()
        if item is None:
            item = Feedback(assistant_id=publication.assistant_id, analysis_id=publication.analysis_id, actor_key=actor_key, value=payload.value, note=payload.note, source="user_portal")
            session.add(item)
        else:
            item.value = payload.value
            item.note = payload.note
            item.source = "user_portal"
        await session.commit()
        feedback_id = item.id
    await _audit(user.id, "reader.feedback", assistant_id=publication.assistant_id, details={"publication_id": str(publication_id), "value": payload.value})
    return {"feedback_id": str(feedback_id), "publication_id": str(publication_id), "value": payload.value, "source": "user_portal"}


def _support_message_payload(message: SupportTicketMessage, *, author_name: str | None) -> dict[str, object]:
    return {
        "id": str(message.id),
        "author_role": message.author_role,
        "author_name": author_name or ("owner" if message.author_role == "owner" else "deleted-user"),
        "body": message.body,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def _support_ticket_payload(
    ticket: SupportTicket,
    *,
    creator: str | None,
    assistant_name: str | None,
    messages: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    thread = list(messages or [])
    # Tickets created before threaded messages were introduced still expose
    # their legacy owner reply as one read-only message in the conversation.
    if not thread and (ticket.owner_reply or "").strip():
        thread.append({
            "id": f"legacy-{ticket.id}",
            "author_role": "owner",
            "author_name": "owner",
            "body": ticket.owner_reply,
            "created_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
        })
    owner_replied = any(item.get("author_role") == "owner" for item in thread)
    return {
        "id": str(ticket.id),
        "ticket_number": f"SUP-{str(ticket.id).split('-')[0].upper()}",
        "category": ticket.category or "other",
        "subject": ticket.subject,
        "body": ticket.body,
        "priority": ticket.priority,
        "status": ticket.status,
        "owner_reply": ticket.owner_reply,
        "messages": thread,
        "message_count": len(thread),
        "owner_replied": owner_replied,
        "is_closed": ticket.status == "closed",
        "created_by": creator or "deleted-user",
        "assistant_id": str(ticket.assistant_id) if ticket.assistant_id else None,
        "assistant_name": assistant_name,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
        "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
    }


SUPPORT_CATEGORY_SUBJECTS = {
    "account_access": "Account and access",
    "project_setup": "Project setup",
    "media_sources": "Media and sources",
    "topics_analysis": "Topics and analysis",
    "schedule_publishing": "Scheduling and publishing",
    "telegram_whatsapp": "Telegram and WhatsApp",
    "feedback_quality": "Feedback and quality",
    "billing_security": "Billing and security",
}


def _support_summary(tickets: list[dict[str, object]]) -> dict[str, object]:
    """Return bounded, UI-ready counts without exposing ticket bodies twice."""
    statuses = {key: 0 for key in ("open", "in_progress", "waiting_user", "answered", "resolved", "closed")}
    priorities = {key: 0 for key in ("low", "normal", "high", "urgent")}
    for ticket in tickets:
        status = str(ticket.get("status") or "open")
        priority = str(ticket.get("priority") or "normal")
        if status in statuses:
            statuses[status] += 1
        if priority in priorities:
            priorities[priority] += 1
    return {"total": len(tickets), "statuses": statuses, "priorities": priorities}


def default_avatar_data(user_id: uuid.UUID | str) -> str:
    """Return one stable, minimal avatar for users without an uploaded image."""
    palettes = (("#2457d6", "#dbe7ff"), ("#0a8f83", "#d8f6f1"), ("#7b61d8", "#eee8ff"), ("#b66a08", "#fff0d2"), ("#d83a56", "#ffe1e7"), ("#334155", "#e2e8f0"), ("#0f766e", "#ccfbf1"), ("#be123c", "#ffe4e6"), ("#4338ca", "#e0e7ff"), ("#92400e", "#fef3c7"))
    index = int(hashlib.sha256(str(user_id).encode()).hexdigest()[:8], 16) % len(palettes)
    primary, background = palettes[index]
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="32" fill="{background}"/><circle cx="32" cy="25" r="11" fill="{primary}"/><path d="M13 57c2-12 10-18 19-18s17 6 19 18" fill="{primary}"/><circle cx="28" cy="23" r="2" fill="white" opacity=".8"/></svg>'
    return "data:image/svg+xml;utf-8," + svg.replace("#", "%23")


async def list_support_tickets(
    user: AdminUser,
    *,
    status: str | None = None,
    priority: str | None = None,
    search: str | None = None,
    limit: int = 100,
) -> dict[str, object]:
    """List tickets with server-side filtering and strict account scoping.

    Owners receive the complete inbox plus their own view. Other accounts
    receive only tickets they created. Filtering happens before the limit so
    the support view remains useful as the inbox grows.
    """
    valid_statuses = {"open", "in_progress", "waiting_user", "answered", "resolved", "closed"}
    valid_priorities = {"low", "normal", "high", "urgent"}
    status = status.strip() if isinstance(status, str) else None
    priority = priority.strip() if isinstance(priority, str) else None
    search = search.strip() if isinstance(search, str) else None
    if status and status not in valid_statuses:
        raise HTTPException(status_code=422, detail="invalid support ticket status")
    if priority and priority not in valid_priorities:
        raise HTTPException(status_code=422, detail="invalid support ticket priority")
    limit = min(max(int(limit or 100), 1), 200)
    async with SessionLocal() as session:
        status_order = case(
            (SupportTicket.status == "open", 0),
            (SupportTicket.status == "in_progress", 1),
            (SupportTicket.status == "waiting_user", 2),
            (SupportTicket.status == "answered", 3),
            (SupportTicket.status == "resolved", 4),
            (SupportTicket.status == "closed", 5),
            else_=5,
        )
        priority_order = case(
            (SupportTicket.priority == "urgent", 0),
            (SupportTicket.priority == "high", 1),
            (SupportTicket.priority == "normal", 2),
            (SupportTicket.priority == "low", 3),
            else_=4,
        )
        statement = (
            select(SupportTicket, AdminUser.username, AssistantWorkspace.name)
            .outerjoin(AdminUser, AdminUser.id == SupportTicket.created_by)
            .outerjoin(AssistantWorkspace, AssistantWorkspace.id == SupportTicket.assistant_id)
            .order_by(status_order, priority_order, SupportTicket.updated_at.desc(), SupportTicket.created_at.desc())
        )
        if not is_owner(user):
            statement = statement.where(SupportTicket.created_by == user.id)
        if status:
            statement = statement.where(SupportTicket.status == status)
        if priority:
            statement = statement.where(SupportTicket.priority == priority)
        if search:
            pattern = f"%{search[:120]}%"
            statement = statement.where(
                or_(
                    SupportTicket.subject.ilike(pattern),
                    SupportTicket.body.ilike(pattern),
                    AdminUser.username.ilike(pattern),
                )
            )
        rows = (await session.execute(statement.limit(limit + 1))).all()
        owner = is_owner(user)
        # Keep the personal queue independent from the owner's inbox limit.
        # Otherwise a busy inbox could push the owner's own tickets past the
        # first page and make the "my tickets" view appear incomplete.
        own_rows = rows
        if owner:
            own_statement = statement.where(SupportTicket.created_by == user.id)
            own_rows = (await session.execute(own_statement.limit(limit + 1))).all()
        # Fetch the complete conversation for the bounded result set in one
        # query.  The UI can then render details without exposing another
        # endpoint or making one request per ticket.
        visible_rows = rows[:limit]
        visible_ids = [ticket.id for ticket, _, _ in visible_rows]
        visible_ids.extend(ticket.id for ticket, _, _ in own_rows[:limit] if ticket.id not in visible_ids)
        message_by_ticket: dict[uuid.UUID, list[dict[str, object]]] = {ticket_id: [] for ticket_id in visible_ids}
        if visible_ids:
            message_rows = (
                await session.execute(
                    select(SupportTicketMessage, AdminUser.username)
                    .outerjoin(AdminUser, AdminUser.id == SupportTicketMessage.author_id)
                    .where(SupportTicketMessage.ticket_id.in_(visible_ids))
                    .order_by(SupportTicketMessage.ticket_id, SupportTicketMessage.created_at.asc())
                )
            ).all()
            for message, author_name in message_rows:
                message_by_ticket.setdefault(message.ticket_id, []).append(
                    _support_message_payload(message, author_name=author_name)
                )
    has_more = len(rows) > limit
    my_has_more = len(own_rows) > limit
    rows = rows[:limit]
    own_rows = own_rows[:limit]
    tickets = [
        _support_ticket_payload(
            ticket,
            creator=creator,
            assistant_name=assistant_name,
            messages=message_by_ticket.get(ticket.id),
        )
        for ticket, creator, assistant_name in rows
    ]
    # Owners need two distinct views in the console: their own requests and
    # the complete inbox they are responsible for. Other roles remain scoped
    # to their own requests and never receive the owner inbox payload.
    own_tickets = [
        _support_ticket_payload(
            ticket,
            creator=creator,
            assistant_name=assistant_name,
            messages=message_by_ticket.get(ticket.id),
        )
        for ticket, creator, assistant_name in own_rows
    ]
    return {
        "count": len(own_tickets),
        "tickets": own_tickets,
        "my_tickets": own_tickets,
        "all_tickets": tickets if owner else [],
        "can_manage": owner,
        "summary": _support_summary(own_tickets),
        "all_summary": _support_summary(tickets) if owner else None,
        "has_more": has_more,
        "my_has_more": my_has_more,
        "limit": limit,
        "filters": {"status": status, "priority": priority, "search": search or ""},
    }


async def create_support_ticket(payload: SupportTicketCreate, user: AdminUser) -> dict[str, object]:
    subject = str(payload.other_subject or "" if payload.category == "other" else payload.subject or SUPPORT_CATEGORY_SUBJECTS[payload.category]).strip()
    if len(subject) < 3:
        raise HTTPException(status_code=422, detail="support ticket subject is required")
    body = payload.body.strip()
    if len(body) < 10:
        raise HTTPException(status_code=422, detail="support ticket description must contain at least 10 characters")
    if payload.assistant_id is not None:
        await _require_assistant_access(payload.assistant_id, user)
    ticket = SupportTicket(
        created_by=user.id,
        assistant_id=payload.assistant_id,
        category=payload.category,
        subject=subject,
        body=body,
        priority=payload.priority,
        status="open",
        owner_reply="",
        updated_at=datetime.now(timezone.utc),
    )
    async with SessionLocal() as session:
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)
    await _audit(user.id, "support.ticket.create", assistant_id=payload.assistant_id, details={"ticket_id": str(ticket.id), "priority": payload.priority})
    return _support_ticket_payload(ticket, creator=user.username, assistant_name=None)


async def update_support_ticket(ticket_id: uuid.UUID, payload: SupportTicketUpdate, user: AdminUser) -> dict[str, object]:
    owner = is_owner(user)
    # Requesters may only perform the terminal action themselves.  They can
    # close their own ticket, but cannot impersonate the owner, rewrite the
    # workflow status, or use the legacy owner_reply field.  All conversation
    # text continues to go through the append-only message endpoint.
    if not owner:
        if payload.owner_reply:
            raise HTTPException(status_code=403, detail="only the owner can reply through this endpoint")
        if payload.status != "closed":
            raise HTTPException(status_code=403, detail="only the owner can change support ticket status")
    reply = payload.owner_reply.strip() if isinstance(payload.owner_reply, str) else None
    if payload.status is None and not reply:
        raise HTTPException(status_code=422, detail="support ticket update is empty")
    async with SessionLocal() as session:
        ticket = await session.get(SupportTicket, ticket_id, with_for_update=True)
        if ticket is None:
            raise HTTPException(status_code=404, detail="support ticket not found")
        creator_user = await session.get(AdminUser, ticket.created_by) if ticket.created_by else None
        creator = creator_user.username if creator_user else None
        assistant = await session.get(AssistantWorkspace, ticket.assistant_id) if ticket.assistant_id else None
        if not owner and ticket.created_by != user.id:
            raise HTTPException(status_code=403, detail="support ticket access denied")
        if not owner and ticket.status == "closed":
            raise HTTPException(status_code=409, detail="closed support tickets cannot be changed")
        previous_status = ticket.status
        changed = False
        if payload.status is not None:
            ticket.status = payload.status
            ticket.resolved_at = datetime.now(timezone.utc) if payload.status in {"resolved", "closed"} else None
            changed = payload.status != previous_status
        if reply:
            message = SupportTicketMessage(
                ticket_id=ticket.id,
                author_id=user.id,
                author_role="owner",
                body=reply,
            )
            session.add(message)
            # Keep the legacy column populated for older integrations, while
            # the message table remains the immutable source of truth.
            ticket.owner_reply = reply
            if payload.status != "closed":
                ticket.status = "answered"
                ticket.resolved_at = None
            changed = True
        ticket.updated_at = datetime.now(timezone.utc)
        if changed:
            if owner and ticket.created_by:
                target = await session.get(AdminUser, ticket.created_by, with_for_update=True)
                if target is not None:
                    preferences = dict(target.preferences or {})
                    inbox = list(preferences.get("global_notifications") or [])
                    inbox.insert(0, {"id": str(uuid.uuid4()), "kind": "support_ticket", "ticket_id": str(ticket.id), "message_key": "support_ticket_updated", "message": "Support ticket updated", "created_at": datetime.now(timezone.utc).isoformat(), "read": False})
                    preferences["global_notifications"] = inbox[:100]
                    target.preferences = preferences
            elif not owner:
                target = (await session.execute(select(AdminUser).where(AdminUser.email == owner_email()).with_for_update())).scalar_one_or_none()
                if target is not None and target.id != user.id:
                    preferences = dict(target.preferences or {})
                    inbox = list(preferences.get("global_notifications") or [])
                    inbox.insert(0, {"id": str(uuid.uuid4()), "kind": "support_ticket", "ticket_id": str(ticket.id), "message_key": "support_ticket_closed", "message": "Support ticket closed by requester", "created_at": datetime.now(timezone.utc).isoformat(), "read": False})
                    preferences["global_notifications"] = inbox[:100]
                    target.preferences = preferences
        await session.flush()
        message_rows = (
            await session.execute(
                select(SupportTicketMessage, AdminUser.username)
                .outerjoin(AdminUser, AdminUser.id == SupportTicketMessage.author_id)
                .where(SupportTicketMessage.ticket_id == ticket.id)
                .order_by(SupportTicketMessage.created_at.asc())
            )
        ).all()
        thread = [_support_message_payload(item, author_name=name) for item, name in message_rows]
        await session.commit()
        await session.refresh(ticket)
    await _audit(user.id, "support.ticket.update", assistant_id=ticket.assistant_id, details={"ticket_id": str(ticket.id), "status": ticket.status})
    return _support_ticket_payload(ticket, creator=creator, assistant_name=assistant.name if assistant else None, messages=thread)


async def add_support_ticket_message(
    ticket_id: uuid.UUID,
    payload: SupportTicketMessageCreate,
    user: AdminUser,
) -> dict[str, object]:
    """Append a reply without ever allowing the original ticket to be edited."""
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="support ticket message cannot be blank")
    owner = is_owner(user)
    async with SessionLocal() as session:
        ticket = await session.get(SupportTicket, ticket_id, with_for_update=True)
        if ticket is None:
            raise HTTPException(status_code=404, detail="support ticket not found")
        if ticket.status == "closed":
            raise HTTPException(status_code=409, detail="closed support tickets cannot be changed")
        if not owner and ticket.created_by != user.id:
            raise HTTPException(status_code=403, detail="support ticket access denied")
        message = SupportTicketMessage(
            ticket_id=ticket.id,
            author_id=user.id,
            author_role="owner" if owner else "requester",
            body=body,
        )
        session.add(message)
        if owner:
            ticket.owner_reply = body
            ticket.status = "answered"
            ticket.resolved_at = None
        else:
            # A requester follow-up puts the ticket back in the owner queue.
            ticket.status = "open"
            ticket.resolved_at = None
        ticket.updated_at = datetime.now(timezone.utc)
        if owner and ticket.created_by:
            target = await session.get(AdminUser, ticket.created_by, with_for_update=True)
            if target is not None:
                preferences = dict(target.preferences or {})
                inbox = list(preferences.get("global_notifications") or [])
                inbox.insert(0, {"id": str(uuid.uuid4()), "kind": "support_ticket", "ticket_id": str(ticket.id), "message_key": "support_ticket_reply", "message": "Support ticket reply received", "created_at": datetime.now(timezone.utc).isoformat(), "read": False})
                preferences["global_notifications"] = inbox[:100]
                target.preferences = preferences
        await session.flush()
        creator_user = await session.get(AdminUser, ticket.created_by) if ticket.created_by else None
        creator_name = creator_user.username if creator_user else None
        assistant = await session.get(AssistantWorkspace, ticket.assistant_id) if ticket.assistant_id else None
        message_rows = (
            await session.execute(
                select(SupportTicketMessage, AdminUser.username)
                .outerjoin(AdminUser, AdminUser.id == SupportTicketMessage.author_id)
                .where(SupportTicketMessage.ticket_id == ticket.id)
                .order_by(SupportTicketMessage.created_at.asc())
            )
        ).all()
        thread = [_support_message_payload(item, author_name=name) for item, name in message_rows]
        await session.commit()
        await session.refresh(ticket)
    await _audit(user.id, "support.ticket.message", assistant_id=ticket.assistant_id, details={"ticket_id": str(ticket.id), "author_role": "owner" if owner else "requester"})
    return _support_ticket_payload(ticket, creator=creator_name, assistant_name=assistant.name if assistant else None, messages=thread)


async def login(request: LoginRequest, response: Response) -> dict[str, object]:
    raw, user = await authenticate(request, require_mfa=False)
    set_admin_session_cookies(response, raw)
    return {
        "id": str(user.id),
        "username": user.username,
        "role": effective_user_role(user),
        "stored_role": user.role,
        "is_owner": is_owner(user),
        "avatar_url": (user.preferences or {}).get("avatar_url") or default_avatar_data(user.id),
        "mfa_required": False,
    }


async def logout(response: Response, token: str | None) -> dict[str, str]:
    if token:
        async with SessionLocal() as session:
            await session.execute(delete(AdminSession).where(AdminSession.token_hash == hashlib.sha256(token.encode()).hexdigest()))
            await session.commit()
    response.delete_cookie(COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"status": "logged_out"}


async def change_password(user: AdminUser, payload: ChangePasswordRequest) -> dict[str, str]:
    if not _check_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=422, detail="new password must differ from current password")
    async with SessionLocal() as session:
        item = await session.get(AdminUser, user.id, with_for_update=True)
        if item is None or not item.active:
            raise HTTPException(status_code=404, detail="admin user not found")
        item.password_hash = _hash_password(payload.new_password)
        # A password rotation is a credential-compromise boundary. Revoke the
        # current session and every other session so the new password is the
        # only remaining authentication path.
        await session.execute(delete(AdminSession).where(AdminSession.user_id == user.id))
        await session.commit()
    await _audit(user.id, "admin.password.change")
    return {"status": "password_changed"}


async def change_user_password(user_id: uuid.UUID, payload: AdminUserPasswordUpdate, user: AdminUser) -> dict[str, str]:
    """Allow an administrator to rotate a user's password from the user directory."""
    if not is_owner(user) and user.role not in {"admin", "assistant_admin"}:
        raise HTTPException(status_code=403, detail="project admin role required")
    if user_id == user.id:
        # Self-service rotation must prove the current password.
        raise HTTPException(status_code=422, detail="use the change-password form for your own account")
    async with SessionLocal() as session:
        item = await session.get(AdminUser, user_id, with_for_update=True)
        if item is None or not item.active:
            raise HTTPException(status_code=404, detail="admin user not found")
        await _ensure_user_manage_scope(session, user_id, user)
        if is_owner(item) and not is_owner(user):
            raise HTTPException(status_code=403, detail="the owner password can only be changed by the owner")
        ensure_can_manage_account(user, item)
        item.password_hash = _hash_password(payload.new_password)
        await session.execute(delete(AdminSession).where(AdminSession.user_id == user_id))
        await session.commit()
    await _audit(user.id, "admin_user.password.rotate", details={"user_id": str(user_id)})
    return {"status": "password_changed", "user_id": str(user_id)}


async def assistants(user: AdminUser) -> dict[str, object]:
    async with SessionLocal() as session:
        retention_cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        statement = select(AssistantWorkspace).where(
            (AssistantWorkspace.deleted_at.is_(None))
            | (AssistantWorkspace.deleted_at >= retention_cutoff if is_owner(user) else False)
        ).order_by(AssistantWorkspace.deleted_at.is_not(None), AssistantWorkspace.created_at.desc())
        member_roles: dict[uuid.UUID, str] = {}
        if not is_global_admin(user):
            statement = statement.join(AssistantMember, AssistantMember.assistant_id == AssistantWorkspace.id).where(AssistantMember.user_id == user.id)
            memberships = (await session.execute(
                select(AssistantMember.assistant_id, AssistantMember.role).where(AssistantMember.user_id == user.id)
            )).all()
            member_roles = {assistant_id: role for assistant_id, role in memberships}
        rows = (await session.execute(statement)).scalars().unique().all()
    # Bee CFO is a separate bounded context. It shares the service process
    # but has no Bee Researcher back-office UI, so never expose its workspace
    # in the Researcher project selector. This also prevents a newly-created
    # Bee CFO workspace from becoming the default empty media/topics view.
    rows = [row for row in rows if str((row.config or {}).get("product") or "").strip().lower() != "bee_cfo"]
    return {"count": len(rows), "assistants": [{"id": str(x.id), "slug": x.slug, "name": x.name, "business_name": x.business_name, "description": x.description, "status": x.status, "config": x.config, "deleted_at": x.deleted_at.isoformat() if x.deleted_at else None, "can_delete": (not x.deleted_at) and workspace_delete_allowed(effective_user_role(user), member_roles.get(x.id), owner=is_owner(user)), "can_restore": bool(x.deleted_at and is_owner(user)), "can_permanent_delete": bool(x.deleted_at and is_owner(user)), "created_at": x.created_at.isoformat(), "updated_at": x.updated_at.isoformat()} for x in rows]}


async def assistant_readiness(assistant_id: uuid.UUID, user: AdminUser) -> dict[str, object]:
    """Expose a safe preflight contract for newly-created workspaces."""
    await _require_assistant_access(assistant_id, user)
    async with SessionLocal() as session:
        assistant = await session.get(AssistantWorkspace, assistant_id)
        if assistant is None:
            raise HTTPException(status_code=404, detail="assistant not found")
        if assistant.deleted_at is not None and not is_owner(user):
            raise HTTPException(status_code=404, detail="assistant not found")
        source_count = int((await session.execute(select(func.count(Source.id)).where(Source.assistant_id == assistant_id))).scalar_one())
        topic_count = int((await session.execute(select(func.count(Topic.id)).where(Topic.assistant_id == assistant_id))).scalar_one())
        profile_count = int((await session.execute(select(func.count(BusinessProfile.id)).where(BusinessProfile.assistant_id == assistant_id))).scalar_one())
    config = assistant.config or {}
    # Readiness must reflect the same *effective* destinations used by the
    # delivery pipeline.  The original workspace predates per-assistant
    # Telegram settings and intentionally inherits server-managed channels;
    # inspecting only the JSON stored on the workspace made it look unready
    # even though publishing was correctly configured.  Keep this in sync
    # through _telegram_config, which also preserves isolation for new
    # workspaces and explicit empty overrides.
    telegram = _telegram_config(config, assistant_id=assistant_id)
    runtime = config.get("runtime") or {}
    # A market-news assistant may operate without a business profile.  An
    # empty workspace business name is the explicit opt-in to general-market
    # mode; populated workspaces still get the useful missing-profile signal.
    business_optional = not str(assistant.business_name or "").strip()
    checks = {
        "business_profile": profile_count > 0 or business_optional,
        "sources": source_count > 0,
        "topics": topic_count > 0,
        "feedback_channel": bool(telegram.get("feedback_channel_id")),
        "observer_channel": bool(telegram.get("observer_channel_id")),
        "runtime_settings": all(key in runtime for key in ("max_items_per_run", "analysis_model", "schedule_slots")),
        "activation": assistant.status in {"active", "testing"},
    }
    missing = [key for key, ok in checks.items() if not ok]
    return {
        "assistant_id": str(assistant_id),
        "status": assistant.status,
        "ready": not missing,
        "checks": checks,
        "missing": missing,
        "counts": {"business_profiles": profile_count, "sources": source_count, "topics": topic_count},
        "secrets": {"telegram_token": "server_env_only"},
        "business_mode": "general_market" if business_optional and profile_count == 0 else "business_context",
    }


async def _require_assistant_access(assistant_id: uuid.UUID, user: AdminUser, *, write: bool = False) -> AssistantWorkspace:
    async with SessionLocal() as session:
        assistant = await session.get(AssistantWorkspace, assistant_id)
        if assistant is None:
            raise HTTPException(status_code=404, detail="assistant not found")
        if assistant.deleted_at is not None and not is_owner(user):
            raise HTTPException(status_code=404, detail="assistant not found")
        if is_global_admin(user):
            return assistant
        member = (await session.execute(select(AssistantMember).where(AssistantMember.assistant_id == assistant_id, AssistantMember.user_id == user.id))).scalar_one_or_none()
        if member is None:
            raise HTTPException(status_code=403, detail="workspace access denied")
        if write and not workspace_write_allowed(effective_user_role(user), member.role):
            raise HTTPException(status_code=403, detail="workspace is read-only for this role")
        return assistant


async def _require_project_admin(assistant_id: uuid.UUID, user: AdminUser) -> AssistantWorkspace:
    """Require owner or an explicitly assigned project administrator."""
    assistant = await _require_assistant_access(assistant_id, user, write=True)
    if is_owner(user):
        return assistant
    async with SessionLocal() as session:
        member = (await session.execute(select(AssistantMember).where(AssistantMember.assistant_id == assistant_id, AssistantMember.user_id == user.id))).scalar_one_or_none()
    if not workspace_delete_allowed(effective_user_role(user), member.role if member else None):
        raise HTTPException(status_code=403, detail="project admin role required")
    return assistant


async def feedback_learning_center(assistant_id: uuid.UUID, user: AdminUser, *, days: int = 30) -> dict[str, object]:
    """Return explainable feedback metrics and the last safe ranking change."""
    await _require_assistant_access(assistant_id, user)
    from app.pipeline_service import feedback_daily_report

    days = max(1, min(days, 30))
    report = await feedback_daily_report(days=days, assistant_id=assistant_id)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    by_source: list[dict[str, object]] = []
    for row in _mapping_rows(report.get("by_source")):
        count = _safe_int_value(row.get("count"))
        by_source.append({"source": row.get("source") or "unknown", "samples": count, "precision": None})
    # Source-level precision needs the same joins as the report. Keep it
    # bounded and read-only so this screen cannot change production ranking.
    async with SessionLocal() as session:
        source_feedback = (await session.execute(
            select(
                Feedback.source,
                func.count(Feedback.id),
                func.sum(case((Feedback.value == "up", 1), else_=0)),
                func.sum(case((Feedback.value == "down", 1), else_=0)),
            ).where(Feedback.assistant_id == assistant_id, Feedback.created_at >= cutoff).group_by(Feedback.source).order_by(func.count(Feedback.id).desc())
        )).all()
        latest = (await session.execute(
            select(JobRun).where(JobRun.job_type == "feedback_ranking", JobRun.status == "succeeded").order_by(JobRun.finished_at.desc()).limit(1)
        )).scalars().first()
    by_source = [
        {
            "source": source or "unknown",
            "samples": int(total or 0),
            "related": int(up or 0),
            "unrelated": int(down or 0),
            "precision": round(int(up or 0) / int(total or 1), 4),
        }
        for source, total, up, down in source_feedback
    ]
    latest_result = latest.result if latest is not None and isinstance(latest.result, dict) else None
    return {
        "status": "learning_center",
        "assistant_id": str(assistant_id),
        "period_days": days,
        "report": report,
        "by_source": by_source,
        "last_ranking_change": {
            "available": bool(latest_result and latest_result.get("score_changes")),
            "job_id": str(latest.id) if latest is not None else None,
            "finished_at": latest.finished_at.isoformat() if latest and latest.finished_at else None,
            "topics_changed": int((latest_result or {}).get("topics_changed") or 0),
        },
        "production_mutated": False,
    }


async def rollback_feedback_ranking(user: AdminUser) -> dict[str, object]:
    """Restore the latest bounded ranking change, when a score snapshot exists."""
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="owner role required")
    async with SessionLocal() as session:
        job = (await session.execute(
            select(JobRun).where(JobRun.job_type == "feedback_ranking", JobRun.status == "succeeded").order_by(JobRun.finished_at.desc()).limit(1)
        )).scalars().first()
        result = job.result if job is not None and isinstance(job.result, dict) else {}
        changes = result.get("score_changes") if isinstance(result, dict) else None
        if job is None or not changes:
            raise HTTPException(status_code=409, detail="no reversible feedback ranking change is available")
        restored = 0
        for change in changes:
            try:
                score_id = uuid.UUID(str(change["score_id"]))
                before = float(change["before"])
            except (KeyError, TypeError, ValueError):
                continue
            restored += int((await session.execute(
                update(ArticleTopic).where(ArticleTopic.id == score_id).values(combined_score=before)
            )).rowcount or 0)
        await session.commit()
    await _audit(user.id, "feedback.ranking.rollback", details={"job_id": str(job.id), "restored": restored})
    return {"status": "rolled_back", "job_id": str(job.id), "restored_scores": restored}


async def list_event_clusters(assistant_id: uuid.UUID, user: AdminUser, *, limit: int = 50) -> dict[str, object]:
    """Return event narratives with their source evidence for review."""
    await _require_assistant_access(assistant_id, user)
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(EventCluster).where(EventCluster.assistant_id == assistant_id).order_by(EventCluster.updated_at.desc()).limit(max(1, min(limit, 100)))
        )).scalars().all()
        cluster_ids = [row.id for row in rows]
        members: list[Any] = []
        if cluster_ids:
            members.extend((await session.execute(
                select(ClusterMember, NormalizedArticle, SourceItem, Source)
                .join(NormalizedArticle, NormalizedArticle.id == ClusterMember.article_id)
                .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
                .join(Source, Source.id == SourceItem.source_id)
                .where(ClusterMember.assistant_id == assistant_id, ClusterMember.cluster_id.in_(cluster_ids))
                .order_by(NormalizedArticle.published_at.desc())
            )).all())
    grouped: dict[uuid.UUID, list[dict[str, object]]] = {row.id: [] for row in rows}
    for member, article, _item, source in members:
        grouped.setdefault(member.cluster_id, []).append({
            "article_id": str(article.id),
            "title": article.title,
            "source": source.name,
            "url": article.canonical_url,
            "similarity": round(float(member.similarity or 0), 4),
            "published_at": article.published_at.isoformat() if article.published_at else None,
        })
    return {
        "assistant_id": str(assistant_id),
        "clusters": [
            {
                "id": str(row.id),
                "headline": row.headline,
                "source_count": int(row.source_count or 0),
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "members": grouped.get(row.id, []),
                "publish_once": True,
            }
            for row in rows
        ],
    }


def _privacy_defaults(config: dict | None) -> dict[str, object]:
    raw = (config or {}).get("privacy") if isinstance(config, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    retention_days, retention_source = effective_retention_days(config)
    return {
        "retention_days": retention_days,
        "retention_source": retention_source,
        "default_retention_days": int(get_settings().normalized_retention_days),
        "min_retention_days": MIN_RETENTION_DAYS,
        "data_region": str(raw.get("data_region") or "unspecified")[:64],
        "export_enabled": bool(raw.get("export_enabled", True)),
    }


async def get_privacy_settings(assistant_id: uuid.UUID, user: AdminUser) -> dict[str, object]:
    assistant = await _require_assistant_access(assistant_id, user)
    return {"assistant_id": str(assistant_id), **_privacy_defaults(assistant.config)}


async def update_privacy_settings(assistant_id: uuid.UUID, payload: PrivacySettingsUpdate, user: AdminUser) -> dict[str, object]:
    assistant = await _require_project_admin(assistant_id, user)
    async with SessionLocal() as session:
        item = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        if item is None:
            raise HTTPException(status_code=404, detail="assistant not found")
        config = dict(item.config or {})
        # Persist only values that were explicitly chosen; an unset
        # retention keeps following the deployment default.
        stored = dict(config.get("privacy") or {}) if isinstance(config.get("privacy"), dict) else {}
        changes = payload.model_dump(exclude_none=True)
        previous_retention = effective_retention_days(config)[0]
        stored.update(changes)
        stored = {key: stored[key] for key in ("retention_days", "data_region", "export_enabled") if key in stored}
        config["privacy"] = stored
        item.config = config
        await session.commit()
    effective = _privacy_defaults(config)
    await _audit(
        user.id,
        "privacy.settings.update",
        assistant_id=assistant_id,
        details={"fields": sorted(changes), "retention_days_before": previous_retention, "retention_days_after": effective["retention_days"]},
    )
    return {"assistant_id": str(assistant_id), **effective}


async def export_assistant_data(assistant_id: uuid.UUID, user: AdminUser) -> dict[str, object]:
    assistant = await _require_assistant_access(assistant_id, user)
    privacy = _privacy_defaults(assistant.config)
    if not privacy["export_enabled"]:
        raise HTTPException(status_code=403, detail="data export is disabled for this project")
    async with SessionLocal() as session:
        profiles = (await session.execute(select(BusinessProfile).where(BusinessProfile.assistant_id == assistant_id))).scalars().all()
        sources = (await session.execute(select(Source).where(Source.assistant_id == assistant_id))).scalars().all()
        topics = (await session.execute(select(Topic).where(Topic.assistant_id == assistant_id))).scalars().all()
        feedback = (await session.execute(select(Feedback).where(Feedback.assistant_id == assistant_id).order_by(Feedback.created_at.desc()).limit(500))).scalars().all()
        counts = {}
        for label, model in (("articles", NormalizedArticle), ("analyses", ArticleAnalysis), ("publications", Publication), ("feedback", Feedback), ("clusters", EventCluster)):
            counts[label] = int((await session.scalar(select(func.count(model.id)).where(model.assistant_id == assistant_id))) or 0)
    payload: dict[str, object] = {
        "export_version": "1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "assistant": {"id": str(assistant.id), "slug": assistant.slug, "name": assistant.name, "business_name": assistant.business_name, "description": assistant.description},
        "privacy": privacy,
        "counts": counts,
        "business_profiles": [_business_payload(row) for row in profiles],
        "sources": [{"source_key": row.source_key, "name": row.name, "homepage_url": row.homepage_url, "fetch_url": row.fetch_url, "enabled": row.enabled} for row in sources],
        "topics": [{"topic_key": row.topic_key, "name": row.name, "definition": row.definition, "positive_terms": row.positive_terms, "negative_terms": row.negative_terms, "threshold": row.threshold, "enabled": row.enabled} for row in topics],
        "feedback": [{"id": str(row.id), "analysis_id": str(row.analysis_id), "actor_key": row.actor_key, "value": row.value, "note": row.note, "source": row.source, "created_at": row.created_at.isoformat() if row.created_at else None} for row in feedback],
    }
    await _audit(user.id, "privacy.data.export", assistant_id=assistant_id, details={"counts": counts})
    return payload


async def _project_admin_scope_ids(session, user: AdminUser) -> set[uuid.UUID] | None:
    """Return project IDs an admin may administer; ``None`` means owner-wide."""
    if is_owner(user):
        return None
    if user.role not in {"admin", "assistant_admin"}:
        return set()
    rows = (await session.execute(
        select(AssistantMember.assistant_id).where(
            AssistantMember.user_id == user.id,
            AssistantMember.role.in_(["admin", "assistant_admin"]),
        )
    )).scalars().all()
    return set(rows)


async def _visible_project_scope_ids(session, user: AdminUser) -> set[uuid.UUID] | None:
    """Return projects whose members may be visible in the security page.

    Read visibility follows the user's actual project memberships, while
    mutation scope remains restricted to project-admin roles above.
    """
    if is_owner(user):
        return None
    rows = (await session.execute(
        select(AssistantMember.assistant_id).where(AssistantMember.user_id == user.id)
    )).scalars().all()
    return set(rows)


async def _ensure_user_manage_scope(session, target_user_id: uuid.UUID, user: AdminUser) -> set[uuid.UUID] | None:
    """Ensure a project admin only manages users sharing an assigned project."""
    scope = await _project_admin_scope_ids(session, user)
    if scope is None:
        return None
    if not scope:
        raise HTTPException(status_code=403, detail="project admin role required")
    if target_user_id == user.id:
        return scope
    target_projects = set((await session.execute(
        select(AssistantMember.assistant_id).where(
            AssistantMember.user_id == target_user_id,
            AssistantMember.assistant_id.in_(scope),
        )
    )).scalars().all())
    if not target_projects:
        raise HTTPException(status_code=403, detail="user is outside your project scope")
    return scope


async def _copy_workspace_catalog(session, source_assistant_id: uuid.UUID, target_assistant_id: uuid.UUID, source_revision: str) -> tuple[int, int]:
    """Copy reusable media/topics into a new workspace without operational state or secrets."""
    source_rows = (await session.execute(select(Source).where(Source.assistant_id == source_assistant_id).order_by(Source.display_order, Source.source_key))).scalars().all()
    topic_rows = (await session.execute(select(Topic).where(Topic.assistant_id == source_assistant_id).order_by(Topic.display_order, Topic.topic_key))).scalars().all()
    for source in source_rows:
        session.add(Source(
            assistant_id=target_assistant_id,
            source_key=source.source_key,
            name=source.name,
            homepage_url=source.homepage_url,
            fetch_url=source.fetch_url,
            adapter=source.adapter,
            item_url_pattern=source.item_url_pattern,
            item_title_class_pattern=source.item_title_class_pattern,
            language=source.language,
            output_language=source.output_language,
            region=source.region,
            priority=source.priority,
            display_order=source.display_order,
            enabled=source.enabled,
            access_policy=source.access_policy,
            access_notes=source.access_notes,
            robots_policy=source.robots_policy,
            rate_limit_seconds=source.rate_limit_seconds,
            request_timeout_seconds=source.request_timeout_seconds,
            max_retries=source.max_retries,
            health_status="unknown",
            last_success_at=None,
            last_error=None,
        ))
    for topic in topic_rows:
        session.add(Topic(
            assistant_id=target_assistant_id,
            topic_key=topic.topic_key,
            name=topic.name,
            definition=topic.definition,
            positive_terms=list(topic.positive_terms or []),
            negative_terms=list(topic.negative_terms or []),
            importance=topic.importance,
            display_order=topic.display_order,
            threshold=topic.threshold,
            enabled=topic.enabled,
            source_revision=source_revision,
        ))
    return len(source_rows), len(topic_rows)


async def create_assistant(payload: AssistantRequest, user: AdminUser) -> dict[str, object]:
    async with SessionLocal() as session:
        # The owner chooses the account-wide project ceiling from the owner
        # settings page.  Until one exists, keep the safe default of ten.
        existing_projects = int(await session.scalar(
            select(func.count(AssistantWorkspace.id)).where(AssistantWorkspace.deleted_at.is_(None))
        ) or 0)
        reference = (await session.execute(
            select(AssistantWorkspace).where(AssistantWorkspace.deleted_at.is_(None)).order_by(AssistantWorkspace.created_at)
        )).scalars().first()
        project_limit = assistant_limits(reference.config if reference else None)["max_projects_per_user"]
        if existing_projects >= project_limit:
            raise HTTPException(status_code=409, detail=f"project limit reached ({project_limit})")
        config = _sanitize_template_config(payload.config or {})
        runtime = dict(config.get("runtime") or {}) if isinstance(config, dict) else {}
        runtime.setdefault("max_items_per_run", get_settings().max_items_per_run)
        runtime.setdefault("analysis_model", get_settings().analysis_model)
        # The first active run must backfill the configured freshness window
        # instead of waiting for the next ordinary schedule slot.
        runtime["bootstrap_pending"] = True
        # A newly created project must never inherit feedback actors from the
        # global/default project.  Users are explicitly configured per project.
        runtime["allowed_feedback_usernames"] = []
        runtime.setdefault("schedule_slots", [])
        config = {**(config if isinstance(config, dict) else {}), "runtime": runtime, "telegram": {}, "limits": dict(DEFAULT_ASSISTANT_LIMITS)}
        item = AssistantWorkspace(
            slug=payload.slug,
            name=payload.name,
            business_name=payload.business_name.strip(),
            description=payload.description,
            config=config,
        )
        session.add(item)
        await session.flush()
        # A new assistant is an empty, isolated workspace.  The business name
        # above is workspace metadata only; profiles, media and topics must be
        # added explicitly by the owner instead of being copied from Dotin.
        source_count, topic_count = 0, 0
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            constraint = str(getattr(exc, "orig", exc)).lower()
            if "uq_mi_assistant_workspaces_slug" in constraint or "assistant_workspaces_slug" in constraint:
                raise HTTPException(status_code=409, detail="assistant slug already exists") from exc
            raise HTTPException(status_code=409, detail="project could not be created because its template data conflicts with existing data") from exc
    await _audit(user.id, "assistant.create", assistant_id=item.id, details={"slug": item.slug})
    return {"id": str(item.id), "slug": item.slug, "status": item.status, "sources_copied": source_count, "topics_copied": topic_count}


_SECRET_CONFIG_KEYS = {"token", "secret", "password", "api_key", "bot_token", "channel_id", "webhook"}

# Workspace configuration keys that the generic project PATCH may change.
# Everything else (runtime, limits, telegram, sandbox, share_links,
# notifications, privacy, templates, knowledge, product, ...) belongs to a
# dedicated endpoint with its own authorization and is left untouched.
_FREEFORM_CONFIG_KEYS = frozenset({"shortcut_mission", "suggested_sources", "suggested_topics"})


def merge_workspace_config(current: dict | None, incoming: object) -> tuple[dict, set[str]]:
    """Merge only free-form keys; return the new config and ignored keys."""
    merged = dict(current or {})
    if not isinstance(incoming, dict):
        return merged, set()
    ignored: set[str] = set()
    for key, value in incoming.items():
        key = str(key)
        if key not in _FREEFORM_CONFIG_KEYS:
            if merged.get(key) != value:
                ignored.add(key)
            continue
        merged[key] = _sanitize_template_config(value)
    return merged, ignored


def _sanitize_template_config(value: object) -> object:
    """Copy workspace configuration without carrying credentials or destinations."""
    if isinstance(value, dict):
        cleaned: dict[str, object] = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(secret in normalized for secret in _SECRET_CONFIG_KEYS):
                continue
            cleaned[str(key)] = _sanitize_template_config(item)
        return cleaned
    if isinstance(value, list):
        return [_sanitize_template_config(item) for item in value]
    return value


async def clone_assistant(source_id: uuid.UUID, payload: AssistantCloneRequest, user: AdminUser) -> dict[str, object]:
    async with SessionLocal() as session:
        existing_projects = int(await session.scalar(select(func.count(AssistantWorkspace.id)).where(AssistantWorkspace.deleted_at.is_(None))) or 0)
        reference = (await session.execute(select(AssistantWorkspace).where(AssistantWorkspace.deleted_at.is_(None)).order_by(AssistantWorkspace.created_at))).scalars().first()
        project_limit = assistant_limits(reference.config if reference else None)["max_projects_per_user"]
        if existing_projects >= project_limit:
            raise HTTPException(status_code=409, detail=f"project limit reached ({project_limit})")
        source = await session.get(AssistantWorkspace, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="source assistant not found")
        template_config = _sanitize_template_config(source.config)
        if not isinstance(template_config, dict):
            template_config = {}
        template_config["telegram"] = {}
        template_runtime = dict(template_config.get("runtime") or {})
        template_runtime.setdefault("max_items_per_run", get_settings().max_items_per_run)
        template_runtime.setdefault("analysis_model", get_settings().analysis_model)
        # Feedback actors are project-specific and must never be cloned from
        # the source workspace.
        template_runtime["allowed_feedback_usernames"] = []
        template_runtime["schedule_slots"] = []
        template_runtime["bootstrap_pending"] = True
        template_config["runtime"] = template_runtime
        sandbox_config = {
            "enabled": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_assistant_id": str(source_id),
            "publication_mode": "dry_run",
        } if payload.sandbox else None
        item = AssistantWorkspace(
            slug=payload.slug,
            name=(f"[Sandbox] {payload.name}" if payload.sandbox else payload.name),
            business_name=payload.business_name,
            description=payload.description,
            status="testing" if payload.sandbox else "draft",
            config={"template_source": str(source.id), "template_version": 1, **template_config, **({"sandbox": sandbox_config} if sandbox_config else {})},
        )
        session.add(item)
        await session.flush()
        source_profile = await session.scalar(select(BusinessProfile).where(BusinessProfile.assistant_id == source_id).order_by(BusinessProfile.id))
        next_profile_id = int((await session.scalar(select(func.max(BusinessProfile.id)))) or 0) + 1
        if source_profile is not None:
            session.add(BusinessProfile(
                id=next_profile_id,
                assistant_id=item.id,
                business_name=payload.business_name,
                description=source_profile.description,
                products_services=source_profile.products_services,
                target_customers=source_profile.target_customers,
                markets=source_profile.markets,
                revenue_model=source_profile.revenue_model,
                strategic_goals=source_profile.strategic_goals,
                competitors=list(source_profile.competitors or []),
                sensitivities=list(source_profile.sensitivities or []),
                output_language=source_profile.output_language,
                output_tone=source_profile.output_tone,
                source_revision="assistant-clone-template",
            ))
            item.config = {**(item.config or {}), "active_business_id": next_profile_id}
        source_count, topic_count = await _copy_workspace_catalog(session, source_id, item.id, "assistant-clone-template")
        try:
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise HTTPException(status_code=409, detail="assistant slug already exists") from exc
    await _audit(user.id, "assistant.clone", assistant_id=item.id, details={"source_assistant_id": str(source_id), "template_version": 1, "sandbox": payload.sandbox})
    return {"id": str(item.id), "slug": item.slug, "name": item.name, "status": item.status, "sandbox": payload.sandbox, "source_assistant_id": str(source_id), "template_version": 1, "sources_copied": source_count, "topics_copied": topic_count}


async def list_assistant_members(assistant_id: uuid.UUID, user: AdminUser) -> dict[str, object]:
    await _require_project_admin(assistant_id, user)
    async with SessionLocal() as session:
        if await session.get(AssistantWorkspace, assistant_id) is None:
            raise HTTPException(status_code=404, detail="assistant not found")
        rows = (await session.execute(select(AssistantMember, AdminUser).join(AdminUser, AdminUser.id == AssistantMember.user_id).where(AssistantMember.assistant_id == assistant_id).order_by(AdminUser.username))).all()
    return {"assistant_id": str(assistant_id), "count": len(rows), "members": [{"id": str(member.id), "user_id": str(member.user_id), "username": admin.username, "role": member.role} for member, admin in rows]}


async def assign_assistant_member(assistant_id: uuid.UUID, payload: AssistantMemberRequest, user: AdminUser) -> dict[str, object]:
    await _require_project_admin(assistant_id, user)
    if not is_owner(user) and _ROLE_RANK.get(payload.role, 0) >= role_rank(user):
        raise HTTPException(status_code=403, detail="cannot grant a role equal to or higher than your own")
    async with SessionLocal() as session:
        if await session.get(AssistantWorkspace, assistant_id) is None:
            raise HTTPException(status_code=404, detail="assistant not found")
        target = await session.get(AdminUser, payload.user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="user not found")
        ensure_can_manage_account(user, target)
        member = (await session.execute(select(AssistantMember).where(AssistantMember.assistant_id == assistant_id, AssistantMember.user_id == payload.user_id))).scalar_one_or_none()
        if member is None:
            member = AssistantMember(assistant_id=assistant_id, user_id=payload.user_id, role=payload.role)
            session.add(member)
        else:
            member.role = payload.role
        await session.commit()
    await _audit(user.id, "assistant.member.assign", assistant_id=assistant_id, details={"user_id": str(payload.user_id), "role": payload.role})
    return {"assistant_id": str(assistant_id), "user_id": str(payload.user_id), "role": payload.role}


async def remove_assistant_member(assistant_id: uuid.UUID, user_id: uuid.UUID, user: AdminUser) -> dict[str, str]:
    """Revoke a user's access to one workspace without touching their account."""
    await _require_project_admin(assistant_id, user)
    async with SessionLocal() as session:
        member = (await session.execute(
            select(AssistantMember).where(
                AssistantMember.assistant_id == assistant_id,
                AssistantMember.user_id == user_id,
            ).with_for_update()
        )).scalar_one_or_none()
        if member is None:
            raise HTTPException(status_code=404, detail="workspace membership not found")
        target = await session.get(AdminUser, user_id)
        if target is not None:
            ensure_can_manage_account(user, target)
        await session.delete(member)
        await session.commit()
    await _audit(user.id, "assistant.member.remove", assistant_id=assistant_id, details={"user_id": str(user_id)})
    return {"assistant_id": str(assistant_id), "user_id": str(user_id), "status": "removed"}


async def update_assistant(assistant_id: uuid.UUID, payload: AssistantUpdate, user: AdminUser) -> dict[str, object]:
    await _require_project_admin(assistant_id, user)
    async with SessionLocal() as session:
        item = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        if item is None:
            raise HTTPException(status_code=404, detail="assistant not found")
        changes = payload.model_dump(exclude_none=True)
        if "slug" in changes:
            changes["slug"] = str(changes["slug"]).strip().lower()
        if "config" in changes:
            # Never replace the stored configuration wholesale: the edit form
            # round-trips a possibly stale copy, and most keys are governed
            # by dedicated, separately authorized endpoints.
            current = dict(item.config or {})
            merged, ignored = merge_workspace_config(current, changes.pop("config"))
            changed_keys = sorted(key for key in set(merged) | set(current) if merged.get(key) != current.get(key))
            if changed_keys:
                item.config = merged
                changes["config"] = changed_keys
            if ignored:
                changes["config_ignored"] = sorted(ignored)
        for key, value in changes.items():
            if key not in {"config", "config_ignored"}:
                setattr(item, key, value)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            if "slug" in changes:
                raise HTTPException(status_code=409, detail="assistant slug already exists") from exc
            raise HTTPException(status_code=409, detail="assistant update conflicts with existing data") from exc
    await _audit(user.id, "assistant.update", assistant_id=assistant_id, details={"fields": sorted(changes)})
    return {"id": str(item.id), "slug": item.slug, "status": item.status, "updated_fields": sorted(changes)}


async def delete_assistant(assistant_id: uuid.UUID, user: AdminUser) -> dict[str, str]:
    # Deletion is an administrative workspace action: an admin may delete
    # only an explicitly assigned project, while editors remain read/write
    # users of project data but never receive destructive project access.
    await _require_project_admin(assistant_id, user)
    async with SessionLocal() as session:
        item = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        if item is None:
            raise HTTPException(status_code=404, detail="assistant not found")
        if item.deleted_at is not None:
            raise HTTPException(status_code=409, detail="assistant is already deleted")
        slug = item.slug
        item.status = "archived"
        item.deleted_at = datetime.now(timezone.utc)
        item.config = {**(item.config or {}), "deleted_by": str(user.id)}
        await session.commit()
    await _audit(user.id, "assistant.delete", details={"assistant_id": str(assistant_id), "slug": slug})
    return {"status": "deleted", "slug": slug}


async def restore_assistant(assistant_id: uuid.UUID, user: AdminUser) -> dict[str, str]:
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="owner role required")
    async with SessionLocal() as session:
        item = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        if item is None or item.deleted_at is None:
            raise HTTPException(status_code=404, detail="deleted assistant not found")
        if item.deleted_at < datetime.now(timezone.utc) - timedelta(days=30):
            raise HTTPException(status_code=410, detail="deleted assistant retention window expired")
        item.deleted_at = None
        item.status = "draft"
        item.config = {key: value for key, value in (item.config or {}).items() if key != "deleted_by"}
        await session.commit()
    await _audit(user.id, "assistant.restore", assistant_id=assistant_id)
    return {"status": "restored", "assistant_id": str(assistant_id)}


async def permanently_delete_assistant(assistant_id: uuid.UUID, user: AdminUser) -> dict[str, str]:
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="owner role required")
    async with SessionLocal() as session:
        item = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        if item is None or item.deleted_at is None:
            raise HTTPException(status_code=404, detail="deleted assistant not found")
        slug = item.slug
        for table in _ASSISTANT_DATA_DELETE_ORDER:
            workspace_table = AssistantWorkspace.metadata.tables[f"market_intelligence.{table}"]
            await session.execute(
                delete(workspace_table).where(workspace_table.c.assistant_id == assistant_id)
            )
        await session.delete(item)
        await session.commit()
    await _audit(user.id, "assistant.permanent_delete", details={"assistant_id": str(assistant_id), "slug": slug})
    return {"status": "permanently_deleted", "slug": slug}


async def activate_assistant(assistant_id: uuid.UUID, user: AdminUser) -> dict[str, object]:
    await _require_project_admin(assistant_id, user)
    async with SessionLocal() as session:
        item = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        if item is None:
            raise HTTPException(status_code=404, detail="assistant not found")
        if item.status == "archived":
            raise HTTPException(status_code=409, detail="archived assistant cannot be activated")
        item.status = "active"
        await session.commit()
    await _audit(user.id, "assistant.activate", assistant_id=assistant_id, details={"status": "active"})
    return {"id": str(assistant_id), "status": "active", "activation": "admin_approved"}


async def update_source(source_id: uuid.UUID, payload: SourceUpdate, user: AdminUser) -> dict[str, object]:
    async with SessionLocal() as session:
        item = await session.get(Source, source_id, with_for_update=True)
        if item is None:
            raise HTTPException(status_code=404, detail="source not found")
        # Source mutations must stay inside the caller's workspace.  The
        # previous implementation authorized by role only, which allowed an
        # editor assigned to one assistant to mutate another assistant's
        # source if its UUID was known.
        if not is_global_admin(user):
            member = (
                await session.execute(
                    select(AssistantMember).where(
                        AssistantMember.assistant_id == item.assistant_id,
                        AssistantMember.user_id == user.id,
                    )
                )
            ).scalar_one_or_none()
            if not workspace_write_allowed(effective_user_role(user), member.role if member else None):
                raise HTTPException(status_code=403, detail="workspace access denied")
        changes = payload.model_dump(exclude_none=True)
        _validate_source_state(
            adapter=changes.get("adapter", item.adapter),
            access_policy=changes.get("access_policy", item.access_policy),
            credential_ref=changes.get("credential_ref", item.credential_ref),
            fetch_url=changes.get("fetch_url", item.fetch_url),
        )
        collection_affecting_fields = {"enabled", "homepage_url", "fetch_url", "adapter", "access_policy", "credential_ref", "account_ref"}
        if collection_affecting_fields.intersection(changes):
            # Give a newly enabled/reconfigured connector one full monitoring
            # window to produce its first successful run before raising a
            # collection outage alert.
            item.updated_at = datetime.now(timezone.utc)
        for key, value in changes.items(): setattr(item, key, value)
        await session.commit()
    await _audit(
        user.id,
        "source.update",
        assistant_id=item.assistant_id,
        details={"source_id": str(source_id), "fields": sorted(changes)},
    )
    return {"id": str(item.id), "source_key": item.source_key, "enabled": item.enabled, "updated_fields": sorted(changes)}


def _validate_source_state(*, adapter: str, access_policy: str, credential_ref: str | None, fetch_url: str) -> None:
    """Validate the complete (merged) source configuration, not just a patch."""
    try:
        validate_public_url_syntax(fetch_url)
        if adapter.endswith("_private") and access_policy != "private_authenticated":
            raise ValueError("private connector requires private_authenticated access policy")
        if adapter.endswith("_public") and access_policy != "public_only":
            raise ValueError("public connector requires public_only access policy")
        validate_connector_binding(adapter, credential_ref, fetch_url, get_settings())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


def _next_catalog_key(rows: list[str], prefix: str) -> str:
    numbers = []
    for value in rows:
        match = re.fullmatch(rf"{re.escape(prefix)}-(\d{{3}})", value or "")
        if match:
            numbers.append(int(match.group(1)))
    next_number = max(numbers or [0]) + 1
    if next_number > 999:
        raise HTTPException(status_code=409, detail=f"{prefix} key space is exhausted")
    return f"{prefix}-{next_number:03d}"


_SOURCE_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"}, "homepage_url": {"type": "string"},
        "fetch_url": {"type": "string"}, "adapter": {"type": "string", "enum": ["rss", "html", "json", "telegram_public", "telegram_private", "instagram_public", "instagram_private", "x_public", "x_private"]},
        "access_policy": {"type": "string", "enum": ["public_only", "private_authenticated"]},
        "credential_ref": {"type": "string"}, "account_ref": {"type": "string"},
        "language": {"type": "string"}, "region": {"type": "string"},
        "output_language": {"type": "string", "enum": list(OUTPUT_LANGUAGE_CODES)},
        "priority": {"type": "integer", "minimum": 1, "maximum": 5},
        "access_notes": {"type": "string"}, "research_notes": {"type": "string"},
        "fit_reason": {"type": "string"}, "example_article": {"type": "string"},
        "overlap_notes": {"type": "string"},
        "match_status": {"type": "string", "enum": ["match", "uncertain", "not_found"]},
        "match_explanation": {"type": "string"},
        "alternatives": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
    },
    "required": ["name", "homepage_url", "fetch_url", "adapter", "access_policy", "credential_ref", "account_ref", "language", "region", "output_language", "priority", "access_notes", "research_notes", "fit_reason", "example_article", "overlap_notes", "match_status", "match_explanation", "alternatives"],
    "additionalProperties": False,
}
_SOURCE_SUGGESTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "maxItems": 10,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "homepage_url": {"type": "string"},
                    "summary": {"type": "string"},
                    "fit_reason": {"type": "string"},
                    "language": {"type": "string"},
                    "region": {"type": "string"},
                    "source_type": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
                },
                "required": ["name", "homepage_url", "summary", "fit_reason", "language", "region", "source_type", "confidence", "evidence"],
                "additionalProperties": False,
            },
        },
        "message": {"type": "string"},
        "alternatives": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
    },
    "required": ["suggestions", "message", "alternatives"],
    "additionalProperties": False,
}
_TOPIC_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"}, "definition": {"type": "string"},
        "positive_terms": {"type": "array", "items": {"type": "string"}},
        "negative_terms": {"type": "array", "items": {"type": "string"}},
        "importance": {"type": "integer", "minimum": 1, "maximum": 5},
        "threshold": {"type": "number", "minimum": 0, "maximum": 1},
        "research_notes": {"type": "string"},
    },
    "required": ["name", "definition", "positive_terms", "negative_terms", "importance", "threshold", "research_notes"],
    "additionalProperties": False,
}
_BUSINESS_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "business_name": {"type": "string"}, "description": {"type": "string"},
        "products_services": {"type": "string"}, "target_customers": {"type": "string"},
        "markets": {"type": "string"}, "revenue_model": {"type": "string"},
        "strategic_goals": {"type": "string"}, "competitors": {"type": "array", "items": {"type": "string"}},
        "sensitivities": {"type": "array", "items": {"type": "string"}},
        "output_language": {"type": "string"}, "output_tone": {"type": "string"},
        "research_notes": {"type": "string"},
    },
    "required": ["business_name", "description", "products_services", "target_customers", "markets", "revenue_model", "strategic_goals", "competitors", "sensitivities", "output_language", "output_tone", "research_notes"],
    "additionalProperties": False,
}

# A small, deterministic directory keeps media setup useful even when the
# optional drafting provider is disabled, rate-limited, or unavailable.  It is
# deliberately limited to public feeds that are safe to probe; the directory
# never carries credentials and is not a substitute for the verification step.
_LOCAL_MEDIA_DIRECTORY: tuple[dict[str, object], ...] = (
    {
        "name": "راه پرداخت",
        "aliases": ("راه پرداخت", "way2pay", "way2pay.ir"),
        "tags": ("پرداخت", "بانکداری", "فین تک", "fintech", "payment"),
        "homepage_url": "https://way2pay.ir/",
        "fetch_url": "https://way2pay.ir/feed/",
        "adapter": "rss", "language": "fa", "region": "IR", "priority": 5,
        "summary": "رسانه تخصصی فناوری‌های مالی، پرداخت و بانکداری.",
    },
    {
        "name": "دیجیاتو",
        "aliases": ("دیجیاتو", "digiato", "digiato.com"),
        "tags": ("فناوری", "هوش مصنوعی", "استارتاپ", "technology", "ai"),
        "homepage_url": "https://digiato.com/",
        "fetch_url": "https://digiato.com/feed",
        "adapter": "rss", "language": "fa", "region": "IR", "priority": 4,
        "summary": "رسانه فناوری و کسب‌وکارهای دیجیتال.",
    },
    {
        "name": "زومیت",
        "aliases": ("زومیت", "zoomit", "zoomit.ir"),
        "tags": ("فناوری", "محصول", "هوش مصنوعی", "technology", "ai"),
        "homepage_url": "https://www.zoomit.ir/",
        "fetch_url": "https://www.zoomit.ir/feed/",
        "adapter": "rss", "language": "fa", "region": "IR", "priority": 3,
        "summary": "رسانه فناوری، محصولات و روندهای دیجیتال.",
    },
    {
        "name": "Finextra",
        "aliases": ("finextra", "finextra.com"),
        "tags": ("پرداخت", "بانکداری", "فین تک", "fintech", "banking", "payments"),
        "homepage_url": "https://www.finextra.com/",
        "fetch_url": "https://www.finextra.com/rss/headlines.aspx",
        "adapter": "rss", "language": "en", "region": "Global", "priority": 5,
        "summary": "رسانه بین‌المللی تخصصی خدمات مالی و فناوری بانکداری.",
    },
    {
        "name": "TechCrunch",
        "aliases": ("techcrunch", "techcrunch.com"),
        "tags": ("فناوری", "استارتاپ", "هوش مصنوعی", "technology", "startup", "ai"),
        "homepage_url": "https://techcrunch.com/",
        "fetch_url": "https://techcrunch.com/feed/",
        "adapter": "rss", "language": "en", "region": "Global", "priority": 4,
        "summary": "رسانه بین‌المللی فناوری، استارتاپ و سرمایه‌گذاری.",
    },
)


def _media_query_tokens(value: str) -> set[str]:
    normalized = re.sub(r"[\u200c\u200f\u202a-\u202e]", " ", str(value or "").casefold())
    normalized = normalized.replace("ي", "ی").replace("ك", "ک")
    return {token for token in re.split(r"[^\w\u0600-\u06ff]+", normalized) if len(token) >= 2}


def _local_source_draft(name: str, instruction: str = "") -> dict[str, object] | None:
    """Resolve a known public source without depending on an external model."""
    requested = str(name or "").strip().casefold()
    for entry in _LOCAL_MEDIA_DIRECTORY:
        aliases = [value.casefold() for value in _string_values(entry.get("aliases"))]
        if requested in aliases:
            return {
                "name": str(entry["name"]), "homepage_url": str(entry["homepage_url"]),
                "fetch_url": str(entry["fetch_url"]), "adapter": str(entry["adapter"]),
                "language": str(entry["language"]), "region": str(entry["region"]),
                "output_language": "source",
                "priority": _safe_int_value(entry.get("priority")), "access_notes": "Public feed from Bee Researcher directory.",
                "research_notes": "Resolved from the local public-media directory; connection is verified before registration.",
                "fit_reason": str(entry["summary"]), "example_article": "", "overlap_notes": "",
                "match_status": "match", "match_explanation": "نام با یک رسانهٔ عمومی شناخته‌شده تطبیق داده شد.",
                "alternatives": [], "draft_source": "local_directory",
            }
    # A keyword is often broader than a publication's exact name (for
    # example, "فین‌تک ایران" or "technology startups").  Resolve a clear
    # single best directory match offline before falling back to the optional
    # external discovery provider.  Require at least two weighted token hits
    # so a vague word never silently registers the wrong media source.
    query_tokens = _media_query_tokens(f"{name} {instruction}")
    ranked: list[tuple[int, int, dict[str, object]]] = []
    for entry in _LOCAL_MEDIA_DIRECTORY:
        tag_tokens = _media_query_tokens(" ".join(_string_values(entry.get("tags"))))
        alias_tokens = _media_query_tokens(" ".join(_string_values(entry.get("aliases"))))
        score = len(query_tokens & tag_tokens) * 3 + len(query_tokens & alias_tokens) * 5
        if score >= 6:
            ranked.append((score, _safe_int_value(entry.get("priority")), entry))
    if ranked:
        ranked.sort(key=lambda row: (-row[0], -row[1], str(row[2].get("name") or "")))
        score, _priority, entry = ranked[0]
        return {
            "name": str(entry["name"]), "homepage_url": str(entry["homepage_url"]),
            "fetch_url": str(entry["fetch_url"]), "adapter": str(entry["adapter"]),
            "language": str(entry["language"]), "region": str(entry["region"]),
            "output_language": "source", "priority": _safe_int_value(entry.get("priority")),
            "access_notes": "Public feed from Bee Researcher directory.",
            "research_notes": "The closest public-media directory match was selected from the supplied keyword; review it before registration.",
            "fit_reason": str(entry["summary"]), "example_article": "", "overlap_notes": "",
            "match_status": "uncertain",
            "match_explanation": f"بهترین تطبیق آفلاین با امتیاز {score} از فهرست رسانه‌های عمومی پیدا شد.",
            "alternatives": [str(row[2]["name"]) for row in ranked[1:4]],
            "draft_source": "local_keyword_match",
        }
    # A URL/domain supplied as the name is a safe, useful escape hatch for a
    # source that is not in the built-in directory.  We still require the
    # fetch probe before allowing registration.
    candidate = requested.removeprefix("https://").removeprefix("http://").split("/", 1)[0]
    if "." in candidate and " " not in candidate:
        homepage = f"https://{candidate}/"
        return {
            "name": str(name).strip()[:160], "homepage_url": homepage,
            "fetch_url": homepage, "adapter": "html", "language": "unknown", "output_language": "source", "region": "Global",
            "priority": 3, "access_notes": "Feed path is a proposal; review it before saving.",
            "research_notes": "A public domain was supplied directly; the feed path must pass the connection check.",
            "fit_reason": str(instruction or "Public source supplied by the owner.")[:600],
            "example_article": "", "overlap_notes": "", "match_status": "uncertain",
            "match_explanation": "دامنه دریافت شد؛ مسیر فید باید بررسی و در صورت نیاز اصلاح شود.",
            "alternatives": [], "draft_source": "local_domain",
        }
    return None


def _local_source_suggestions(keyword: str, instruction: str = "") -> dict[str, object]:
    query_tokens = _media_query_tokens(keyword) | _media_query_tokens(instruction)
    ranked: list[tuple[int, dict[str, object]]] = []
    for entry in _LOCAL_MEDIA_DIRECTORY:
        entry_tokens = _media_query_tokens(" ".join(_string_values(entry.get("tags"))))
        alias_tokens = _media_query_tokens(" ".join(_string_values(entry.get("aliases"))))
        score = len(query_tokens & entry_tokens) * 3 + len(query_tokens & alias_tokens) * 5
        if score:
            ranked.append((score, entry))
    ranked.sort(key=lambda pair: (-pair[0], -_safe_int_value(pair[1].get("priority"))))
    suggestions = []
    # Pick one candidate from each available coverage bucket first.  This
    # prevents five near-identical local sources from crowding out a useful
    # cross-language/region option, while still filling the result up to five.
    selected: list[tuple[int, dict[str, object]]] = []
    seen_buckets: set[tuple[str, str, str]] = set()
    for score, entry in ranked:
        source_type = (
            "finance_media" if _media_query_tokens(" ".join(_string_values(entry.get("tags")))) & {"پرداخت", "بانکداری", "فین", "fintech", "banking", "payments", "payment"}
            else "technology_media" if _media_query_tokens(" ".join(_string_values(entry.get("tags")))) & {"فناوری", "technology", "ai", "هوش", "استارتاپ", "startup"}
            else "specialist_public_media"
        )
        bucket = (str(entry.get("language") or "unknown"), str(entry.get("region") or "Global"), source_type)
        if bucket not in seen_buckets and len(selected) < 5:
            selected.append((score, entry))
            seen_buckets.add(bucket)
    for pair in ranked:
        if pair not in selected and len(selected) < 5:
            selected.append(pair)
    for score, entry in selected[:5]:
        # A deterministic confidence is deliberately conservative: it is a
        # discovery ranking, not a claim that the source has already passed
        # the connection/readability probe.
        confidence = min(0.96, 0.58 + (float(score) / 20.0) + (0.04 if _safe_int_value(entry.get("priority")) >= 4 else 0.0))
        suggestions.append({
            "name": str(entry["name"]), "homepage_url": str(entry["homepage_url"]),
            "summary": str(entry["summary"]),
            "fit_reason": "بر اساس کلیدواژه و زاویهٔ واردشده، از فهرست رسانه‌های عمومی انتخاب شد.",
            "language": str(entry.get("language") or "unknown"),
            "region": str(entry.get("region") or "Global"),
            "source_type": (
                "finance_media" if _media_query_tokens(" ".join(_string_values(entry.get("tags")))) & {"پرداخت", "بانکداری", "فین", "fintech", "banking", "payments", "payment"}
                else "technology_media" if _media_query_tokens(" ".join(_string_values(entry.get("tags")))) & {"فناوری", "technology", "ai", "هوش", "استارتاپ", "startup"}
                else "specialist_public_media"
            ),
            "confidence": round(confidence, 2),
            "evidence": [str(entry["homepage_url"])],
        })
    alternatives = [] if suggestions else [str(entry["name"]) for entry in _LOCAL_MEDIA_DIRECTORY[:3]]
    return {
        "suggestions": suggestions,
        "message": "" if suggestions else "در فهرست محلی رسانهٔ دقیقی برای این کلیدواژه پیدا نشد؛ نام مشابه را بررسی کنین.",
        "alternatives": alternatives,
    }

_ASSISTANT_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "slug": {"type": "string"},
        "business_name": {"type": "string"},
        "description": {"type": "string"},
        "mission": {"type": "string"},
        "language": {"type": "string"},
        "countries": {"type": "array", "items": {"type": "string"}},
        "source_suggestions": {"type": "array", "items": {"type": "string"}},
        "topic_suggestions": {"type": "array", "items": {"type": "string"}},
        "settings": {
            "type": "object",
            "properties": {
                "freshness_window_days": {"type": "integer", "minimum": 1, "maximum": 7},
                "relevance_threshold": {"type": "number", "minimum": 0, "maximum": 1},
                "max_items_per_run": {"type": "integer", "minimum": 1, "maximum": 7},
                "output_language": {"type": "string"},
            },
            "required": ["freshness_window_days", "relevance_threshold", "max_items_per_run", "output_language"],
            "additionalProperties": False,
        },
    },
    "required": ["name", "slug", "business_name", "description", "mission", "language", "countries", "source_suggestions", "topic_suggestions", "settings"],
    "additionalProperties": False,
}


def _mission_slug(value: str) -> str:
    """Create a stable, API-safe slug without persisting the draft."""
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    normalized = normalized[:56].strip("-")
    return normalized if len(normalized) >= 3 else f"research-{secrets.token_hex(3)}"


def _assistant_draft_fallback(mission: str, language: str) -> dict[str, object]:
    short = " ".join(mission.split())[:160]
    slug = _mission_slug(short)
    return {
        "name": short[:80] or "Market Research Assistant",
        "slug": slug,
        "business_name": "پروژه جدید" if language.startswith("fa") else "New business",
        "description": short,
        "mission": mission,
        "language": language,
        "countries": [],
        "source_suggestions": [],
        "topic_suggestions": [short],
        "settings": {
            "freshness_window_days": 3,
            "relevance_threshold": 0.45,
            "max_items_per_run": 7,
            "output_language": language,
        },
        "draft_source": "fallback",
        "research_notes": "پیش‌نویس پایه تولید شد؛ رسانه‌ها و موضوعات را قبل از ساخت نهایی بررسی و اصلاح کنید.",
    }


async def draft_assistant(payload: AssistantDraftRequest, user: AdminUser) -> dict[str, object]:
    """Generate an editable, non-persistent assistant setup from a short mission."""
    if not is_global_admin(user):
        raise HTTPException(status_code=403, detail="admin role required")
    mission = " ".join(payload.mission.split())
    settings = get_settings()
    client = OpenAIClient(settings)
    system = (
        "شما طراح دستیار تحقیقات بازار هستید. از توضیح کوتاه کاربر یک پیش‌نویس کاملاً قابل ویرایش بسازید. "
        "تنظیمات باید محافظه‌کارانه باشد؛ هیچ secret، شناسه کانال یا آدرس قطعی ساختگی تولید نکنید. "
        "فقط JSON مطابق schema برگردانید."
    )
    try:
        draft = await asyncio.wait_for(
            client.draft_json(
                system_prompt=system,
                user_payload={"mission": mission, "language": payload.language},
                schema_name="market_intelligence_assistant_draft",
                schema=_ASSISTANT_DRAFT_SCHEMA,
            ),
            timeout=50,
        )
        draft = dict(draft)
        draft["draft_source"] = "openai"
    except Exception:
        draft = _assistant_draft_fallback(mission, payload.language)
    # Never let generated configuration carry an operational secret or a
    # destination. The draft is returned to the editor and is not persisted.
    draft["name"] = str(draft.get("name") or mission[:80] or "Market Research Assistant")[:160]
    draft["business_name"] = str(draft.get("business_name") or ("پروژه جدید" if payload.language.startswith("fa") else "New business"))[:160]
    draft["slug"] = _mission_slug(str(draft.get("slug") or draft.get("name") or mission))
    draft["mission"] = mission
    raw_settings = _object_mapping(draft.get("settings"))
    freshness = min(max(_safe_int_value(raw_settings.get("freshness_window_days"), default=3), 1), 7)
    threshold = min(max(_safe_float_value(raw_settings.get("relevance_threshold"), default=0.45), 0.0), 1.0)
    max_items = min(max(_safe_int_value(raw_settings.get("max_items_per_run"), default=7), 1), 7)
    draft["settings"] = {
        "freshness_window_days": freshness,
        "relevance_threshold": threshold,
        "max_items_per_run": max_items,
        "output_language": str(raw_settings.get("output_language") or payload.language)[:16],
    }
    draft["config"] = {
        "runtime": {
            "freshness_window_days": freshness,
            "relevance_threshold": threshold,
            "max_items_per_run": max_items,
            "output_language": str(raw_settings.get("output_language") or payload.language)[:16],
            "schedule_slots": [],
        },
        "shortcut_mission": mission,
        "suggested_sources": [value[:240] for value in _string_values(draft.get("source_suggestions"))[:20]],
        "suggested_topics": [value[:240] for value in _string_values(draft.get("topic_suggestions"))[:20]],
    }
    return {"status": "draft", "expires_in_seconds": 300, "draft": draft}


async def _catalog_draft(
    kind: Literal["source", "topic", "business"],
    name: str,
    instruction: str,
) -> dict[str, object]:
    if kind == "source":
        try:
            return await asyncio.wait_for(discover_media(get_settings(), name=name, instruction=instruction, schema=_SOURCE_DRAFT_SCHEMA), timeout=90)
        except Exception as exc:
            provider_status = type(exc).__name__
        local_draft = _local_source_draft(name, instruction)
        if local_draft is not None:
            local_draft["provider_status"] = provider_status
            return local_draft
        aliases = {alias: str(row["name"]) for row in _LOCAL_MEDIA_DIRECTORY for alias in _string_values(row.get("aliases"))}
        names = list(dict.fromkeys(aliases.get(a, a) for a in difflib.get_close_matches(name.casefold(), list(aliases), n=3, cutoff=0.55)))
        return {"name": name, "homepage_url": "", "fetch_url": "", "adapter": "html", "language": "unknown", "output_language": "source", "region": "Global", "priority": 3, "match_status": "uncertain", "match_explanation": "جست‌وجوی آنلاین موقتاً در دسترس نیست؛ این به معنی نبود رسانه نیست. دوباره تلاش کنید یا آدرس عمومی را وارد کنید.", "alternatives": names[:3], "draft_source": "fallback", "provider_status": provider_status}
    settings = get_settings()
    client = OpenAIClient(settings)
    system = (
        "شما دستیار راه‌اندازی یک سامانه تحقیقات بازار هستید. بر اساس نام داده‌شده، "
        "یک پیش‌نویس دقیق و قابل ویرایش بسازید. چیزی را قطعی جلوه ندهید؛ اگر لینک یا "
        "اطلاعاتی قابل اطمینان نیست، صریحاً در research_notes بنویسید. برای رسانه فقط وقتی "
        "نام و URL عمومیِ قابل اتکا دارید match_status را match قرار دهید. در غیر این صورت "
        "match_status را uncertain یا not_found، URLها را خالی، و حداکثر سه نام مشابه را در "
        "alternatives برگردانید. هرگز URL، RSS یا credential ساختگی تولید نکنید. خروجی فقط JSON باشد."
    )
    schemas = {"source": _SOURCE_DRAFT_SCHEMA, "topic": _TOPIC_DRAFT_SCHEMA, "business": _BUSINESS_DRAFT_SCHEMA}
    try:
        draft = await asyncio.wait_for(
            client.draft_json(
                system_prompt=system,
                # Only the explicit catalog input is sent to the optional
                # drafting provider. Business profiles, existing sources and
                # project configuration remain local to this service.
                user_payload={"kind": kind, "name": name, "instruction": instruction},
                schema_name=f"market_intelligence_{kind}_draft",
                schema=schemas[kind],
            ),
            timeout=50,
        )
        draft["draft_source"] = "openai"
        return draft
    except Exception as exc:
        # Setup must remain usable when the external service is unavailable.
        # The user still receives an honest editable draft, never fabricated
        # credentials or a silently persisted record.
        note = "رسانه‌ای با این نام در فهرست محلی پیدا نشد و تحلیل خودکار در دسترس نبود؛ نام دقیق یا دامنهٔ عمومی را وارد کنین."
        if kind == "source":
            return {"name": name, "homepage_url": "", "fetch_url": "", "adapter": "rss", "language": "fa", "output_language": "source", "region": "IR", "priority": 3, "access_notes": "", "research_notes": note, "fit_reason": "", "example_article": "", "overlap_notes": "", "match_status": "uncertain", "match_explanation": note, "alternatives": [], "draft_source": "fallback"}
        if kind == "topic":
            return {"name": name, "definition": f"پوشش و تحلیل اخبار مرتبط با «{name}». ", "positive_terms": [name], "negative_terms": [], "importance": 3, "threshold": 0.45, "research_notes": note, "draft_source": "fallback"}
        return {"business_name": name, "description": "", "products_services": "", "target_customers": "", "markets": "", "revenue_model": "", "strategic_goals": "", "competitors": [], "sensitivities": [], "output_language": "fa", "output_tone": "کوتاه، تحلیلی، اجرایی و رسمی", "research_notes": note, "draft_source": "fallback"}


async def _source_suggestions(
    keyword: str,
    instruction: str,
    *, exclude: list[str] | None = None, page: int = 0,
) -> dict[str, object]:
    """Return up to five concise, review-first media candidates.

    The discovery step deliberately does not fabricate feed adapters or
    credentials. Those operational details are resolved only after the owner
    approves one candidate.
    """
    local = _local_source_suggestions(keyword, instruction)
    try:
        return await asyncio.wait_for(discover_media(get_settings(), name=keyword, instruction=instruction, schema=_SOURCE_SUGGESTIONS_SCHEMA, suggestions=True, exclude=exclude, page=page), timeout=90)
    except Exception as exc:
        excluded = {publisher_host(url) for url in (exclude or [])}
        local["suggestions"] = [row for row in _mapping_rows(local.get("suggestions")) if publisher_host(str(row.get("homepage_url") or "")) not in excluded]
        local["provider_status"] = type(exc).__name__
        local["draft_source"] = "local_directory"
        local["message"] = "جست‌وجوی آنلاین موقتاً در دسترس نیست؛ فقط نتایج فهرست محلی نمایش داده می‌شوند."
        return local
async def _assistant_media_context(assistant_id: uuid.UUID) -> dict[str, object]:
    """Return a small, non-secret project brief for media discovery.

    A media name is ambiguous on its own.  This brief is intentionally used
    only inside Bee Researcher for duplicate detection and alternatives; it
    is never sent to the optional drafting provider.
    """
    async with SessionLocal() as session:
        assistant = await session.get(AssistantWorkspace, assistant_id)
        if assistant is None:
            return {}
        profiles = (await session.scalars(
            select(BusinessProfile).where(BusinessProfile.assistant_id == assistant_id).order_by(BusinessProfile.id)
        )).all()
        selected_id = str((assistant.config or {}).get("active_business_id") or "")
        profile = next((row for row in profiles if str(row.id) == selected_id), profiles[0] if profiles else None)
        sources = (await session.scalars(
            select(Source.name).where(Source.assistant_id == assistant_id).order_by(Source.priority.desc(), Source.name).limit(20)
        )).all()
    return {
        "assistant_name": str(assistant.name or "")[:160],
        "mission": str(assistant.description or "")[:1200],
        "business": {
            "name": str((profile.business_name if profile else assistant.business_name) or "")[:160],
            "description": str((profile.description if profile else "") or "")[:1200],
            "markets": str((profile.markets if profile else "") or "")[:500],
            "products_services": str((profile.products_services if profile else "") or "")[:500],
        },
        "existing_media": [str(value)[:160] for value in sources],
    }


def _draft_alternatives(draft: dict[str, object], context: dict[str, object]) -> list[str]:
    """Combine model alternatives with close existing names without guessing URLs."""
    alternatives = [value.strip()[:160] for value in _string_values(draft.get("alternatives"))[:3] if value.strip()]
    requested = str(draft.get("name") or "").strip()
    known = [value.strip() for value in _string_values(context.get("existing_media")) if value.strip()]
    for value in difflib.get_close_matches(requested, known, n=3, cutoff=0.45):
        if value not in alternatives:
            alternatives.append(value)
    return alternatives[:3]


async def _verify_source_draft(draft: dict[str, object]) -> dict[str, object]:
    """Check a generated public connector before it is shown as ready to add.

    The test uses the same SSRF checks, robots policy and parsers as runtime
    collection, but does not persist a Source, article or publication.  It is
    intentionally bounded to a single request attempt and 20 seconds.
    """
    homepage = str(draft.get("homepage_url") or "").strip()
    fetch_url = str(draft.get("fetch_url") or "").strip()
    adapter = str(draft.get("adapter") or "rss").strip()
    match_status = str(draft.get("match_status") or "uncertain")
    if match_status == "not_found" or not homepage or not fetch_url:
        return {
            "status": "not_found",
            "message": str(draft.get("match_explanation") or "رسانهٔ قابل اتکایی برای این نام پیدا نشد.")[:600],
            "items_found": 0,
        }
    if adapter not in {"rss", "html", "json", "telegram_public"}:
        return {
            "status": "not_usable",
            "message": "نوع اتصال پیشنهادی برای بررسی خودکار این رسانه قابل استفاده نیست.",
            "items_found": 0,
        }
    try:
        homepage = validate_public_url_syntax(homepage)
        fetch_url = validate_public_url_syntax(fetch_url)
        draft["homepage_url"] = homepage
        draft["fetch_url"] = fetch_url
    except ValueError:
        return {
            "status": "not_usable",
            "message": "آدرس‌های پیشنهادی عمومی و معتبر نیستند؛ این رسانه ثبت نشد.",
            "items_found": 0,
        }
    try:
        if adapter == "html":
            try:
                feeds = await asyncio.wait_for(SourceFetcher(get_settings()).discover_feeds(homepage), timeout=15)
                if feeds:
                    fetch_url, adapter = feeds[0]
                    draft["fetch_url"], draft["adapter"] = fetch_url, adapter
            except (FetchFailure, ValueError, OSError, asyncio.TimeoutError):
                pass  # Keep the evidenced HTML connector editable.
        result = await asyncio.wait_for(
            SourceFetcher(get_settings()).fetch(
                SourceSpec(
                    source_key="DRAFT-VERIFY",
                    name=str(draft.get("name") or "media draft")[:160],
                    homepage_url=homepage,
                    fetch_url=fetch_url,
                    adapter=adapter,
                    request_timeout_seconds=20,
                    max_retries=0,
                )
            ),
            timeout=25,
        )
    except (FetchFailure, ValueError, OSError, asyncio.TimeoutError) as exc:
        # A transport/DNS/timeout failure is not proof that the publication
        # is invalid.  Keep the candidate editable so the owner can correct
        # its feed path and save it; a real HTTP/content failure below still
        # remains ``not_usable``.  This avoids the previous dead-end where a
        # temporarily unavailable network made every valid media name look
        # like a missing source.
        status_code = getattr(exc, "status_code", None)
        if status_code is None:
            return {
                "status": "needs_review",
                "message": f"اتصال خودکار موقتاً در دسترس نبود؛ آدرس و نوع اتصال را مرور و سپس ثبت کنین: {str(exc)[:260]}",
                "items_found": 0,
                "editable": True,
            }
        return {"status": "not_usable", "message": f"رسانه پاسخ HTTP معتبر نداد: {str(exc)[:300]}", "items_found": 0, "editable": True}
    except Exception:
        return {"status": "not_usable", "message": "اتصال یا خواندن محتوای رسانه تأیید نشد.", "items_found": 0}
    if result.status == "succeeded" and result.items:
        return {
            "status": "ready",
            "message": "اتصال رسانه و خواندن نمونه‌ای از محتوای آن تأیید شد.",
            "items_found": len(result.items),
            "response_url": result.response_url,
        }
    return {
        "status": "not_usable",
        "message": "رسانه پاسخ داد، اما محتوای قابل‌خواندن برای این نوع اتصال پیدا نشد.",
        "items_found": len(result.items),
        "response_url": result.response_url,
    }


async def draft_source(assistant_id: uuid.UUID, payload: CatalogDraftRequest, user: AdminUser) -> dict[str, object]:
    await _require_assistant_access(assistant_id, user, write=True)
    context = await _assistant_media_context(assistant_id)
    draft = await _catalog_draft("source", payload.name.strip(), payload.instruction.strip())
    draft["alternatives"] = _draft_alternatives(draft, context)
    verification = await _verify_source_draft(draft)
    return {
        "kind": "source",
        "draft": draft,
        "verification": verification,
        "expires_in_seconds": 300,
    }


_TEMPLATE_BLOCKS = {
    "title", "summary", "business_connection", "opportunity", "risk",
    "source", "published_at", "source_url", "feedback", "footer", "image",
}
_DEFAULT_TEMPLATE = [
    {"type": "title", "label": "عنوان", "visible": True, "max_chars": 150, "guidance": "عنوان دقیق خبر را حفظ کن.", "emoji": "📢"},
    {"type": "image", "label": "تصویر شاخص", "visible": False, "max_chars": 0, "guidance": "اگر تصویر شاخص معتبر منبع موجود بود، همراه پیام منتشر شود.", "emoji": "🖼️"},
    {"type": "summary", "label": "خلاصه", "visible": True, "max_chars": 350, "guidance": "خلاصه کوتاه و فقط مبتنی بر متن خبر بنویس.", "emoji": ""},
    {"type": "source", "label": "منبع", "visible": True, "max_chars": 120, "guidance": "نام رسانه و لینک منبع حفظ شود.", "emoji": "🔗"},
    {"type": "published_at", "label": "زمان انتشار", "visible": True, "max_chars": 80, "guidance": "زمان را کوتاه و خوانا نمایش بده.", "emoji": ""},
    {"type": "business_connection", "label": "ارتباط با بیزینس", "visible": True, "max_chars": 300, "guidance": "ارتباط مستقیم خبر با بیزینس را توضیح بده.", "emoji": "💡"},
    {"type": "opportunity", "label": "فرصت", "visible": True, "max_chars": 250, "guidance": "فرصت قابل اقدام را کوتاه بنویس.", "emoji": "🔍"},
    {"type": "risk", "label": "ریسک", "visible": True, "max_chars": 250, "guidance": "ریسک قابل توجه را بدون اغراق بنویس.", "emoji": "⚠️"},
    {"type": "feedback", "label": "بازخورد", "visible": True, "max_chars": 80, "guidance": "دکمه‌های بازخورد را واضح نگه دار.", "emoji": "🗳"},
    {"type": "footer", "label": "پاورقی", "visible": True, "max_chars": 80, "guidance": "پاورقی کوتاه بماند.", "emoji": "—"},
]


def _normalise_template_blocks(blocks: list[dict[str, object]]) -> list[dict[str, object]]:
    cleaned: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in blocks[:12]:
        if not isinstance(raw, dict):
            continue
        block_type = str(raw.get("type") or "").strip()
        if block_type not in _TEMPLATE_BLOCKS or block_type in seen:
            continue
        seen.add(block_type)
        label = str(raw.get("label") or block_type).strip()[:80]
        guidance = str(raw.get("guidance") or "").strip()[:400]
        emoji = str(raw.get("emoji") or "").strip()[:16]
        try:
            max_chars = _safe_int_value(raw.get("max_chars"))
        except (TypeError, ValueError):
            max_chars = 0
        max_chars = min(max(max_chars, 20), 1200) if max_chars else 0
        # Keep at most one blank line between consecutive rendered blocks.
        try:
            spacing_after = _safe_int_value(raw.get("spacing_after"), default=1)
        except (TypeError, ValueError):
            spacing_after = 1
        spacing_after = min(max(spacing_after, 0), 1)
        cleaned.append({"type": block_type, "label": label, "visible": bool(raw.get("visible", True)), "max_chars": max_chars, "guidance": guidance, "emoji": emoji, "spacing_after": spacing_after})
    if not cleaned:
        raise HTTPException(status_code=422, detail="template must contain at least one supported block")
    return cleaned


def _assistant_templates(config: dict | None) -> dict[str, dict[str, object]]:
    stored = (config or {}).get("message_templates") or {}
    result: dict[str, dict[str, object]] = {}
    for channel in ("feedback", "observer"):
        item = stored.get(channel) if isinstance(stored, dict) else None
        blocks = _normalise_template_blocks(item.get("blocks", _DEFAULT_TEMPLATE)) if isinstance(item, dict) else list(_DEFAULT_TEMPLATE)
        if not any(str(block.get("type")) == "image" for block in blocks):
            blocks.insert(1, next(block for block in _DEFAULT_TEMPLATE if block["type"] == "image"))
        result[channel] = {
            "status": str(item.get("status", "published")) if isinstance(item, dict) else "published",
            "blocks": blocks,
        }
    return result


async def get_assistant_templates(assistant_id: uuid.UUID, user: AdminUser) -> dict[str, object]:
    await _require_assistant_access(assistant_id, user)
    async with SessionLocal() as session:
        item = await session.get(AssistantWorkspace, assistant_id)
    if item is None:
        raise HTTPException(status_code=404, detail="assistant not found")
    return {"assistant_id": str(assistant_id), "templates": _assistant_templates(item.config), "can_edit": is_owner(user), "supported_blocks": sorted(_TEMPLATE_BLOCKS)}


async def update_assistant_template(assistant_id: uuid.UUID, channel: str, payload: TemplateBlocksRequest, user: AdminUser) -> dict[str, object]:
    await _require_assistant_access(assistant_id, user, write=True)
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="owner role required to edit message templates")
    if channel not in {"feedback", "observer"}:
        raise HTTPException(status_code=422, detail="channel must be feedback or observer")
    blocks = _normalise_template_blocks(payload.blocks)
    async with SessionLocal() as session:
        item = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        if item is None:
            raise HTTPException(status_code=404, detail="assistant not found")
        config = dict(item.config or {})
        templates = _assistant_templates(config)
        templates[channel] = {"status": "published" if payload.publish else "draft", "blocks": blocks}
        config["message_templates"] = templates
        item.config = config
        await session.commit()
    await _audit(user.id, "assistant.template.update", assistant_id=assistant_id, details={"channel": channel})
    return {"assistant_id": str(assistant_id), "channel": channel, **templates[channel]}


async def preview_assistant_template(assistant_id: uuid.UUID, channel: str, payload: TemplateBlocksRequest, user: AdminUser) -> dict[str, object]:
    await _require_assistant_access(assistant_id, user)
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="owner role required to preview message templates")
    if channel not in {"feedback", "observer"}:
        raise HTTPException(status_code=422, detail="channel must be feedback or observer")
    blocks = _normalise_template_blocks(payload.blocks)
    async with SessionLocal() as session:
        assistant = await session.get(AssistantWorkspace, assistant_id)
        if assistant is None:
            raise HTTPException(status_code=404, detail="assistant not found")
        selected_id = (assistant.config or {}).get("active_business_id")
        profile_query = select(BusinessProfile).where(BusinessProfile.assistant_id == assistant_id)
        if selected_id:
            profile_query = profile_query.where(BusinessProfile.id == int(selected_id))
        profile = (await session.execute(profile_query.order_by(BusinessProfile.id))).scalars().first()
        business_name = str((profile.business_name if profile else assistant.business_name) or "داتین").strip() or "داتین"
    message = render_analysis_message(
        headline="نمونه خبر بازار پرداخت",
        summary="این یک پیش‌نمایش امن از ساختار پیام است و محتوای واقعی خبر محسوب نمی‌شود.",
        business_connection="نمونه ارتباط خبر با بیزینس برای بررسی ترتیب و خوانایی قالب.",
        opportunity="فرصت نمونه برای ارزیابی قالب.",
        risk="ریسک نمونه برای ارزیابی قالب.",
        action="اقدام نمونه",
        confidence=0.8,
        source_name="رسانه نمونه",
        source_url="https://example.com/preview",
        published_at=datetime.now(timezone.utc).isoformat(),
        incomplete=False,
        business_name=business_name,
        template_blocks=blocks,
    )
    return {"assistant_id": str(assistant_id), "channel": channel, "preview": message, "length": len(message), "blocks": blocks}


_ACCOUNT_THEMES = {
    "system": {"label_fa": "همگام با سیستم", "label_en": "System"},
    "light": {"label_fa": "روشن", "label_en": "Light"},
    "dark": {"label_fa": "تیره", "label_en": "Dark"},
    "default": {"label_fa": "آبی جذاب", "label_en": "Attractive blue"},
    "honey": {"label_fa": "عسل و کهربا", "label_en": "Honey amber"},
    "forest": {"label_fa": "جنگل سبز", "label_en": "Forest green"},
    "slate": {"label_fa": "خاکستری محو", "label_en": "Faded gray"},
    "blackyellow": {"label_fa": "مشکی و زرد", "label_en": "Black & yellow"},
    "red": {"label_fa": "قرمز حرفه‌ای", "label_en": "Professional red"},
}


async def get_account_preferences(user: AdminUser) -> dict[str, object]:
    preferences = dict(user.preferences or {})
    # New accounts default to Honey Amber, while an explicitly selected
    # legacy/default theme remains available and is never silently migrated.
    theme = str(preferences.get("theme") or "honey")
    if theme not in _ACCOUNT_THEMES:
        theme = "honey"
    return {"theme": theme, "accent_color": preferences.get("accent_color") or "blue", "density": preferences.get("density") or "comfortable", "sidebar_collapsed": bool(preferences.get("sidebar_collapsed", False)), "default_view": preferences.get("default_view") or "assistants", "auto_refresh": bool(preferences.get("auto_refresh", True)), "show_technical_details": bool(preferences.get("show_technical_details", False)), "avatar_url": preferences.get("avatar_url"), "themes": [{"id": key, **value} for key, value in _ACCOUNT_THEMES.items()], "can_edit": is_owner(user), "appearance_edit": True}


async def update_account_preferences(payload: AccountPreferencesUpdate, user: AdminUser) -> dict[str, object]:
    changed = any(value is not None for value in (payload.theme, payload.accent_color, payload.density, payload.sidebar_collapsed, payload.default_view, payload.auto_refresh, payload.show_technical_details, payload.avatar_url))
    if not changed:
        raise HTTPException(status_code=403, detail="owner role required")
    async with SessionLocal() as session:
        item = await session.get(AdminUser, user.id, with_for_update=True)
        if item is None:
            raise HTTPException(status_code=404, detail="account not found")
        preferences = dict(item.preferences or {})
        if payload.theme is not None:
            preferences["theme"] = payload.theme
        for key in ("accent_color", "density", "default_view"):
            value = getattr(payload, key)
            if value is not None:
                preferences[key] = value
        for key in ("sidebar_collapsed", "auto_refresh", "show_technical_details"):
            value = getattr(payload, key)
            if value is not None:
                preferences[key] = bool(value)
        if payload.avatar_url is not None:
            preferences["avatar_url"] = payload.avatar_url
        elif "avatar_url" in preferences and payload.avatar_url is None and payload.theme is None:
            preferences.pop("avatar_url", None)
        item.preferences = preferences
        await session.commit()
    await _audit(user.id, "admin.account_preferences.update", details={"theme": payload.theme, "accent_color": payload.accent_color, "density": payload.density, "avatar_updated": payload.avatar_url is not None})
    return await get_account_preferences(user)


def _source_suggestion_rows(config: dict | None) -> list[dict[str, object]]:
    rows = (config or {}).get("source_suggestions") or []
    return [dict(row) for row in rows if isinstance(row, dict) and row.get("id")]


async def list_source_suggestions(assistant_id: uuid.UUID, user: AdminUser) -> dict[str, object]:
    await _require_assistant_access(assistant_id, user)
    async with SessionLocal() as session:
        item = await session.get(AssistantWorkspace, assistant_id)
    if item is None:
        raise HTTPException(status_code=404, detail="assistant not found")
    # The config list is an active review queue. Decisions remove the card;
    # ignore legacy non-pending rows as a safe migration for old workspaces.
    rows = [row for row in _source_suggestion_rows(item.config) if row.get("status", "pending") == "pending"]
    return {
        "assistant_id": str(assistant_id),
        "can_approve": is_owner(user),
        "suggestions": rows,
    }


async def create_source_suggestion(assistant_id: uuid.UUID, payload: CatalogDraftRequest, user: AdminUser) -> dict[str, object]:
    await _require_assistant_access(assistant_id, user, write=True)
    keyword = payload.name.strip()
    if not keyword:
        raise HTTPException(status_code=422, detail="media keyword is required")
    async with SessionLocal() as session:
        workspace = await session.get(AssistantWorkspace, assistant_id)
        existing = (await session.scalars(select(Source.homepage_url).where(Source.assistant_id == assistant_id))).all()
        config_before = dict(workspace.config or {}) if workspace else {}
    history_key = hashlib.sha256((keyword.casefold() + "\n" + payload.instruction.strip()).encode()).hexdigest()
    histories = dict(config_before.get("source_discovery_seen") or {})
    exclude = list(existing) + payload.exclude_urls
    exclude.extend(str(_object_mapping(row.get("draft")).get("homepage_url") or "") for row in _source_suggestion_rows(config_before))
    if payload.page:
        exclude.extend(histories.get(history_key) or [])
    discovery = await _source_suggestions(keyword, payload.instruction.strip(), exclude=exclude, page=payload.page)
    candidates = _mapping_rows(discovery.get("suggestions"))
    suggestions = []
    async with SessionLocal() as session:
        item = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        if item is None:
            raise HTTPException(status_code=404, detail="assistant not found")
        config = dict(item.config or {})
        rows = _source_suggestion_rows(config)
        existing_sources = (await session.execute(select(Source).where(Source.assistant_id == assistant_id))).scalars().all()
        existing_names = {str(source.name or "").strip().casefold() for source in existing_sources}
        existing_homepages = {str(source.homepage_url or "").strip().rstrip("/").casefold() for source in existing_sources}
        pending_homepages = {
            str(_object_mapping(row.get("draft")).get("homepage_url") or "").strip().rstrip("/").casefold()
            for row in rows if row.get("status", "pending") == "pending"
        }
        seen_hosts = {publisher_host(url) for url in exclude if publisher_host(url)}
        for candidate in candidates[:10]:
            candidate_name = str(candidate.get("name") or "").strip()[:160]
            candidate_homepage = str(candidate.get("homepage_url") or "").strip()[:2048]
            homepage_key = candidate_homepage.rstrip("/").casefold()
            if not publisher_host(candidate_homepage) or publisher_host(candidate_homepage) in seen_hosts or not candidate_name or candidate_name.casefold() in existing_names or homepage_key in existing_homepages or homepage_key in pending_homepages:
                continue
            suggestion: dict[str, object] = {
                "id": str(uuid.uuid4()),
                "keyword": keyword,
                "name": candidate_name,
                "status": "pending",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_by": str(user.username),
                "draft": {
                    "name": candidate_name,
                    "homepage_url": candidate_homepage,
                    "summary": str(candidate.get("summary") or "").strip()[:600],
                    "fit_reason": str(candidate.get("fit_reason") or "").strip()[:600],
                    "language": str(candidate.get("language") or "unknown")[:16],
                    "region": str(candidate.get("region") or "Global")[:32],
                    "source_type": str(candidate.get("source_type") or "specialist_public_media")[:48],
                    "confidence": min(max(_safe_float_value(candidate.get("confidence"), default=0.55), 0.0), 1.0),
                    "evidence": [value[:2048] for value in _string_values(candidate.get("evidence"))[:3] if value.strip()],
                },
            }
            if candidate_name and candidate_homepage:
                rows.insert(0, suggestion)
                pending_homepages.add(homepage_key)
                suggestions.append(suggestion)
                seen_hosts.add(publisher_host(candidate_homepage))
        config["source_suggestions"] = rows[:50]
        histories = dict(config.get("source_discovery_seen") or {})
        histories[history_key] = list(dict.fromkeys((histories.get(history_key) or []) + [str(_object_mapping(row.get("draft")).get("homepage_url") or "") for row in suggestions]))[-100:]
        config["source_discovery_seen"] = dict(list(histories.items())[-20:])
        item.config = config
        await session.commit()
    await _audit(user.id, "source.suggestion.create", assistant_id=assistant_id, details={"keyword": keyword, "count": len(suggestions)})
    return {
        "keyword": keyword,
        "provider": discovery.get("draft_source"),
        "provider_status": discovery.get("provider_status", "succeeded"),
        "page": payload.page,
        "count": len(suggestions),
        "suggestions": suggestions,
        "message": str(discovery.get("message") or "").strip()[:600],
        "alternatives": [value[:160] for value in _string_values(discovery.get("alternatives"))[:3]],
    }


async def decide_source_suggestion(assistant_id: uuid.UUID, suggestion_id: uuid.UUID, *, approve: bool, user: AdminUser) -> dict[str, object]:
    await _require_assistant_access(assistant_id, user, write=True)
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="owner role required to approve source suggestions")

    # Read the suggestion in a short-lived session. Approval may need an
    # OpenAI catalog lookup (up to tens of seconds); never hold a database
    # connection or row lock while waiting on that external service.
    async with SessionLocal() as session:
        item = await session.get(AssistantWorkspace, assistant_id)
        if item is None:
            raise HTTPException(status_code=404, detail="assistant not found")
        config = dict(item.config or {})
        rows = _source_suggestion_rows(config)
        suggestion = next((row for row in rows if str(row.get("id")) == str(suggestion_id)), None)
        if suggestion is None:
            raise HTTPException(status_code=404, detail="source suggestion not found")
        if suggestion.get("status") != "pending":
            return suggestion

    if not approve:
        async with SessionLocal() as session:
            item = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
            if item is None:
                raise HTTPException(status_code=404, detail="assistant not found")
            config = dict(item.config or {})
            rows = _source_suggestion_rows(config)
            suggestion = next((row for row in rows if str(row.get("id")) == str(suggestion_id)), None)
            if suggestion is None:
                raise HTTPException(status_code=404, detail="source suggestion not found")
            if suggestion.get("status") != "pending":
                return suggestion
            # Rejected cards are intentionally not retained in the active
            # queue. The audit event below preserves who decided and when.
            config["source_suggestions"] = [row for row in rows if str(row.get("id")) != str(suggestion_id)]
            item.config = config
            await session.commit()
            result = {"id": str(suggestion_id), "status": "rejected", "removed": True}
    else:
        # Discovery cards intentionally contain only a short summary and
        # website. Resolve the operational feed/adapter details lazily at
        # approval time, outside any database transaction.
        draft = dict(_object_mapping(suggestion.get("draft")))
        context = await _assistant_media_context(assistant_id)
        if not str(draft.get("fetch_url") or "").strip():
            enriched = await _catalog_draft(
                "source",
                str(draft.get("name") or suggestion.get("name") or "").strip(),
                f"تکمیل اطلاعات فنی رسانه برای کلیدواژه: {suggestion.get('keyword') or ''}",
            )
            if isinstance(enriched, dict):
                # Preserve any newer non-empty values saved on the suggestion
                # while filling only the missing operational fields.
                draft = {**enriched, **{key: value for key, value in draft.items() if value not in (None, "")}}

        verification = await _verify_source_draft(draft)
        if verification.get("status") != "ready":
            raise HTTPException(status_code=422, detail="source suggestion could not be verified as readable; review its media details and try again")

        # Re-read and lock only for the short, final write. This serializes
        # source-key allocation and makes a concurrent approval idempotent.
        async with SessionLocal() as session:
            item = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
            if item is None:
                raise HTTPException(status_code=404, detail="assistant not found")
            config = dict(item.config or {})
            rows = _source_suggestion_rows(config)
            suggestion = next((row for row in rows if str(row.get("id")) == str(suggestion_id)), None)
            if suggestion is None:
                raise HTTPException(status_code=404, detail="source suggestion not found")
            if suggestion.get("status") != "pending":
                return suggestion
            latest_draft = _object_mapping(suggestion.get("draft"))
            draft = {
                **draft,
                **{key: value for key, value in latest_draft.items() if value not in (None, "")},
            }
            homepage = str(draft.get("homepage_url") or "").strip()
            fetch_url = str(draft.get("fetch_url") or "").strip()
            if not homepage or not fetch_url:
                raise HTTPException(status_code=422, detail="source suggestion needs valid homepage and feed URLs before approval")
            try:
                homepage = validate_public_url_syntax(homepage)
                fetch_url = validate_public_url_syntax(fetch_url)
            except ValueError:
                raise HTTPException(status_code=422, detail="source suggestion needs valid homepage and feed URLs before approval") from None
            candidate_name = str(draft.get("name") or suggestion.get("name") or "").strip().casefold()
            existing_sources = (await session.execute(select(Source).where(Source.assistant_id == assistant_id))).scalars().all()
            source_limit = assistant_limits(item.config if item else None)["max_sources"]
            if len(existing_sources) >= source_limit:
                raise HTTPException(status_code=409, detail=f"media limit reached ({source_limit})")
            if any(
                candidate_name == str(existing.name or "").strip().casefold()
                or homepage == str(existing.homepage_url or "").strip()
                or fetch_url == str(existing.fetch_url or "").strip()
                for existing in existing_sources
            ):
                raise HTTPException(status_code=409, detail="a matching source already exists in this project")
            existing_keys = [existing.source_key for existing in existing_sources]
            source_key = _next_catalog_key(existing_keys, "S")
            source = Source(
                assistant_id=assistant_id,
                source_key=source_key,
                name=str(draft.get("name") or suggestion.get("name") or "منبع جدید").strip(),
                homepage_url=homepage,
                fetch_url=fetch_url,
                # A model-drafted suggestion may only become a plain public
                # feed; credentialed connectors are configured explicitly.
                adapter=str(draft.get("adapter") or "rss") if str(draft.get("adapter") or "rss") in {"rss", "html", "json", "telegram_public"} else "rss",
                access_policy="public_only",
                credential_ref=None,
                account_ref=str(draft.get("account_ref") or "").strip() or None,
                language=str(draft.get("language") or "fa")[:16],
                output_language=(str(draft.get("output_language") or "source") if str(draft.get("output_language") or "source") in OUTPUT_LANGUAGE_CODES else "source"),
                region=str(draft.get("region") or "IR")[:16],
                priority=min(max(_safe_int_value(draft.get("priority"), default=3), 1), 5),
                access_notes=str(draft.get("access_notes") or ""),
                robots_policy="respect",
                health_status="unknown",
            )
            max_order = await session.scalar(select(Source.display_order).where(Source.assistant_id == assistant_id).order_by(Source.display_order.desc()).limit(1))
            source.display_order = int(max_order or 0) + 10
            session.add(source)
            config["source_suggestions"] = [row for row in rows if str(row.get("id")) != str(suggestion_id)]
            item.config = config
            await session.commit()
            result = {"id": str(suggestion_id), "status": "approved", "source_key": source_key, "removed": True}
    await _audit(user.id, "source.suggestion.approve" if approve else "source.suggestion.reject", assistant_id=assistant_id, details={"suggestion_id": str(suggestion_id)})
    return result


async def draft_topic(assistant_id: uuid.UUID, payload: CatalogDraftRequest, user: AdminUser) -> dict[str, object]:
    await _require_assistant_access(assistant_id, user, write=True)
    return {"kind": "topic", "draft": await _catalog_draft("topic", payload.name.strip(), payload.instruction.strip()), "expires_in_seconds": 300}


async def draft_business(assistant_id: uuid.UUID, payload: BusinessDraftRequest, user: AdminUser) -> dict[str, object]:
    await _require_assistant_access(assistant_id, user, write=True)
    return {"kind": "business", "draft": await _catalog_draft("business", payload.business_name.strip(), payload.instruction.strip()), "expires_in_seconds": 300}


async def create_source(assistant_id: uuid.UUID, payload: SourceCreate, user: AdminUser) -> dict[str, object]:
    await _require_assistant_access(assistant_id, user, write=True)
    async with SessionLocal() as session:
        # Serialize key allocation per workspace so two simultaneous saves
        # cannot receive the same human-readable identifier.
        await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        assistant = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        existing_keys = list((await session.scalars(select(Source.source_key).where(Source.assistant_id == assistant_id))).all())
        source_limit = assistant_limits(assistant.config if assistant else None)["max_sources"]
        if len(existing_keys) >= source_limit:
            raise HTTPException(status_code=409, detail=f"media limit reached ({source_limit})")
        source_key = _next_catalog_key(existing_keys, "S")
        item = Source(
            assistant_id=assistant_id,
            source_key=source_key,
            name=payload.name,
            homepage_url=payload.homepage_url,
            fetch_url=payload.fetch_url,
            adapter=payload.adapter,
            language=payload.language,
            output_language=payload.output_language,
            region=payload.region,
            priority=payload.priority,
            enabled=payload.enabled,
            access_policy=payload.access_policy,
            access_notes=payload.access_notes,
            credential_ref=payload.credential_ref,
            account_ref=payload.account_ref,
            robots_policy="respect",
            health_status="unknown",
        )
        max_order = await session.scalar(select(Source.display_order).where(Source.assistant_id == assistant_id).order_by(Source.display_order.desc()).limit(1))
        item.display_order = int(max_order or 0) + 10
        session.add(item)
        try:
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise HTTPException(status_code=409, detail="source key already exists") from exc
    await _audit(user.id, "source.create", assistant_id=assistant_id, details={"source_key": item.source_key, "generated": True})
    return {"id": str(item.id), "source_key": item.source_key, "enabled": item.enabled}


async def create_public_social_source(
    assistant_id: uuid.UUID,
    payload: PublicSocialSourceCreate,
    user: AdminUser,
) -> dict[str, object]:
    """Create a public Telegram, Instagram, or X source from one handle."""
    await _require_assistant_access(assistant_id, user, write=True)
    descriptor = public_social_source_config(
        payload.platform,
        payload.handle_or_url,
        name=payload.name,
        language=payload.language,
        region=payload.region,
        priority=payload.priority,
    )
    settings = get_settings()
    credential = {
        "telegram_public": None,
        "instagram_public": settings.instagram_source_access_token,
        "x_public": settings.x_source_bearer_token,
    }[str(descriptor["adapter"])]
    enabled = _server_secret_configured(credential) if descriptor["credential_ref"] else True
    if not enabled:
        descriptor["access_notes"] = (
            f"{descriptor['access_notes']} Configure {descriptor['credential_ref']} on the server; "
            "the source remains disabled until the credential is present."
        )
    async with SessionLocal() as session:
        assistant = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        if assistant is None:
            raise HTTPException(status_code=404, detail="assistant not found")
        existing_keys = list((await session.scalars(select(Source.source_key).where(Source.assistant_id == assistant_id))).all())
        source_limit = assistant_limits(assistant.config if assistant else None)["max_sources"]
        if len(existing_keys) >= source_limit:
            raise HTTPException(status_code=409, detail=f"media limit reached ({source_limit})")
        source_key = _next_catalog_key(existing_keys, "S")
        item = Source(
            assistant_id=assistant_id,
            source_key=source_key,
            name=str(descriptor["name"]),
            homepage_url=str(descriptor["homepage_url"]),
            fetch_url=str(descriptor["fetch_url"]),
            adapter=str(descriptor["adapter"]),
            language=str(descriptor["language"]),
            region=str(descriptor["region"]),
            priority=_safe_int_value(descriptor.get("priority")),
            enabled=enabled,
            access_policy="public_only",
            access_notes=str(descriptor["access_notes"]),
            credential_ref=str(descriptor["credential_ref"]) if descriptor["credential_ref"] else None,
            account_ref=str(descriptor["account_ref"]),
            robots_policy="respect",
            health_status="unknown",
            last_error=None if enabled else "connector credential is not configured on the server",
        )
        max_order = await session.scalar(
            select(Source.display_order)
            .where(Source.assistant_id == assistant_id)
            .order_by(Source.display_order.desc())
            .limit(1)
        )
        item.display_order = int(max_order or 0) + 10
        session.add(item)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(status_code=409, detail="this public source already exists in the project") from exc
    await _audit(
        user.id,
        "source.public_social.create",
        assistant_id=assistant_id,
        details={"source_key": item.source_key, "adapter": item.adapter, "account_ref": item.account_ref, "credential_configured": enabled},
    )
    return {
        "id": str(item.id),
        "source_key": item.source_key,
        "adapter": item.adapter,
        "account_ref": item.account_ref,
        "enabled": item.enabled,
        "credential_configured": credential is not None if descriptor["credential_ref"] else True,
    }


async def move_source(source_id: uuid.UUID, payload: OrderMoveRequest, user: AdminUser) -> dict[str, object]:
    async with SessionLocal() as session:
        item = await session.get(Source, source_id, with_for_update=True)
        if item is None:
            raise HTTPException(status_code=404, detail="source not found")
        await _require_assistant_access(item.assistant_id, user, write=True)
        direction = -1 if payload.direction == "up" else 1
        neighbour = (
            await session.execute(
                select(Source)
                .where(Source.assistant_id == item.assistant_id)
                .where(Source.display_order < item.display_order if direction < 0 else Source.display_order > item.display_order)
                .order_by(Source.display_order.desc() if direction < 0 else Source.display_order.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if neighbour is None:
            return {"status": "unchanged", "display_order": item.display_order}
        item.display_order, neighbour.display_order = neighbour.display_order, item.display_order
        await session.commit()
        result = {"status": "moved", "display_order": item.display_order}
    await _audit(user.id, "source.reorder", assistant_id=item.assistant_id, details={"source_id": str(source_id), "direction": payload.direction})
    return result


async def delete_source(source_id: uuid.UUID, user: AdminUser) -> dict[str, str]:
    async with SessionLocal() as session:
        item = await session.get(Source, source_id, with_for_update=True)
        if item is None:
            raise HTTPException(status_code=404, detail="source not found")
        if not is_global_admin(user):
            member = (
                await session.execute(
                    select(AssistantMember).where(
                        AssistantMember.assistant_id == item.assistant_id,
                        AssistantMember.user_id == user.id,
                    )
                )
            ).scalar_one_or_none()
            if not workspace_write_allowed(effective_user_role(user), member.role if member else None):
                raise HTTPException(status_code=403, detail="workspace access denied")
        assistant_id = item.assistant_id
        source_key = item.source_key
        await session.delete(item)
        await session.commit()
    await _audit(user.id, "source.delete", details={"assistant_id": str(assistant_id), "source_key": source_key})
    return {"status": "deleted", "source_key": source_key}


async def update_topic(topic_id: uuid.UUID, payload: TopicUpdate, user: AdminUser) -> dict[str, object]:
    async with SessionLocal() as session:
        item = await session.get(Topic, topic_id, with_for_update=True)
        if item is None: raise HTTPException(status_code=404, detail="topic not found")
        # Keep topic configuration changes workspace-scoped just like source
        # changes; role checks alone are not sufficient for multi-assistant
        # operation.
        if not is_global_admin(user):
            member = (
                await session.execute(
                    select(AssistantMember).where(
                        AssistantMember.assistant_id == item.assistant_id,
                        AssistantMember.user_id == user.id,
                    )
                )
            ).scalar_one_or_none()
            if not workspace_write_allowed(effective_user_role(user), member.role if member else None):
                raise HTTPException(status_code=403, detail="workspace access denied")
        changes = payload.model_dump(exclude_none=True)
        for key, value in changes.items(): setattr(item, key, value)
        # A changed relevance rule must be applied to the workspace's recent
        # unanalysed articles on the next pipeline run.  Existing score rows
        # otherwise make ``score_pending_articles(rescore=False)`` skip them,
        # so lowering a threshold would appear to have no effect until new
        # source items arrive.  Preserve scores for analysed articles because
        # they are part of the audit/history used by feedback reports.
        rescore_fields = {"threshold", "positive_terms", "negative_terms", "definition", "enabled"}
        invalidated = 0
        if rescore_fields.intersection(changes):
            result = await session.execute(
                delete(ArticleTopic)
                .where(ArticleTopic.topic_id == item.id)
                .where(
                    ~select(ArticleAnalysis.id)
                    .where(ArticleAnalysis.article_id == ArticleTopic.article_id)
                    .exists()
                )
            )
            invalidated = int(result.rowcount or 0)
        await session.commit()
    await _audit(
        user.id,
        "topic.update",
        assistant_id=item.assistant_id,
        details={"topic_id": str(topic_id), "fields": sorted(changes), "rescore_invalidated": invalidated},
    )
    return {"id": str(item.id), "topic_key": item.topic_key, "enabled": item.enabled, "updated_fields": sorted(changes), "rescore_invalidated": invalidated}


async def create_topic(assistant_id: uuid.UUID, payload: TopicCreate, user: AdminUser) -> dict[str, object]:
    await _require_assistant_access(assistant_id, user, write=True)
    async with SessionLocal() as session:
        assistant = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        existing_keys = list((await session.scalars(select(Topic.topic_key).where(Topic.assistant_id == assistant_id))).all())
        topic_limit = assistant_limits(assistant.config if assistant else None)["max_topics"]
        if len(existing_keys) >= topic_limit:
            raise HTTPException(status_code=409, detail=f"topic limit reached ({topic_limit})")
        topic_key = _next_catalog_key(existing_keys, "T")
        item = Topic(
            assistant_id=assistant_id,
            topic_key=topic_key,
            name=payload.name,
            definition=payload.definition,
            positive_terms=payload.positive_terms,
            negative_terms=payload.negative_terms,
            importance=payload.importance,
            threshold=payload.threshold,
            enabled=payload.enabled,
            source_revision="backoffice",
        )
        max_order = await session.scalar(select(Topic.display_order).where(Topic.assistant_id == assistant_id).order_by(Topic.display_order.desc()).limit(1))
        item.display_order = int(max_order or 0) + 10
        session.add(item)
        try:
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise HTTPException(status_code=409, detail="topic key already exists") from exc
    await _audit(user.id, "topic.create", assistant_id=assistant_id, details={"topic_key": item.topic_key, "generated": True})
    return {"id": str(item.id), "topic_key": item.topic_key, "enabled": item.enabled}


async def move_topic(topic_id: uuid.UUID, payload: OrderMoveRequest, user: AdminUser) -> dict[str, object]:
    async with SessionLocal() as session:
        item = await session.get(Topic, topic_id, with_for_update=True)
        if item is None:
            raise HTTPException(status_code=404, detail="topic not found")
        await _require_assistant_access(item.assistant_id, user, write=True)
        direction = -1 if payload.direction == "up" else 1
        neighbour = (
            await session.execute(
                select(Topic)
                .where(Topic.assistant_id == item.assistant_id)
                .where(Topic.display_order < item.display_order if direction < 0 else Topic.display_order > item.display_order)
                .order_by(Topic.display_order.desc() if direction < 0 else Topic.display_order.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if neighbour is None:
            return {"status": "unchanged", "display_order": item.display_order}
        item.display_order, neighbour.display_order = neighbour.display_order, item.display_order
        await session.commit()
        result = {"status": "moved", "display_order": item.display_order}
    await _audit(user.id, "topic.reorder", assistant_id=item.assistant_id, details={"topic_id": str(topic_id), "direction": payload.direction})
    return result


async def delete_topic(topic_id: uuid.UUID, user: AdminUser) -> dict[str, str]:
    async with SessionLocal() as session:
        item = await session.get(Topic, topic_id, with_for_update=True)
        if item is None:
            raise HTTPException(status_code=404, detail="topic not found")
        if not is_global_admin(user):
            member = (
                await session.execute(
                    select(AssistantMember).where(
                        AssistantMember.assistant_id == item.assistant_id,
                        AssistantMember.user_id == user.id,
                    )
                )
            ).scalar_one_or_none()
            if not workspace_write_allowed(effective_user_role(user), member.role if member else None):
                raise HTTPException(status_code=403, detail="workspace access denied")
        assistant_id = item.assistant_id
        topic_key = item.topic_key
        await session.delete(item)
        await session.commit()
    await _audit(user.id, "topic.delete", details={"assistant_id": str(assistant_id), "topic_key": topic_key})
    return {"status": "deleted", "topic_key": topic_key}


def _telegram_config(
    config: dict | None,
    *,
    assistant_id: uuid.UUID,
) -> dict[str, object]:
    """Return the effective, non-secret Telegram configuration for a workspace.

    The original Dotin workspace predates per-workspace destinations, so its
    empty workspace configuration intentionally inherits the deployment-managed
    channel IDs. New workspaces never inherit those destinations. This mirrors
    ``settings_for_assistant`` while keeping the bot token private.
    """
    value = (config or {}).get("telegram") or {}
    settings = get_settings()
    inherits_server_destinations = assistant_id == DEFAULT_ASSISTANT_ID
    feedback_in_workspace = "feedback_channel_id" in value
    observer_in_workspace = "observer_channel_id" in value
    feedback_channel_id = (
        value.get("feedback_channel_id")
        if feedback_in_workspace
        else settings.telegram_channel_id if inherits_server_destinations else None
    )
    observer_channel_id = (
        value.get("observer_channel_id")
        if observer_in_workspace
        else settings.telegram_observer_channel_id if inherits_server_destinations else None
    )
    token = settings.telegram_bot_token.get_secret_value() if settings.telegram_bot_token else ""
    token_bot_id = token.partition(":")[0] if token and token.partition(":")[0].isdigit() else None
    bot_id = value.get("bot_id") or token_bot_id
    channels = [
        {
            "key": "feedback",
            "role": "feedback",
            "channel_id": feedback_channel_id,
            "configured": bool(feedback_channel_id),
            "feedback_buttons": True,
            "delivery_mode": "publish_with_feedback",
            "source": "workspace" if feedback_in_workspace else "server_env" if feedback_channel_id else "unset",
        },
        {
            "key": "observer",
            "role": "observer",
            "channel_id": observer_channel_id,
            "configured": bool(observer_channel_id),
            "feedback_buttons": False,
            "delivery_mode": "publish_read_only",
            "source": "workspace" if observer_in_workspace else "server_env" if observer_channel_id else "unset",
        },
    ]
    return {
        "feedback_channel_id": feedback_channel_id,
        "observer_channel_id": observer_channel_id,
        "bot_display_name": value.get("bot_display_name"),
        "bot_username": value.get("bot_username"),
        "bot_id": bot_id,
        # The token remains server-side only; this is a boolean status, never the secret.
        "token_configured": bool(settings.telegram_bot_token),
        "token_source": "server_env",
        "channels": channels,
    }


async def get_assistant_telegram(assistant_id: uuid.UUID, user: AdminUser) -> dict[str, object]:
    await _require_assistant_access(assistant_id, user)
    async with SessionLocal() as session:
        item = await session.get(AssistantWorkspace, assistant_id)
    if item is None:
        raise HTTPException(status_code=404, detail="assistant not found")
    return {
        "assistant_id": str(assistant_id),
        **_telegram_config(item.config, assistant_id=assistant_id),
    }


async def update_assistant_telegram(assistant_id: uuid.UUID, payload: TelegramSettingsUpdate, user: AdminUser) -> dict[str, object]:
    await _require_assistant_access(assistant_id, user, write=True)
    async with SessionLocal() as session:
        item = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        if item is None:
            raise HTTPException(status_code=404, detail="assistant not found")
        config = dict(item.config or {})
        telegram = dict(config.get("telegram") or {})
        for key in payload.model_fields_set:
            telegram[key] = getattr(payload, key)
        config["telegram"] = telegram
        item.config = config
        await session.commit()
    await _audit(user.id, "assistant.telegram.update", assistant_id=assistant_id, details={"fields": sorted(payload.model_fields_set)})
    return {
        "assistant_id": str(assistant_id),
        **_telegram_config(config, assistant_id=assistant_id),
    }


_BUSINESS_FIELDS = (
    "business_name", "description", "products_services", "target_customers", "markets",
    "revenue_model", "strategic_goals", "competitors", "sensitivities", "output_language",
    "output_tone", "source_revision",
)


def _business_payload(item: BusinessProfile) -> dict[str, object]:
    return {"id": int(item.id), "assistant_id": str(item.assistant_id), **{c: getattr(item, c) for c in _BUSINESS_FIELDS}}


async def list_business_profiles(assistant_id: uuid.UUID, user: AdminUser) -> dict[str, object]:
    await _require_assistant_access(assistant_id, user)
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(BusinessProfile).where(BusinessProfile.assistant_id == assistant_id).order_by(BusinessProfile.id)
        )).scalars().all()
        assistant = await session.get(AssistantWorkspace, assistant_id)
    if assistant is None:
        raise HTTPException(status_code=404, detail="assistant not found")
    active_id = str((assistant.config or {}).get("active_business_id") or (rows[0].id if rows else ""))
    return {"assistant_id": str(assistant_id), "active_business_id": active_id, "count": len(rows), "businesses": [_business_payload(row) for row in rows]}


async def get_business_profile(user: AdminUser, assistant_id: uuid.UUID | None = None, profile_id: int | None = None) -> dict[str, object]:
    assistant_id = assistant_id or DEFAULT_ASSISTANT_ID
    await _require_assistant_access(assistant_id, user)
    async with SessionLocal() as session:
        assistant = await session.get(AssistantWorkspace, assistant_id)
        if assistant is None:
            raise HTTPException(status_code=404, detail="assistant not found")
        selected_id = profile_id or (assistant.config or {}).get("active_business_id")
        statement = select(BusinessProfile).where(BusinessProfile.assistant_id == assistant_id)
        if selected_id:
            statement = statement.where(BusinessProfile.id == int(selected_id))
        item = (await session.execute(statement.order_by(BusinessProfile.id))).scalars().first()
    if item is None:
        raise HTTPException(status_code=404, detail="business profile not found")
    return _business_payload(item)


async def create_business_profile(assistant_id: uuid.UUID, payload: BusinessProfileCreate, user: AdminUser) -> dict[str, object]:
    await _require_assistant_access(assistant_id, user, write=True)
    async with SessionLocal() as session:
        assistant = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        profile_count = int(await session.scalar(select(func.count(BusinessProfile.id)).where(BusinessProfile.assistant_id == assistant_id)) or 0)
        profile_limit = assistant_limits(assistant.config if assistant else None)["max_business_profiles"]
        if profile_count >= profile_limit:
            raise HTTPException(status_code=409, detail=f"business profile limit reached ({profile_limit})")
        next_id = int((await session.scalar(select(func.max(BusinessProfile.id)))) or 0) + 1
        item = BusinessProfile(
            id=next_id, assistant_id=assistant_id, source_revision="backoffice",
            business_name=payload.business_name, description=payload.description,
            products_services=payload.products_services, target_customers=payload.target_customers,
            markets=payload.markets, revenue_model=payload.revenue_model or "",
            strategic_goals=payload.strategic_goals or "", competitors=payload.competitors or [],
            sensitivities=payload.sensitivities or [], output_language=payload.output_language,
            output_tone=payload.output_tone,
        )
        session.add(item)
        config = dict(assistant.config or {}) if assistant else {}
        config.setdefault("active_business_id", next_id)
        if assistant:
            assistant.config = config
        await session.commit()
    await _audit(user.id, "business_profile.create", assistant_id=assistant_id, details={"business_id": next_id})
    return _business_payload(item)


async def list_topics(user: AdminUser, assistant_id: uuid.UUID | None = None) -> dict[str, object]:
    if assistant_id is not None:
        await _require_assistant_access(assistant_id, user)
    elif not is_global_admin(user):
        # Without a workspace filter the query spans every tenant; only the
        # owner may read that cross-workspace view.
        raise HTTPException(status_code=403, detail="assistant_id is required")
    async with SessionLocal() as session:
        statement = select(Topic).order_by(Topic.display_order.asc(), Topic.topic_key)
        if assistant_id is not None:
            statement = statement.where(Topic.assistant_id == assistant_id)
        rows = (await session.execute(statement)).scalars().all()
    return {"count": len(rows), "topics": [{"id": str(x.id), "topic_key": x.topic_key, "name": x.name, "definition": x.definition, "positive_terms": x.positive_terms, "negative_terms": x.negative_terms, "importance": x.importance, "threshold": x.threshold, "enabled": x.enabled, "display_order": x.display_order} for x in rows]}


async def update_business_profile(payload: BusinessProfileUpdate, user: AdminUser, *, assistant_id: uuid.UUID | None = None, profile_id: int | None = None) -> dict[str, object]:
    assistant_id = assistant_id or DEFAULT_ASSISTANT_ID
    await _require_assistant_access(assistant_id, user, write=True)
    async with SessionLocal() as session:
        assistant = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        selected_id = profile_id or (assistant.config or {}).get("active_business_id") if assistant else profile_id
        statement = select(BusinessProfile).where(BusinessProfile.assistant_id == assistant_id)
        if selected_id:
            statement = statement.where(BusinessProfile.id == int(selected_id))
        item = (await session.execute(statement.order_by(BusinessProfile.id))).scalars().first()
        if item is None: raise HTTPException(status_code=404, detail="business profile not found")
        changes = payload.model_dump(exclude_none=True)
        for key, value in changes.items(): setattr(item, key, value)
        await session.commit()
    await _audit(user.id, "business_profile.update", assistant_id=assistant_id, details={"business_id": int(item.id), "fields": sorted(changes)})
    return {"updated_fields": sorted(changes), "business_id": int(item.id)}


def _clean_knowledge(payload: dict[str, object]) -> dict[str, list[str]]:
    keys = ("facts", "products_services", "markets", "differentiators", "strategic_goals", "sensitivities", "source_urls")
    cleaned: dict[str, list[str]] = {}
    for key in keys:
        values = payload.get(key) or []
        if not isinstance(values, list):
            values = [values]
        cleaned[key] = list(dict.fromkeys(str(value).strip()[:500] for value in values if str(value).strip()))[:50]
    # URLs are retained only as references; credentials/query tokens are not
    # accepted in this project-scoped knowledge store.
    cleaned["source_urls"] = [value.split("?")[0][:2048] for value in cleaned["source_urls"] if value.startswith(("https://", "http://"))]
    return cleaned


async def get_business_knowledge(assistant_id: uuid.UUID, user: AdminUser) -> dict[str, object]:
    assistant = await _require_assistant_access(assistant_id, user)
    config = assistant.config or {}
    knowledge = _object_mapping(config.get("business_knowledge"))
    return {
        "assistant_id": str(assistant_id),
        "revision": _safe_int_value(knowledge.get("revision")),
        "updated_at": knowledge.get("updated_at"),
        "knowledge": _clean_knowledge(dict(knowledge)),
        "history": _object_list(knowledge.get("history"))[-10:],
    }


async def update_business_knowledge(assistant_id: uuid.UUID, payload: BusinessKnowledgeUpdate, user: AdminUser) -> dict[str, object]:
    assistant = await _require_project_admin(assistant_id, user)
    now = datetime.now(timezone.utc).isoformat()
    incoming = _clean_knowledge(payload.model_dump())
    async with SessionLocal() as session:
        item = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        if item is None:
            raise HTTPException(status_code=404, detail="assistant not found")
        config = dict(item.config or {})
        previous = _object_mapping(config.get("business_knowledge"))
        history = _object_list(previous.get("history"))
        if previous:
            history.append({"revision": _safe_int_value(previous.get("revision")), "updated_at": previous.get("updated_at"), "knowledge": _clean_knowledge(dict(previous))})
        knowledge = {**incoming, "revision": _safe_int_value(previous.get("revision")) + 1, "updated_at": now, "history": history[-10:]}
        # Sanitize only the knowledge document. Sanitizing the whole config
        # used to strip Telegram channel IDs and share-link token hashes.
        config["business_knowledge"] = _sanitize_template_config(knowledge)
        item.config = config
        await session.commit()
    await _audit(user.id, "business_knowledge.update", assistant_id=assistant_id, details={"revision": knowledge["revision"]})
    return {"assistant_id": str(assistant_id), "revision": knowledge["revision"], "updated_at": now, "knowledge": incoming}


async def delete_business_profile(assistant_id: uuid.UUID, profile_id: int, user: AdminUser) -> dict[str, object]:
    await _require_assistant_access(assistant_id, user, write=True)
    async with SessionLocal() as session:
        item = (await session.execute(select(BusinessProfile).where(BusinessProfile.id == profile_id, BusinessProfile.assistant_id == assistant_id).with_for_update())).scalar_one_or_none()
        if item is None:
            raise HTTPException(status_code=404, detail="business profile not found")
        count = await session.scalar(select(func.count(BusinessProfile.id)).where(BusinessProfile.assistant_id == assistant_id))
        if int(count or 0) <= 1:
            raise HTTPException(status_code=409, detail="هر دستیار باید حداقل یک پروفایل کسب‌وکار داشته باشد")
        await session.delete(item)
        assistant = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        if assistant and str((assistant.config or {}).get("active_business_id")) == str(profile_id):
            config = dict(assistant.config or {})
            replacement = await session.scalar(select(BusinessProfile.id).where(BusinessProfile.assistant_id == assistant_id, BusinessProfile.id != profile_id).order_by(BusinessProfile.id))
            config["active_business_id"] = int(replacement) if replacement else None
            assistant.config = config
        await session.commit()
    await _audit(user.id, "business_profile.delete", assistant_id=assistant_id, details={"business_id": profile_id})
    return {"status": "deleted", "business_id": profile_id}


async def get_assistant_runtime_settings(assistant_id: uuid.UUID, user: AdminUser) -> dict[str, object]:
    await _require_assistant_access(assistant_id, user)
    async with SessionLocal() as session:
        assistant = await session.get(AssistantWorkspace, assistant_id)
    if assistant is None:
        raise HTTPException(status_code=404, detail="assistant not found")
    runtime = (assistant.config or {}).get("runtime") or {}
    limits = assistant_limits(assistant.config)
    app_settings = get_settings()
    stored_max_items = int(runtime.get("max_items_per_run", get_settings().max_items_per_run))
    max_items_per_run = min(max(stored_max_items, 1), limits["max_items_per_run"])
    def bounded_int(key: str, default: int, low: int, high: int) -> int:
        try:
            value = int(runtime.get(key, default))
        except (TypeError, ValueError):
            value = default
        return min(max(value, low), high)

    collection_slots = runtime.get("collection_schedule_slots")
    if not isinstance(collection_slots, list):
        collection_slots = []
    response: dict[str, object] = {
        "assistant_id": str(assistant_id),
        "max_items_per_run": max_items_per_run,
        "publish_max_items_per_run": max_items_per_run,
        "processing_max_items_per_day": bounded_int("collection_max_items_per_day", app_settings.processing_max_items_per_day, 1, 1000),
        "freshness_window_days": min(int(runtime.get("freshness_window_days", app_settings.freshness_window_days)), limits["max_freshness_window_days"]),
        "limits": limits,
        "telegram_silent_notifications": bool(runtime.get("telegram_silent_notifications", False)),
        "analysis_model": runtime.get("analysis_model", get_settings().analysis_model),
        "relevance_threshold": runtime.get("relevance_threshold", app_settings.relevance_threshold if assistant_id == DEFAULT_ASSISTANT_ID else 0.0),
        "ai_analysis_ready": app_settings.openai_ready,
        "allowed_feedback_usernames": list(runtime.get("allowed_feedback_usernames", sorted(get_settings().allowed_telegram_username_values))),
        "schedule_slots": list(runtime.get("schedule_slots", [])),
        "timezone": runtime.get("timezone", get_settings().timezone),
        "active_business_id": (assistant.config or {}).get("active_business_id"),
        "collection_owner_only": True,
    }
    # Collection cadence and capacity are account-owner controls.  Do not
    # leak their values to project editors/viewers even when they can read the
    # shared publication settings from this endpoint; the scheduler reads the
    # persisted workspace config internally.
    if is_owner(user):
        # Empty means the safe default: 10:00, 14:00 and 18:00 on each day.
        # The UI expands it to the 7×24 grid for owner editing.
        response.update({
            "collection_enabled": runtime.get("collection_enabled", True) is not False,
            "collection_schedule_slots": collection_slots,
            "collection_schedule_configured": bool(collection_slots),
            "collection_max_items_per_source": bounded_int("collection_max_items_per_source", app_settings.fetch_max_items_per_source, 1, 200),
            "collection_max_items_per_run": bounded_int("collection_max_items_per_run", app_settings.pipeline_max_candidates_per_run, 1, 1000),
            "collection_max_items_per_day": bounded_int("collection_max_items_per_day", app_settings.processing_max_items_per_day, 1, 1000),
        })
    return response


async def update_assistant_runtime_settings(assistant_id: uuid.UUID, payload: AssistantRuntimeSettingsUpdate, user: AdminUser) -> dict[str, object]:
    if payload.model_fields_set & COLLECTION_RUNTIME_FIELDS and not is_owner(user):
        raise HTTPException(status_code=403, detail="owner role required")
    await _require_assistant_access(assistant_id, user, write=True)
    async with SessionLocal() as session:
        assistant = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        if assistant is None:
            raise HTTPException(status_code=404, detail="assistant not found")
        config = dict(assistant.config or {})
        runtime = dict(config.get("runtime") or {})
        values = payload.model_dump(exclude_none=True)
        limits = assistant_limits(config)
        if values.get("max_items_per_run") is not None and values["max_items_per_run"] > limits["max_items_per_run"]:
            raise HTTPException(status_code=422, detail=f"publication limit cannot exceed {limits['max_items_per_run']}")
        if values.get("freshness_window_days") is not None and values["freshness_window_days"] > limits["max_freshness_window_days"]:
            raise HTTPException(status_code=422, detail=f"freshness window cannot exceed {limits['max_freshness_window_days']} days")
        active_business_id = values.pop("active_business_id", None)
        deactivate_business = bool(values.pop("deactivate_business", False))
        for key, value in values.items():
            runtime[key] = value
        config["runtime"] = runtime
        if deactivate_business:
            config["active_business_id"] = None
        elif active_business_id is not None:
            exists = await session.scalar(select(BusinessProfile.id).where(BusinessProfile.id == active_business_id, BusinessProfile.assistant_id == assistant_id))
            if exists is None:
                raise HTTPException(status_code=404, detail="business profile not found")
            config["active_business_id"] = active_business_id
        assistant.config = config
        await session.commit()
    await _audit(user.id, "assistant.runtime.update", assistant_id=assistant_id, details={"fields": sorted(payload.model_fields_set)})
    return await get_assistant_runtime_settings(assistant_id, user)


async def preview_assistant_runtime_settings(
    assistant_id: uuid.UUID,
    payload: RuntimeSettingsPreviewRequest,
    user: AdminUser,
) -> dict[str, object]:
    """Compare a proposed runtime configuration without writing or sending.

    The preview is deliberately deterministic: it reports only values already
    present in the workspace and bounded capacity arithmetic.  It never calls
    Telegram, the scheduler, or an external model.
    """
    if payload.model_fields_set & COLLECTION_RUNTIME_FIELDS and not is_owner(user):
        raise HTTPException(status_code=403, detail="owner role required")
    current = await get_assistant_runtime_settings(assistant_id, user)
    proposed = dict(current)
    values = payload.model_dump(exclude_none=True)
    for key, value in values.items():
        if key not in {"deactivate_business", "active_business_id"}:
            proposed[key] = value
    if payload.active_business_id is not None:
        proposed["active_business_id"] = payload.active_business_id
    if payload.deactivate_business:
        proposed["active_business_id"] = None
    changes = {
        key: {"before": current.get(key), "after": proposed.get(key)}
        for key in ("max_items_per_run", "freshness_window_days", "telegram_silent_notifications", "analysis_model", "relevance_threshold", "schedule_slots", "timezone", "active_business_id", "collection_enabled", "collection_schedule_slots", "collection_max_items_per_source", "collection_max_items_per_run", "collection_max_items_per_day")
        if current.get(key) != proposed.get(key)
    }
    slots = _object_list(proposed.get("schedule_slots"))
    collection_slots = _object_list(proposed.get("collection_schedule_slots"))
    publication_cap = _safe_int_value(proposed.get("max_items_per_run"))
    collection_limits = _object_mapping(current.get("limits"))
    return {
        "assistant_id": str(assistant_id),
        "safe": True,
        "mutated": False,
        "telegram_send_attempted": False,
        "changes": changes,
        "estimated_publications_per_day": len(slots) * publication_cap,
        "estimated_collection_slots_per_day": round(len(collection_slots) / 7, 1),
        "estimated_collection_items_per_day": min(
            _safe_int_value(proposed.get("collection_max_items_per_day"), default=get_settings().processing_max_items_per_day),
            _safe_int_value(proposed.get("collection_max_items_per_run"), default=get_settings().pipeline_max_candidates_per_run)
            * max(1, round(len(collection_slots) / 7)),
        ),
        "processing_max_items_per_day": _safe_int_value(current.get("processing_max_items_per_day"), default=get_settings().processing_max_items_per_day),
        "constraints": {
            "max_publications_per_slot": _safe_int_value(collection_limits.get("max_items_per_run"), default=7),
            "max_freshness_window_days": _safe_int_value(collection_limits.get("max_freshness_window_days"), default=7),
            "schedule_slots_max": 168,
            "collection_schedule_slots_max": 168,
            "collection_max_items_per_source": 200,
            "collection_max_items_per_run": 1000,
            "collection_max_items_per_day": 1000,
        },
        "proposed": {key: proposed.get(key) for key in ("max_items_per_run", "freshness_window_days", "telegram_silent_notifications", "analysis_model", "relevance_threshold", "schedule_slots", "timezone", "active_business_id", "collection_enabled", "collection_schedule_slots", "collection_max_items_per_source", "collection_max_items_per_run", "collection_max_items_per_day")},
    }


async def review_publication(
    assistant_id: uuid.UUID,
    publication_id: uuid.UUID,
    payload: PublicationReviewRequest,
    user: AdminUser,
) -> dict[str, object]:
    """Record an auditable draft → review → approval decision."""
    await _require_assistant_access(assistant_id, user, write=True)
    if payload.state == "approved" and not (is_owner(user) or user.role in {"admin", "assistant_admin"}):
        raise HTTPException(status_code=403, detail="final approval requires a project administrator")
    now = datetime.now(timezone.utc).isoformat()
    async with SessionLocal() as session:
        publication = (await session.execute(
            select(Publication).where(Publication.id == publication_id, Publication.assistant_id == assistant_id).with_for_update()
        )).scalar_one_or_none()
        if publication is None:
            raise HTTPException(status_code=404, detail="publication not found")
        audit = dict(publication.audit or {})
        approval = dict(audit.get("approval") or {})
        history = list(approval.get("history") or [])
        history.append({"state": payload.state, "note": payload.note, "at": now, "by": str(user.id)})
        approval.update({"state": payload.state, "note": payload.note, "updated_at": now, "updated_by": str(user.id), "history": history[-20:]})
        publication.audit = {**audit, "approval": approval}
        publication.updated_at = datetime.now(timezone.utc)
        await session.commit()
    await _audit(user.id, "publication.review", assistant_id=assistant_id, details={"publication_id": str(publication_id), "state": payload.state})
    return {"publication_id": str(publication_id), "assistant_id": str(assistant_id), "approval": approval}


async def publication_explanation(assistant_id: uuid.UUID, analysis_id: uuid.UUID, user: AdminUser) -> dict[str, object]:
    """Return a score/evidence chain made only from persisted source data."""
    await _require_assistant_access(assistant_id, user)
    from app.insights import quality_projection

    async with SessionLocal() as session:
        row = (await session.execute(
            select(ArticleAnalysis, NormalizedArticle, Source)
            .join(NormalizedArticle, NormalizedArticle.id == ArticleAnalysis.article_id)
            .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
            .join(Source, Source.id == SourceItem.source_id)
            .where(ArticleAnalysis.id == analysis_id, ArticleAnalysis.assistant_id == assistant_id)
        )).one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="analysis not found")
        analysis, article, source = row
        topic_rows = (await session.execute(
            select(ArticleTopic, Topic).join(Topic, Topic.id == ArticleTopic.topic_id).where(ArticleTopic.assistant_id == assistant_id, ArticleTopic.article_id == article.id).order_by(ArticleTopic.combined_score.desc())
        )).all()
        cluster_ids = [value for value in (await session.execute(select(ClusterMember.cluster_id).where(ClusterMember.assistant_id == assistant_id, ClusterMember.article_id == article.id))).scalars().all()]
        related_rows: list[Any] = []
        if cluster_ids:
            related_rows.extend((await session.execute(
                select(NormalizedArticle.title, Source.name, NormalizedArticle.canonical_url)
                .join(ClusterMember, ClusterMember.article_id == NormalizedArticle.id)
                .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
                .join(Source, Source.id == SourceItem.source_id)
                .where(ClusterMember.assistant_id == assistant_id, ClusterMember.cluster_id.in_(cluster_ids), NormalizedArticle.id != article.id)
                .limit(20)
            )).all())
    quality = quality_projection(article, source, len(related_rows) + 1)
    return {
        "assistant_id": str(assistant_id),
        "analysis_id": str(analysis_id),
        "article": {"title": article.title, "url": article.canonical_url, "published_at": article.published_at, "language": article.language, "extraction_status": article.extraction_status},
        "source": {"name": source.name, "source_key": source.source_key, "health_status": source.health_status, "url": source.fetch_url},
        "relevance": {"score": max((float(item.combined_score) for item, _topic in topic_rows), default=0.0), "topics": [{"name": topic.name, "combined_score": float(item.combined_score), "lexical_score": float(item.lexical_score), "semantic_score": item.semantic_score, "explanation": item.explanation, "matched_positive": item.matched_positive, "matched_negative": item.matched_negative, "selected": bool(item.selected)} for item, topic in topic_rows]},
        "quality": quality,
        "analysis": {"status": analysis.status, "confidence": float(analysis.confidence), "facts": analysis.facts, "inferences": analysis.inferences, "citations": analysis.citations, "model": analysis.model, "created_at": analysis.created_at},
        "corroboration": [{"title": title, "source": name, "url": url} for title, name, url in related_rows],
        "note": "All values are persisted evidence; no model-generated explanation is added here.",
    }


async def create_share_link(assistant_id: uuid.UUID, payload: ShareLinkCreateRequest, user: AdminUser) -> dict[str, object]:
    await _require_project_admin(assistant_id, user)
    raw_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=payload.expiry_hours)
    async with SessionLocal() as session:
        assistant = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        if assistant is None:
            raise HTTPException(status_code=404, detail="assistant not found")
        if payload.publication_ids:
            ids = list(dict.fromkeys(payload.publication_ids))
            valid = (await session.execute(select(Publication.id).where(Publication.assistant_id == assistant_id, Publication.id.in_(ids), Publication.status != "deleted"))).scalars().all()
            if len(valid) != len(ids):
                raise HTTPException(status_code=422, detail="one or more publications are outside this project")
        else:
            ids = list((await session.execute(select(Publication.id).where(Publication.assistant_id == assistant_id, Publication.status.in_(["published", "edited", "preview"])).order_by(Publication.created_at.desc()).limit(50))).scalars().all())
        link_id = str(uuid.uuid4())
        config = dict(assistant.config or {})
        links = list(config.get("share_links") or [])
        links.append({"id": link_id, "token_hash": hashlib.sha256(raw_token.encode()).hexdigest(), "created_at": now.isoformat(), "expires_at": expires_at.isoformat(), "created_by": str(user.id), "label": payload.label, "publication_ids": [str(value) for value in ids]})
        config["share_links"] = links[-50:]
        assistant.config = config
        await session.commit()
    domain = str(get_settings().domain or "").strip().rstrip("/")
    base = domain if domain.startswith("http://") or domain.startswith("https://") else (f"https://{domain}" if domain else "")
    url = f"{base}/shared/reports/{raw_token}" if base else f"/shared/reports/{raw_token}"
    await _audit(user.id, "share_link.create", assistant_id=assistant_id, details={"link_id": link_id, "expires_at": expires_at.isoformat(), "publication_count": len(ids)})
    return {"id": link_id, "url": url, "expires_at": expires_at, "publication_count": len(ids), "token_returned_once": True}


async def revoke_share_link(assistant_id: uuid.UUID, link_id: str, user: AdminUser) -> dict[str, object]:
    await _require_project_admin(assistant_id, user)
    now = datetime.now(timezone.utc).isoformat()
    async with SessionLocal() as session:
        assistant = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        if assistant is None:
            raise HTTPException(status_code=404, detail="assistant not found")
        config = dict(assistant.config or {})
        links = list(config.get("share_links") or [])
        found = False
        for link in links:
            if str(link.get("id")) == link_id:
                link["revoked_at"] = now
                found = True
        if not found:
            raise HTTPException(status_code=404, detail="share link not found")
        config["share_links"] = links
        assistant.config = config
        await session.commit()
    await _audit(user.id, "share_link.revoke", assistant_id=assistant_id, details={"link_id": link_id})
    return {"id": link_id, "status": "revoked"}


async def resolve_share_link(raw_token: str) -> dict[str, object]:
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        assistants = (await session.execute(select(AssistantWorkspace).where(AssistantWorkspace.deleted_at.is_(None)))).scalars().all()
        match = None
        for assistant in assistants:
            for link in list((assistant.config or {}).get("share_links") or []):
                if hmac.compare_digest(str(link.get("token_hash") or ""), token_hash) and not link.get("revoked_at"):
                    try:
                        expires = datetime.fromisoformat(str(link.get("expires_at")))
                    except (TypeError, ValueError):
                        continue
                    if expires.tzinfo is None:
                        expires = expires.replace(tzinfo=timezone.utc)
                    if expires > now:
                        match = (assistant, link, expires)
                        break
            if match:
                break
        if match is None:
            raise HTTPException(status_code=404, detail="report not found")
        assistant, link, expires = match
        # A view is recorded without exposing the token or any account data.
        # This is intentionally the only mutation performed by the public
        # endpoint and gives the owner an auditable usage signal.
        link["view_count"] = int(link.get("view_count") or 0) + 1
        link["last_viewed_at"] = now.isoformat()
        assistant.config = {**(assistant.config or {}), "share_links": list((assistant.config or {}).get("share_links") or [])}
        await session.commit()
        ids = [uuid.UUID(value) for value in list(link.get("publication_ids") or []) if isinstance(value, str)]
        if not ids:
            return {"assistant": assistant.name, "expires_at": expires, "view_count": link["view_count"], "publications": []}
        rows = (await session.execute(
            select(Publication, ArticleAnalysis, NormalizedArticle, Source)
            .join(ArticleAnalysis, ArticleAnalysis.id == Publication.analysis_id)
            .join(NormalizedArticle, NormalizedArticle.id == ArticleAnalysis.article_id)
            .join(SourceItem, SourceItem.id == NormalizedArticle.source_item_id)
            .join(Source, Source.id == SourceItem.source_id)
            .where(Publication.assistant_id == assistant.id, Publication.id.in_(ids), Publication.status != "deleted")
            .order_by(Publication.created_at.desc())
        )).all()
    return {"assistant": assistant.name, "expires_at": expires, "view_count": link["view_count"], "publications": [{"id": str(publication.id), "title": article.title, "source": source.name, "source_url": article.canonical_url, "article_published_at": article.published_at, "published_at": publication.published_at, "message": publication.message_text, "status": publication.status} for publication, _analysis, article, source in rows]}


async def get_assistant_limits(assistant_id: uuid.UUID, user: AdminUser) -> dict[str, object]:
    """Return capacity controls only to the account owner."""
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="owner role required")
    async with SessionLocal() as session:
        assistant = await session.get(AssistantWorkspace, assistant_id)
    if assistant is None:
        raise HTTPException(status_code=404, detail="assistant not found")
    return {"assistant_id": str(assistant_id), "limits": assistant_limits(assistant.config)}


async def _queue_limit_notifications(session, assistant: AssistantWorkspace, user: AdminUser, previous: dict[str, int], current: dict[str, int]) -> list[str]:
    """Apply reductions and queue notices only when a live value is crossed."""
    source_count = int(await session.scalar(select(func.count(Source.id)).where(Source.assistant_id == assistant.id)) or 0)
    topic_count = int(await session.scalar(select(func.count(Topic.id)).where(Topic.assistant_id == assistant.id)) or 0)
    business_count = int(await session.scalar(select(func.count(BusinessProfile.id)).where(BusinessProfile.assistant_id == assistant.id)) or 0)
    project_count = int(await session.scalar(select(func.count(AssistantWorkspace.id)).where(AssistantWorkspace.deleted_at.is_(None))) or 0)
    runtime = dict((assistant.config or {}).get("runtime") or {})
    old_runtime = dict(runtime)
    notifications: list[str] = []
    if current["max_sources"] < source_count and current["max_sources"] < previous["max_sources"]:
        excess = source_count - current["max_sources"]
        rows = (await session.execute(select(Source).where(Source.assistant_id == assistant.id, Source.enabled.is_(True)).order_by(Source.display_order.desc(), Source.created_at.desc()))).scalars().all()
        for source in rows[:excess]:
            source.enabled = False
            source.health_status = "disabled_limit"
            source.last_error = f"disabled because project media limit is {current['max_sources']}"
        notifications.append(f"سقف رسانه‌های پروژه به {current['max_sources']} کاهش یافت؛ {excess} رسانه اضافی غیرفعال شد و نیاز به رسیدگی دارد.")
    if current["max_topics"] < topic_count and current["max_topics"] < previous["max_topics"]:
        notifications.append(f"سقف موضوع‌های پروژه به {current['max_topics']} کاهش یافته و از تعداد موضوع‌های موجود کمتر است؛ موارد اضافی را بررسی کنید.")
    if current["max_business_profiles"] < business_count and current["max_business_profiles"] < previous["max_business_profiles"]:
        notifications.append(f"سقف بیزینس‌های پروژه به {current['max_business_profiles']} کاهش یافته و از تعداد بیزینس‌های موجود کمتر است؛ رسیدگی کنید.")
    if current["max_projects_per_user"] < project_count and current["max_projects_per_user"] < previous["max_projects_per_user"]:
        notifications.append(f"سقف پروژه‌های قابل تعریف به {current['max_projects_per_user']} کاهش یافته و از تعداد پروژه‌های موجود کمتر است؛ پروژه‌های جدید تا رسیدگی متوقف می‌شوند.")
    if current["max_freshness_window_days"] < int(runtime.get("freshness_window_days", get_settings().freshness_window_days)) and current["max_freshness_window_days"] < previous["max_freshness_window_days"]:
        runtime["freshness_window_days"] = current["max_freshness_window_days"]
        notifications.append(f"پنجره تازگی خبر پروژه به {current['max_freshness_window_days']} روز کاهش یافت؛ تنظیمات کانال را بررسی کنید.")
    if current["max_items_per_run"] < int(runtime.get("max_items_per_run", get_settings().max_items_per_run)) and current["max_items_per_run"] < previous["max_items_per_run"]:
        runtime["max_items_per_run"] = current["max_items_per_run"]
        notifications.append(f"سقف انتشار هر نوبت به {current['max_items_per_run']} خبر کاهش یافت؛ تنظیمات زمان‌بندی را بررسی کنید.")
    if runtime != old_runtime:
        config = dict(assistant.config or {})
        config["runtime"] = runtime
        assistant.config = config
    if not notifications:
        return notifications
    recipients = set((await session.scalars(select(AssistantMember.user_id).where(AssistantMember.assistant_id == assistant.id))).all())
    owner_id = await session.scalar(select(AdminUser.id).where(AdminUser.email == owner_email()))
    if owner_id:
        recipients.add(owner_id)
    config = dict(assistant.config or {})
    inbox = dict(config.get("notifications") or {})
    now = datetime.now(timezone.utc).isoformat()
    for recipient in recipients:
        existing = list(inbox.get(str(recipient)) or [])
        for message in notifications:
            existing.insert(0, {"id": str(uuid.uuid4()), "assistant_id": str(assistant.id), "message": message, "created_at": now, "read": False, "created_by": str(user.username)})
        inbox[str(recipient)] = existing[:100]
    config["notifications"] = inbox
    assistant.config = config
    return notifications


async def update_assistant_limits(assistant_id: uuid.UUID, payload: AssistantLimitsUpdate, user: AdminUser) -> dict[str, object]:
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="owner role required")
    async with SessionLocal() as session:
        assistant = await session.get(AssistantWorkspace, assistant_id, with_for_update=True)
        if assistant is None:
            raise HTTPException(status_code=404, detail="assistant not found")
        config = dict(assistant.config or {})
        previous = assistant_limits(config)
        limits = payload.model_dump()
        config["limits"] = limits
        runtime = dict(config.get("runtime") or {})
        # Lowering a ceiling must never leave the runtime above it.
        runtime["max_items_per_run"] = min(max(int(runtime.get("max_items_per_run", get_settings().max_items_per_run)), 1), limits["max_items_per_run"])
        runtime["freshness_window_days"] = min(max(int(runtime.get("freshness_window_days", get_settings().freshness_window_days)), 1), limits["max_freshness_window_days"])
        config["runtime"] = runtime
        assistant.config = config
        notifications = await _queue_limit_notifications(session, assistant, user, previous, limits)
        await session.commit()
    await _audit(user.id, "assistant.limits.update", assistant_id=assistant_id, details={"fields": sorted(limits)})
    return {"assistant_id": str(assistant_id), "limits": limits, "notifications_created": len(notifications)}


async def list_admin_notifications(user: AdminUser) -> dict[str, object]:
    async with SessionLocal() as session:
        scope = await _visible_project_scope_ids(session, user)
        rows = (await session.execute(select(AssistantWorkspace).where(AssistantWorkspace.deleted_at.is_(None)))).scalars().all()
    items: list[dict[str, object]] = []
    items.extend(dict(item) for item in ((user.preferences or {}).get("global_notifications") or []) if isinstance(item, dict))
    for assistant in rows:
        if scope is not None and assistant.id not in scope:
            continue
        values = ((assistant.config or {}).get("notifications") or {}).get(str(user.id), [])
        items.extend(dict(item) for item in values if isinstance(item, dict))
    items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return {"count": len(items), "unread": sum(1 for item in items if not item.get("read")), "notifications": items[:100]}


async def mark_admin_notifications_read(user: AdminUser) -> dict[str, object]:
    async with SessionLocal() as session:
        account = await session.get(AdminUser, user.id, with_for_update=True)
        rows = (await session.execute(select(AssistantWorkspace).where(AssistantWorkspace.deleted_at.is_(None)))).scalars().all()
        changed = 0
        if account is not None:
            preferences = dict(account.preferences or {})
            global_items = list(preferences.get("global_notifications") or [])
            for item in global_items:
                if not item.get("read"):
                    item["read"] = True
                    changed += 1
            preferences["global_notifications"] = global_items
            account.preferences = preferences
        for assistant in rows:
            config = dict(assistant.config or {})
            inbox = dict(config.get("notifications") or {})
            items = list(inbox.get(str(user.id)) or [])
            for item in items:
                if not item.get("read"):
                    item["read"] = True
                    changed += 1
            if items:
                inbox[str(user.id)] = items
                config["notifications"] = inbox
                assistant.config = config
        await session.commit()
    return {"marked_read": changed}


async def list_news_views(assistant_id: uuid.UUID, user: AdminUser) -> dict[str, object]:
    """Return the current user's saved News List views for one workspace."""
    await _require_assistant_access(assistant_id, user)
    preferences = dict(user.preferences or {})
    grouped = preferences.get("news_views") if isinstance(preferences.get("news_views"), dict) else {}
    values = grouped.get(str(assistant_id), []) if isinstance(grouped, dict) else []
    views = [dict(item) for item in values if isinstance(item, dict) and item.get("name")]
    views.sort(key=lambda item: (not bool(item.get("is_default")), str(item.get("updated_at") or "")), reverse=False)
    return {"assistant_id": str(assistant_id), "views": views[:20]}


async def save_news_view(assistant_id: uuid.UUID, payload: NewsViewRequest, user: AdminUser) -> dict[str, object]:
    """Create or update a bounded personal view without exposing other users' data."""
    await _require_assistant_access(assistant_id, user)
    now = datetime.now(timezone.utc).isoformat()
    async with SessionLocal() as session:
        item = await session.get(AdminUser, user.id, with_for_update=True)
        if item is None:
            raise HTTPException(status_code=404, detail="user not found")
        preferences = dict(item.preferences or {})
        grouped = dict(_object_mapping(preferences.get("news_views")))
        views = _mapping_rows(grouped.get(str(assistant_id)))
        view_id = str(payload.view_id or uuid.uuid4())
        updated = {"id": view_id, "name": payload.name.strip(), "filters": payload.filters, "is_default": bool(payload.is_default), "updated_at": now}
        replaced = False
        for index, value in enumerate(views):
            if str(value.get("id")) == view_id:
                views[index] = updated
                replaced = True
                break
        if not replaced:
            views.insert(0, updated)
        if updated["is_default"]:
            for value in views:
                if str(value.get("id")) != view_id:
                    value["is_default"] = False
        views = views[:20]
        grouped[str(assistant_id)] = views
        preferences["news_views"] = grouped
        item.preferences = preferences
        await session.commit()
    await _audit(user.id, "news_view.save", assistant_id=assistant_id, details={"view_id": view_id, "is_default": bool(payload.is_default)})
    return {"assistant_id": str(assistant_id), "view": updated, "views": views}


async def delete_news_view(assistant_id: uuid.UUID, view_id: uuid.UUID, user: AdminUser) -> dict[str, object]:
    await _require_assistant_access(assistant_id, user)
    async with SessionLocal() as session:
        item = await session.get(AdminUser, user.id, with_for_update=True)
        if item is None:
            raise HTTPException(status_code=404, detail="user not found")
        preferences = dict(item.preferences or {})
        grouped = dict(_object_mapping(preferences.get("news_views")))
        views = _mapping_rows(grouped.get(str(assistant_id)))
        remaining = [value for value in views if str(value.get("id")) != str(view_id)]
        grouped[str(assistant_id)] = remaining
        preferences["news_views"] = grouped
        item.preferences = preferences
        await session.commit()
    await _audit(user.id, "news_view.delete", assistant_id=assistant_id, details={"view_id": str(view_id)})
    return {"assistant_id": str(assistant_id), "deleted": len(remaining) != len(views), "views": remaining}


async def bulk_publications(assistant_id: uuid.UUID, payload: PublicationBulkRequest, user: AdminUser) -> dict[str, object]:
    """Apply non-delivery batch actions to a bounded, project-scoped queue."""
    await _require_assistant_access(assistant_id, user, write=True)
    if payload.action == "approve":
        raise HTTPException(status_code=409, detail="bulk publish is disabled until the safety gate is approved")
    if payload.action == "label" and not (payload.label or "").strip():
        raise HTTPException(status_code=422, detail="label is required for a label action")
    ids = list(dict.fromkeys(payload.ids))
    async with SessionLocal() as session:
        rows = (await session.execute(select(Publication).where(Publication.assistant_id == assistant_id, Publication.id.in_(ids)).with_for_update())).scalars().all()
        now = datetime.now(timezone.utc)
        changed: list[str] = []
        for item in rows:
            audit = dict(item.audit or {})
            audit["bulk_action"] = payload.action
            audit["bulk_action_at"] = now.isoformat()
            audit["bulk_action_by"] = str(user.username)
            audit["bulk_previous_status"] = item.status
            if payload.action == "label":
                audit["label"] = (payload.label or "").strip()
            elif payload.action == "archive":
                item.status = "archived"
            elif payload.action == "reject":
                item.status = "rejected"
            item.audit = audit
            item.updated_at = now
            changed.append(str(item.id))
        await session.commit()
    await _audit(user.id, "publication.bulk", assistant_id=assistant_id, details={"action": payload.action, "requested": len(ids), "changed": len(changed), "label": payload.label})
    return {"assistant_id": str(assistant_id), "action": payload.action, "changed": changed, "count": len(changed), "skipped": [str(value) for value in ids if str(value) not in set(changed)]}


async def undo_bulk_publications(assistant_id: uuid.UUID, payload: PublicationBulkUndoRequest, user: AdminUser) -> dict[str, object]:
    await _require_assistant_access(assistant_id, user, write=True)
    ids = list(dict.fromkeys(payload.ids))
    async with SessionLocal() as session:
        rows = (await session.execute(select(Publication).where(Publication.assistant_id == assistant_id, Publication.id.in_(ids)).with_for_update())).scalars().all()
        now = datetime.now(timezone.utc)
        changed: list[str] = []
        for item in rows:
            audit = dict(item.audit or {})
            previous = audit.get("bulk_previous_status")
            if not previous or audit.get("bulk_action_by") != str(user.username):
                continue
            item.status = str(previous)
            audit["bulk_undone_at"] = now.isoformat()
            audit["bulk_undone_by"] = str(user.username)
            item.audit = audit
            item.updated_at = now
            changed.append(str(item.id))
        await session.commit()
    await _audit(user.id, "publication.bulk.undo", assistant_id=assistant_id, details={"requested": len(ids), "changed": len(changed)})
    return {"assistant_id": str(assistant_id), "changed": changed, "count": len(changed)}


async def list_admin_incidents(user: AdminUser, assistant_id: uuid.UUID | None = None) -> dict[str, object]:
    """Expose actionable notifications plus missing-collection freshness alerts.

    ``/ready`` reports process health, not whether every assistant is still
    collecting. Owner-only synthetic incidents close that observability gap
    without making one workspace's pipeline state visible to other members.
    They are recomputed from successful job history, so clearing a notification
    cannot accidentally hide an ongoing collection outage.
    """
    payload = await list_admin_notifications(user)
    incidents: list[dict[str, object]] = []
    for item in _mapping_rows(payload.get("notifications")):
        if assistant_id and str(item.get("assistant_id")) != str(assistant_id):
            continue
        message = str(item.get("message") or "")
        lower = message.lower()
        severity = "critical" if any(word in lower for word in ("بحرانی", "critical", "failed", "خطا")) else ("warning" if any(word in lower for word in ("هشدار", "warning", "نیازمند")) else "info")
        incidents.append({**item, "severity": severity, "status": "closed" if item.get("read") else "open", "suggested_action": "health_check" if "رسانه" in message or "media" in lower else "review"})
    if is_owner(user):
        now = datetime.now(timezone.utc)
        stale_after = timedelta(hours=36)
        async with SessionLocal() as session:
            scope = await _visible_project_scope_ids(session, user)
            statement = select(AssistantWorkspace).where(
                AssistantWorkspace.deleted_at.is_(None),
                AssistantWorkspace.status == "active",
            )
            if assistant_id is not None:
                statement = statement.where(AssistantWorkspace.id == assistant_id)
            if scope is not None:
                statement = statement.where(AssistantWorkspace.id.in_(scope))
            workspaces = (await session.execute(statement.order_by(AssistantWorkspace.name))).scalars().all()
            workspace_ids = [workspace.id for workspace in workspaces]
            source_counts: dict[uuid.UUID, int] = {}
            source_monitoring_since: dict[uuid.UUID, datetime] = {}
            last_success_by_workspace: dict[uuid.UUID, datetime] = {}
            if workspace_ids:
                source_rows = (await session.execute(
                    select(Source.assistant_id, func.count(Source.id), func.max(Source.updated_at))
                    .where(
                        Source.assistant_id.in_(workspace_ids),
                        Source.enabled.is_(True),
                    )
                    .group_by(Source.assistant_id)
                )).all()
                source_counts = {source_assistant_id: int(count) for source_assistant_id, count, _ in source_rows}
                source_monitoring_since = {
                    source_assistant_id: updated_at
                    for source_assistant_id, _, updated_at in source_rows
                    if updated_at is not None
                }
                success_rows = (await session.execute(
                    select(JobRun.assistant_id, func.max(JobRun.finished_at))
                    .where(
                        JobRun.assistant_id.in_(workspace_ids),
                        JobRun.job_type == "market_pipeline",
                        JobRun.status == "succeeded",
                        JobRun.finished_at.is_not(None),
                    )
                    .group_by(JobRun.assistant_id)
                )).all()
                last_success_by_workspace = {
                    assistant_id: finished_at
                    for assistant_id, finished_at in success_rows
                    if finished_at is not None
                }
            for workspace in workspaces:
                runtime = (workspace.config or {}).get("runtime") or {}
                if runtime.get("collection_enabled", True) is False:
                    continue
                source_count = source_counts.get(workspace.id, 0)
                if source_count == 0:
                    continue
                finished_at = last_success_by_workspace.get(workspace.id)
                baselines = [
                    value for value in (finished_at, source_monitoring_since.get(workspace.id))
                    if value is not None
                ]
                if not baselines:
                    continue
                monitoring_baseline = max(baselines)
                if (now - monitoring_baseline) <= stale_after:
                    continue
                incidents.append({
                    "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"bee-researcher:collection-stale:{workspace.id}")),
                    "assistant_id": str(workspace.id),
                    "assistant_name": workspace.name,
                    "message_key": "collection_stale",
                    "last_success_at": finished_at.isoformat() if finished_at else None,
                    "source_count": source_count,
                    "severity": "critical" if finished_at is None else "warning",
                    "status": "open",
                    "suggested_action": "freshness",
                    "is_freshness_alert": True,
                })
    incidents.sort(key=lambda item: (
        bool(item.get("is_freshness_alert")),
        item.get("severity") == "critical",
        str(item.get("created_at") or item.get("last_success_at") or ""),
    ), reverse=True)
    return {"count": len(incidents), "open": sum(1 for item in incidents if item.get("status") == "open"), "incidents": incidents[:100]}


async def close_admin_incident(incident_id: uuid.UUID, user: AdminUser) -> dict[str, object]:
    async with SessionLocal() as session:
        rows = (await session.execute(select(AssistantWorkspace).where(AssistantWorkspace.deleted_at.is_(None)))).scalars().all()
        scope = await _visible_project_scope_ids(session, user)
        changed = False
        for assistant in rows:
            if scope is not None and assistant.id not in scope:
                continue
            config = dict(assistant.config or {})
            inbox = dict(config.get("notifications") or {})
            values = list(inbox.get(str(user.id)) or [])
            for item in values:
                if str(item.get("id")) == str(incident_id):
                    item["read"] = True
                    item["closed_at"] = datetime.now(timezone.utc).isoformat()
                    changed = True
            if values:
                inbox[str(user.id)] = values
                config["notifications"] = inbox
                assistant.config = config
        await session.commit()
    if changed:
        await _audit(user.id, "incident.close", details={"incident_id": str(incident_id)})
    return {"incident_id": str(incident_id), "closed": changed}


async def list_admin_users(user: AdminUser) -> dict[str, object]:
    async with SessionLocal() as session:
        rows = (await session.execute(select(AdminUser).order_by(AdminUser.created_at))).scalars().all()
        memberships = (await session.execute(select(AssistantMember, AssistantWorkspace).join(AssistantWorkspace, AssistantWorkspace.id == AssistantMember.assistant_id))).all()
        scope = await _visible_project_scope_ids(session, user)
    by_user: dict[uuid.UUID, list[dict[str, object]]] = {}
    for member, assistant in memberships:
        if scope is not None and assistant.id not in scope:
            continue
        by_user.setdefault(member.user_id, []).append({"assistant_id": str(assistant.id), "assistant_name": assistant.name, "role": member.role})
    visible_rows = list(rows) if is_owner(user) else [
        x for x in rows
        if can_view_admin_user(user, x)
        and (x.id == user.id or by_user.get(x.id))
    ]
    unique_rows = _dedupe_admin_rows(visible_rows, current_user_id=user.id, project_access=by_user)
    return {"count": len(unique_rows), "users": [{"id": str(x.id), "username": x.username, "role": effective_user_role(x), "stored_role": x.role, "is_owner": is_owner(x), "active": x.active, "login_method": x.login_method, "email": x.email if is_owner(user) else None, "can_manage": x.id != user.id and (is_owner(user) or (not is_owner(x) and role_rank(x) < role_rank(user))), "created_at": x.created_at.isoformat(), "project_access": by_user.get(x.id, []), **user_portal_access_payload(x), "can_manage_user_portal": (is_owner(user) or user.role == "admin") and can_view_admin_user(user, x)} for x in unique_rows]}


def _dedupe_admin_rows(
    rows: list[AdminUser],
    *,
    current_user_id: uuid.UUID,
    project_access: dict[uuid.UUID, list[dict[str, object]]],
) -> list[AdminUser]:
    """Return one canonical security-row per username.

    The owner account was historically allowed to exist with a legacy stored
    role, so a data repair can temporarily expose two rows with the same
    username.  Keep the current session identity when available; otherwise
    retain the duplicate that carries the most project membership metadata.
    """
    unique_rows: list[AdminUser] = []
    selected_by_username: dict[str, AdminUser] = {}
    for candidate in rows:
        key = str(candidate.username or "").strip().casefold()
        existing = selected_by_username.get(key)
        if existing is None:
            selected_by_username[key] = candidate
            unique_rows.append(candidate)
            continue
        candidate_preferred = (
            candidate.id == current_user_id
            or (
                existing.id != current_user_id
                and len(project_access.get(candidate.id, [])) > len(project_access.get(existing.id, []))
            )
        )
        if candidate_preferred:
            unique_rows[unique_rows.index(existing)] = candidate
            selected_by_username[key] = candidate
    return unique_rows


async def update_user_portal_access(
    user_id: uuid.UUID,
    payload: UserPortalAccessUpdate,
    user: AdminUser,
) -> dict[str, object]:
    """Grant/revoke User-service access without changing project roles.

    Only the configured owner or a global-admin account can change these
    flags.  A project-scoped admin can only act on a user visible in its own
    project scope, preserving the same hierarchy used by the Security page.
    """

    if not (is_owner(user) or user.role == "admin"):
        raise HTTPException(status_code=403, detail="owner or global admin role required")
    async with SessionLocal() as session:
        item = await session.get(AdminUser, user_id, with_for_update=True)
        if item is None:
            raise HTTPException(status_code=404, detail="admin user not found")
        if not can_view_admin_user(user, item):
            raise HTTPException(status_code=403, detail="user is outside your account scope")
        ensure_can_manage_account(user, item)
        scope = await _ensure_user_manage_scope(session, user_id, user)
        if scope is not None and user_id != user.id:
            # _ensure_user_manage_scope already checked shared project access;
            # retain the local variable to make that boundary explicit.
            _ = scope
        if payload.feedback_enabled and not payload.enabled:
            raise HTTPException(status_code=422, detail="feedback access requires User-service access")
        if (is_owner(item) or item.role == "admin") and not payload.enabled:
            raise HTTPException(status_code=422, detail="owner and global admin accounts always have User-service access")
        preferences = dict(item.preferences or {}) if isinstance(item.preferences, dict) else {}
        preferences["user_portal_access"] = {
            "enabled": bool(payload.enabled),
            "feedback_enabled": bool(payload.feedback_enabled),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": str(user.username),
        }
        item.preferences = preferences
        await session.commit()
    await _audit(user.id, "admin_user.user_portal_access", details={"user_id": str(user_id), "enabled": payload.enabled, "feedback_enabled": payload.feedback_enabled})
    return {"id": str(item.id), "username": item.username, **user_portal_access_payload(item)}


async def create_admin_user(payload: AdminUserRequest, user: AdminUser) -> dict[str, object]:
    if not is_owner(user) and user.role not in {"admin", "assistant_admin"}:
        raise HTTPException(status_code=403, detail="project admin role required")
    # User-service grants are account-level privileges.  A project assistant
    # administrator may create accounts and assign project memberships, but
    # must never be able to smuggle a portal or feedback grant through the
    # generic user-creation endpoint.  Only the configured owner or an
    # account-level admin can set these flags (the dedicated Account panel
    # uses the same authorization boundary).
    if (payload.user_portal_access is not None or payload.user_feedback_access is not None) and not (
        is_owner(user) or user.role == "admin"
    ):
        raise HTTPException(status_code=403, detail="owner or global admin role required")
    if payload.role == "owner":
        raise HTTPException(status_code=422, detail="the owner account is configured separately")
    async with SessionLocal() as session:
        scope = await _project_admin_scope_ids(session, user)
        selected = set(payload.assistant_ids or [])
        if scope is not None:
            if not selected or not selected.issubset(scope):
                raise HTTPException(status_code=403, detail="selected projects are outside your project scope")
            if _ROLE_RANK.get(payload.role, 0) >= _ROLE_RANK.get(effective_user_role(user), 0):
                raise HTTPException(status_code=403, detail="cannot grant a role equal to or higher than your own")
        if payload.role in {"admin", "assistant_admin"} and not selected:
            raise HTTPException(status_code=422, detail="an admin user must have at least one project assignment")
        if payload.user_feedback_access and not (payload.user_portal_access or payload.role == "admin"):
            raise HTTPException(status_code=422, detail="feedback access requires User-service access")
        item = AdminUser(username=payload.username.lower(), password_hash=_hash_password(payload.password), role=payload.role, active=True)
        if payload.user_portal_access is not None or payload.user_feedback_access is not None:
            item.preferences = {
                "user_portal_access": {
                    "enabled": bool(payload.user_portal_access),
                    "feedback_enabled": bool(payload.user_feedback_access),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "updated_by": str(user.username),
                }
            }
        session.add(item)
        await session.flush()
        if selected:
            assistants_rows = (await session.execute(select(AssistantWorkspace).where(AssistantWorkspace.id.in_(selected)))).scalars().all()
            if len(assistants_rows) != len(selected):
                raise HTTPException(status_code=404, detail="one or more selected projects do not exist")
            member_role = "admin" if payload.role in {"admin", "assistant_admin"} else "editor" if payload.role == "editor" else "viewer"
            for assistant_id in selected:
                session.add(AssistantMember(assistant_id=assistant_id, user_id=item.id, role=member_role))
        try:
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise HTTPException(status_code=409, detail="username already exists") from exc
    await _audit(user.id, "admin_user.create", details={"username": item.username, "role": item.role})
    return {"id": str(item.id), "username": item.username, "role": item.role, "active": item.active}


async def update_admin_user(user_id: uuid.UUID, payload: AdminUserUpdate, user: AdminUser) -> dict[str, object]:
    """Update account metadata without ever exposing or accepting a password hash."""
    if not is_owner(user) and user.role not in {"admin", "assistant_admin"}:
        raise HTTPException(status_code=403, detail="project admin role required")
    if user_id == user.id and (payload.active is False or payload.role not in (None, "owner", "admin")):
        raise HTTPException(status_code=422, detail="the current owner/admin account cannot be deactivated or demoted")
    async with SessionLocal() as session:
        item = await session.get(AdminUser, user_id, with_for_update=True)
        if item is None:
            raise HTTPException(status_code=404, detail="admin user not found")
        await _ensure_user_manage_scope(session, user_id, user)
        if is_owner(item) and not is_owner(user):
            raise HTTPException(status_code=403, detail="the owner account cannot be changed")
        # Rank is checked against the target's *current* role as well as
        # the requested one: a lower role can never reset, rename, disable
        # or re-role a peer or superior.
        ensure_can_manage_account(user, item)
        if not is_owner(user) and payload.role is not None and _ROLE_RANK.get(payload.role, 0) >= role_rank(user):
            raise HTTPException(status_code=403, detail="cannot grant a role equal to or higher than your own")
        changes = payload.model_dump(exclude_none=True)
        portal_enabled = changes.pop("user_portal_access", None)
        feedback_enabled = changes.pop("user_feedback_access", None)
        if portal_enabled is not None or feedback_enabled is not None:
            if not (is_owner(user) or user.role == "admin"):
                raise HTTPException(status_code=403, detail="owner or global admin role required")
            current_access = user_portal_access_payload(item)
            current_portal, current_feedback = current_access["user_portal_access"], current_access["user_feedback_access"]
            next_portal = current_portal if portal_enabled is None else bool(portal_enabled)
            next_feedback = current_feedback if feedback_enabled is None else bool(feedback_enabled)
            if next_feedback and not next_portal:
                raise HTTPException(status_code=422, detail="feedback access requires User-service access")
            if (is_owner(item) or item.role == "admin") and not next_portal:
                raise HTTPException(status_code=422, detail="owner and global admin accounts always have User-service access")
            preferences = dict(item.preferences or {}) if isinstance(item.preferences, dict) else {}
            preferences["user_portal_access"] = {"enabled": next_portal, "feedback_enabled": next_feedback, "updated_at": datetime.now(timezone.utc).isoformat(), "updated_by": str(user.username)}
            item.preferences = preferences
        if "username" in changes:
            changes["username"] = changes["username"].strip().lower()
        if is_owner(item) and changes.get("active") is False:
            raise HTTPException(status_code=422, detail="the owner account cannot be deactivated")
        for key, value in changes.items():
            setattr(item, key, value)
        try:
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise HTTPException(status_code=409, detail="username already exists") from exc
        if changes.get("active") is False:
            await session.execute(delete(AdminSession).where(AdminSession.user_id == user_id))
            await session.commit()
    await _audit(user.id, "admin_user.update", details={"user_id": str(user_id), "fields": sorted(changes)})
    return {"id": str(item.id), "username": item.username, "role": item.role, "active": item.active, "updated_fields": sorted(changes)}


async def manage_admin_user(user_id: uuid.UUID, payload: AdminUserManageUpdate, user: AdminUser) -> dict[str, object]:
    """Atomically update identity, role, password and project memberships."""
    if not is_owner(user) and user.role not in {"admin", "assistant_admin"}:
        raise HTTPException(status_code=403, detail="project admin role required")
    async with SessionLocal() as session:
        item = await session.get(AdminUser, user_id, with_for_update=True)
        if item is None:
            raise HTTPException(status_code=404, detail="admin user not found")
        scope = await _ensure_user_manage_scope(session, user_id, user)
        target_is_owner = is_owner(item)
        if target_is_owner and not is_owner(user):
            raise HTTPException(status_code=403, detail="the owner account cannot be changed")
        if user_id == user.id and (payload.active is False or payload.role not in (None, "admin")):
            raise HTTPException(status_code=422, detail="the current owner/admin account cannot be deactivated or demoted")
        if target_is_owner and payload.active is False:
            raise HTTPException(status_code=422, detail="the owner account cannot be deactivated")
        # Checked against the target's current role, not only the requested
        # one, so a lower role can never reset or disable a superior.
        ensure_can_manage_account(user, item)
        if not is_owner(user) and payload.role is not None and _ROLE_RANK.get(payload.role, 0) >= role_rank(user):
            raise HTTPException(status_code=403, detail="cannot grant a role equal to or higher than your own")
        if payload.new_password is not None:
            if user_id == user.id:
                if not payload.current_password or not _check_password(payload.current_password, item.password_hash):
                    raise HTTPException(status_code=401, detail="current password is incorrect")
                if payload.current_password == payload.new_password:
                    raise HTTPException(status_code=422, detail="new password must differ from current password")
            item.password_hash = _hash_password(payload.new_password)
            await session.execute(delete(AdminSession).where(AdminSession.user_id == user_id))
        changes = payload.model_dump(exclude_none=True, exclude={"new_password", "current_password", "assistant_ids", "user_portal_access", "user_feedback_access"})
        if "username" in changes:
            changes["username"] = changes["username"].strip().lower()
        for key, value in changes.items():
            setattr(item, key, value)
        # Ownership follows the owner e-mail, so a username or stored-role
        # edit can neither demote the owner nor promote anybody else.
        effective_role = changes.get("role", "owner" if target_is_owner else item.role)
        if payload.user_portal_access is not None or payload.user_feedback_access is not None:
            if not (is_owner(user) or user.role == "admin"):
                raise HTTPException(status_code=403, detail="owner or global admin role required")
            current_portal, current_feedback = user_portal_access_payload(item)["user_portal_access"], user_portal_access_payload(item)["user_feedback_access"]
            next_portal = current_portal if payload.user_portal_access is None else bool(payload.user_portal_access)
            next_feedback = current_feedback if payload.user_feedback_access is None else bool(payload.user_feedback_access)
            if next_feedback and not next_portal:
                raise HTTPException(status_code=422, detail="feedback access requires User-service access")
            if (is_owner(item) or effective_role == "admin") and not next_portal:
                raise HTTPException(status_code=422, detail="owner and global admin accounts always have User-service access")
            preferences = dict(item.preferences or {}) if isinstance(item.preferences, dict) else {}
            preferences["user_portal_access"] = {"enabled": next_portal, "feedback_enabled": next_feedback, "updated_at": datetime.now(timezone.utc).isoformat(), "updated_by": str(user.username)}
            item.preferences = preferences
        if payload.assistant_ids is not None:
            selected = set(payload.assistant_ids)
            if scope is not None and not selected.issubset(scope):
                raise HTTPException(status_code=403, detail="selected projects are outside your project scope")
            if effective_role in {"admin", "assistant_admin"} and not selected:
                raise HTTPException(status_code=422, detail="an admin user must have at least one project assignment")
            if effective_role == "owner":
                await session.execute(delete(AssistantMember).where(AssistantMember.user_id == user_id))
            else:
                assistants_rows = (await session.execute(select(AssistantWorkspace).where(AssistantWorkspace.id.in_(selected)))).scalars().all()
                if len(assistants_rows) != len(selected):
                    raise HTTPException(status_code=404, detail="one or more selected projects do not exist")
                membership_query = select(AssistantMember).where(AssistantMember.user_id == user_id).with_for_update()
                if scope is not None:
                    membership_query = membership_query.where(AssistantMember.assistant_id.in_(scope))
                memberships = (await session.execute(membership_query)).scalars().all()
                member_role = "admin" if effective_role in {"admin", "assistant_admin"} else "editor" if effective_role == "editor" else "viewer"
                for member in memberships:
                    if member.assistant_id not in selected:
                        await session.delete(member)
                    else:
                        member.role = member_role
                existing = {member.assistant_id for member in memberships}
                for assistant_id in selected - existing:
                    session.add(AssistantMember(assistant_id=assistant_id, user_id=user_id, role=member_role))
        if payload.active is False:
            await session.execute(delete(AdminSession).where(AdminSession.user_id == user_id))
        try:
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise HTTPException(status_code=409, detail="username already exists") from exc
    await _audit(user.id, "admin_user.manage", details={"user_id": str(user_id), "fields": sorted(changes), "memberships_updated": payload.assistant_ids is not None, "password_changed": payload.new_password is not None})
    return {"id": str(item.id), "username": item.username, "role": "owner" if is_owner(item) else item.role, "active": item.active, "updated_fields": sorted(changes)}


async def delete_admin_user(user_id: uuid.UUID, user: AdminUser) -> dict[str, str]:
    """Permanently remove an account and all of its project memberships."""
    if not is_global_admin(user):
        raise HTTPException(status_code=403, detail="admin role required")
    if user_id == user.id:
        raise HTTPException(status_code=422, detail="the current admin account cannot be deleted")
    async with SessionLocal() as session:
        item = await session.get(AdminUser, user_id, with_for_update=True)
        if item is None:
            raise HTTPException(status_code=404, detail="admin user not found")
        if is_owner(item):
            raise HTTPException(status_code=403, detail="the owner account cannot be deleted")
        if item.role == "admin" and item.active:
            active_admins = await session.scalar(
                select(func.count(AdminUser.id)).where(AdminUser.role == "admin", AdminUser.active.is_(True))
            )
            if int(active_admins or 0) <= 1:
                raise HTTPException(status_code=409, detail="the last active admin cannot be deleted")
        # Explicit deletes keep the operation safe on installations upgraded
        # before the FK cascade was applied and make access removal obvious.
        await session.execute(delete(AdminSession).where(AdminSession.user_id == user_id))
        await session.execute(delete(AssistantMember).where(AssistantMember.user_id == user_id))
        username = item.username
        await session.delete(item)
        await session.commit()
    await _audit(user.id, "admin_user.delete", details={"user_id": str(user_id), "username": username})
    return {"status": "deleted", "user_id": str(user_id), "username": username}


async def list_active_sessions(user: AdminUser, current_token: str | None) -> dict[str, object]:
    current_hash = hashlib.sha256(current_token.encode()).hexdigest() if current_token else None
    async with SessionLocal() as session:
        scope = await _visible_project_scope_ids(session, user)
        visible_user_ids: set[uuid.UUID] | None = None
        if scope is not None:
            visible_user_ids = {user.id}
            visible_user_ids.update((await session.execute(
                select(AssistantMember.user_id).where(AssistantMember.assistant_id.in_(scope))
            )).scalars().all())
        rows = (await session.execute(
            select(AdminSession, AdminUser)
            .join(AdminUser, AdminUser.id == AdminSession.user_id)
            .where(AdminSession.expires_at > datetime.now(timezone.utc))
            .where(AdminSession.user_id.in_(visible_user_ids) if visible_user_ids is not None else true())
            .order_by(AdminSession.created_at.desc())
        )).all()
        if scope is not None:
            rows = [row for row in rows if can_view_admin_user(user, row[1])]
    return {
        "count": len(rows),
        "sessions": [{
            "id": str(item.id),
            "username": account.username,
            "created_at": item.created_at.isoformat(),
            "expires_at": item.expires_at.isoformat(),
            "current": bool(current_hash and hmac.compare_digest(item.token_hash, current_hash)),
        } for item, account in rows],
    }


async def revoke_session(session_id: uuid.UUID, user: AdminUser, current_token: str | None) -> dict[str, str]:
    if not is_owner(user) and user.role not in {"admin", "assistant_admin"}:
        raise HTTPException(status_code=403, detail="project admin role required")
    current_hash = hashlib.sha256(current_token.encode()).hexdigest() if current_token else None
    async with SessionLocal() as session:
        item = await session.get(AdminSession, session_id, with_for_update=True)
        if item is None:
            raise HTTPException(status_code=404, detail="session not found")
        await _ensure_user_manage_scope(session, item.user_id, user)
        target = await session.get(AdminUser, item.user_id)
        if target is not None:
            ensure_can_manage_account(user, target)
        if current_hash and hmac.compare_digest(item.token_hash, current_hash):
            raise HTTPException(status_code=422, detail="current session cannot be revoked here")
        await session.delete(item)
        await session.commit()
    await _audit(user.id, "admin.session.revoke", details={"session_id": str(session_id)})
    return {"status": "session_revoked"}


async def revoke_other_sessions(user: AdminUser, current_token: str | None) -> dict[str, object]:
    if not is_owner(user) and user.role not in {"admin", "assistant_admin"}:
        raise HTTPException(status_code=403, detail="project admin role required")
    current_hash = hashlib.sha256(current_token.encode()).hexdigest() if current_token else None
    async with SessionLocal() as session:
        # Select first, then delete by primary key.  This avoids driver-specific
        # rowcount behaviour on a table DELETE and makes the current-session
        # exclusion explicit and testable.
        query = select(AdminSession).where(AdminSession.user_id == user.id)
        if current_hash:
            query = query.where(AdminSession.token_hash != current_hash)
        rows = (await session.execute(query)).scalars().all()
        for row in rows:
            await session.delete(row)
        await session.commit()
    count = len(rows)
    await _audit(user.id, "admin.session.revoke_others", details={"count": count})
    return {"status": "sessions_revoked", "count": count}


class GoogleAccessGrant(BaseModel):
    """Owner-managed Gmail allowlist entry."""

    email: str = Field(min_length=6, max_length=320)
    # Attach the address to an existing account instead of creating one.
    user_id: uuid.UUID | None = None
    username: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_.-]{3,128}$")
    role: Literal["admin", "editor", "viewer", "assistant_admin", "analyst"] = "viewer"
    login_method: Literal["google", "both"] = "google"
    password: str | None = Field(default=None, min_length=12, max_length=256)
    assistant_ids: list[uuid.UUID] | None = None


class GoogleAccessUpdate(BaseModel):
    login_method: Literal["google", "both"] | None = None
    active: bool | None = None
    role: Literal["admin", "editor", "viewer", "assistant_admin", "analyst"] | None = None
    password: str | None = Field(default=None, min_length=12, max_length=256)


def _require_owner(user: AdminUser) -> None:
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="owner role required")


def _google_access_payload(item: AdminUser) -> dict[str, object]:
    return {
        "id": str(item.id),
        "username": item.username,
        "email": item.email,
        "login_method": item.login_method,
        "role": effective_user_role(item),
        "active": item.active,
        "is_owner": is_owner(item),
        "linked": bool(item.google_sub),
        "has_password": bool(item.password_hash),
    }


def _validated_gmail(value: str) -> str:
    email = normalize_email(value)
    if not is_gmail(email):
        raise HTTPException(status_code=422, detail="only @gmail.com addresses can use Google sign-in")
    return email


async def list_google_access(user: AdminUser) -> dict[str, object]:
    _require_owner(user)
    async with SessionLocal() as session:
        rows = (await session.execute(select(AdminUser).where(AdminUser.email.is_not(None)).order_by(AdminUser.created_at))).scalars().all()
    return {
        "google_login_configured": get_settings().google_login_ready,
        "owner_email": owner_email(),
        "count": len(rows),
        "accounts": [_google_access_payload(row) for row in rows],
    }


async def grant_google_access(payload: GoogleAccessGrant, user: AdminUser) -> dict[str, object]:
    _require_owner(user)
    email = _validated_gmail(payload.email)
    if email == owner_email():
        raise HTTPException(status_code=422, detail="the owner address is reserved for the owner account")
    async with SessionLocal() as session:
        if await session.scalar(select(AdminUser.id).where(AdminUser.email == email)) is not None:
            raise HTTPException(status_code=409, detail="this Gmail address already has access")
        if payload.user_id is not None:
            item = await session.get(AdminUser, payload.user_id, with_for_update=True)
            if item is None:
                raise HTTPException(status_code=404, detail="admin user not found")
            if is_owner(item):
                raise HTTPException(status_code=422, detail="the owner account is managed automatically")
            if item.email:
                raise HTTPException(status_code=409, detail="this account already has a Gmail address")
        else:
            username = (payload.username or "").strip().lower() or await _unique_username(session, email.split("@", 1)[0])
            item = AdminUser(username=username, role=payload.role, active=True, password_hash=None)
            session.add(item)
        if payload.login_method == "both" and not (item.password_hash or payload.password):
            raise HTTPException(status_code=422, detail="a password is required for Gmail + password sign-in")
        if payload.login_method == "google":
            item.password_hash = None
        elif payload.password:
            item.password_hash = _hash_password(payload.password)
        item.email = email
        item.google_sub = None
        item.login_method = payload.login_method
        await session.flush()
        if payload.assistant_ids:
            selected = set(payload.assistant_ids)
            found = (await session.execute(select(AssistantWorkspace.id).where(AssistantWorkspace.id.in_(selected)))).scalars().all()
            if len(found) != len(selected):
                raise HTTPException(status_code=404, detail="one or more selected projects do not exist")
            existing = set((await session.execute(select(AssistantMember.assistant_id).where(AssistantMember.user_id == item.id))).scalars().all())
            member_role = "admin" if item.role in {"admin", "assistant_admin"} else "editor" if item.role == "editor" else "viewer"
            for assistant_id in selected - existing:
                session.add(AssistantMember(assistant_id=assistant_id, user_id=item.id, role=member_role))
        # The sign-in contract changed: close every existing session.
        await session.execute(delete(AdminSession).where(AdminSession.user_id == item.id))
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(status_code=409, detail="username or Gmail address already exists") from exc
    await _audit(user.id, "google_access.grant", details={"user_id": str(item.id), "login_method": item.login_method})
    return _google_access_payload(item)


async def update_google_access(user_id: uuid.UUID, payload: GoogleAccessUpdate, user: AdminUser) -> dict[str, object]:
    _require_owner(user)
    async with SessionLocal() as session:
        item = await session.get(AdminUser, user_id, with_for_update=True)
        if item is None or not item.email:
            raise HTTPException(status_code=404, detail="Gmail access not found")
        if is_owner(item) and (payload.active is False or payload.role is not None):
            raise HTTPException(status_code=422, detail="the owner account cannot be disabled or re-roled")
        method = payload.login_method or item.login_method
        if method == "both" and not (item.password_hash or payload.password):
            raise HTTPException(status_code=422, detail="a password is required for Gmail + password sign-in")
        revoke_sessions = False
        if payload.login_method == "google" and item.password_hash:
            item.password_hash = None
            revoke_sessions = True
        if payload.password and method == "both":
            item.password_hash = _hash_password(payload.password)
            revoke_sessions = True
        if payload.login_method:
            item.login_method = payload.login_method
        if payload.role is not None:
            item.role = payload.role
        if payload.active is not None:
            item.active = payload.active
            revoke_sessions = revoke_sessions or payload.active is False
        if revoke_sessions:
            await session.execute(delete(AdminSession).where(AdminSession.user_id == item.id))
        await session.commit()
    await _audit(user.id, "google_access.update", details={"user_id": str(user_id), "fields": sorted(payload.model_dump(exclude_none=True, exclude={"password"}))})
    return _google_access_payload(item)


async def revoke_google_access(user_id: uuid.UUID, user: AdminUser) -> dict[str, object]:
    _require_owner(user)
    async with SessionLocal() as session:
        item = await session.get(AdminUser, user_id, with_for_update=True)
        if item is None or not item.email:
            raise HTTPException(status_code=404, detail="Gmail access not found")
        if is_owner(item):
            raise HTTPException(status_code=422, detail="the owner Gmail access cannot be removed")
        item.email = None
        item.google_sub = None
        item.login_method = "password"
        if not item.password_hash:
            # Without a password the account has no remaining sign-in path.
            item.active = False
        await session.execute(delete(AdminSession).where(AdminSession.user_id == item.id))
        await session.commit()
    await _audit(user.id, "google_access.revoke", details={"user_id": str(user_id)})
    return {"id": str(user_id), "status": "revoked", "active": item.active}


async def record_admin_feedback(analysis_id: uuid.UUID, *, value: str, note: str | None, actor_key: str | None, user: AdminUser) -> dict[str, object]:
    """Authenticated HTTP feedback: the actor is always the signed-in account.

    The analysis must belong to a workspace the account can access, and the
    workspace feedback allowlist is still enforced by ``record_feedback``.
    """
    from app.pipeline_service import record_feedback

    actor = str(user.username or "").strip().lower()
    requested = str(actor_key or "").strip().lower().lstrip("@")
    if requested and requested != actor:
        raise HTTPException(status_code=403, detail="feedback can only be recorded as the signed-in account")
    async with SessionLocal() as session:
        workspace_id = await session.scalar(select(ArticleAnalysis.assistant_id).where(ArticleAnalysis.id == analysis_id))
    if workspace_id is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    await _require_assistant_access(workspace_id, user)
    try:
        result = await record_feedback(analysis_id, actor_key=actor, value=value, note=note, source="api")
    except ValueError as exc:
        status = 403 if str(exc) == "feedback actor is not authorized" else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    await _audit(user.id, "feedback.record", assistant_id=workspace_id, details={"analysis_id": str(analysis_id), "value": value})
    return result
