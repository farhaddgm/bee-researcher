from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
NAMESPACE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")


class Settings(BaseSettings):
    app_name: str = "Bee Researcher"
    version: str = "3.38.0"
    build_revision: str = "unknown"
    image_digest: str | None = None
    environment: str = "production"
    # Public host names are used only to validate same-origin requests behind
    # the reverse proxy. They are not credentials and may be omitted locally.
    domain: str | None = None
    legacy_domain: str | None = None
    # Read-only profile display/sync only. Intentionally not a pipeline input.
    contenter_api_url: str | None = None
    contenter_web_url: str | None = None
    contenter_token: SecretStr | None = None
    contenter_sync_seconds: int = Field(default=900, ge=60, le=86400)
    contenter_cache_max_age_seconds: int = Field(default=86400, ge=60, le=604800)

    postgres_db: str
    postgres_user: str
    postgres_password: SecretStr
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    database_schema: str = "market_intelligence"
    # The back-office fans out several read requests during a cold load.
    # Keep the pool bounded, but large enough for normal concurrent requests;
    # deployments can tune these values without changing application code.
    database_pool_size: int = Field(default=10, ge=3, le=30)
    database_max_overflow: int = Field(default=10, ge=0, le=30)
    database_pool_timeout_seconds: int = Field(default=15, ge=1, le=120)

    redis_password: SecretStr
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_database: int = Field(default=2, ge=1, le=15)
    queue_namespace: str = "market-intelligence"

    timezone: str = "Europe/Berlin"
    schedule_times: str = "08:00,11:00,14:00,17:00,22:00"
    # This is a publication cap, not an ingestion or analysis cap.
    max_items_per_run: int = Field(default=7, ge=1, le=7)
    # Processing is intentionally much larger than the delivery cap. The
    # pipeline may inspect up to 1000 newly extracted articles per project/day
    # and publish only the configured per-slot maximum.
    processing_max_items_per_day: int = Field(default=1000, ge=1, le=1000)
    freshness_window_days: int = Field(default=3, ge=1, le=7)
    business_name: str = "داتین"

    fetch_timeout_seconds: int = Field(default=20, ge=3, le=120)
    fetch_max_bytes: int = Field(default=5_000_000, ge=100_000, le=20_000_000)
    fetch_max_items_per_source: int = Field(default=50, ge=1, le=200)
    fetch_concurrency: int = Field(default=3, ge=1, le=10)
    fetch_lock_ttl_seconds: int = Field(default=180, ge=30, le=1800)
    # Identify the product consistently in source requests.  Workspace names
    # (for example Dotin) are runtime data and must not leak into the service
    # identity or make a new deployment look like a different product.
    fetch_user_agent: str = "BeeResearcher/1.0 (private market research)"

    extraction_concurrency: int = Field(default=3, ge=1, le=10)
    extraction_max_chars: int = Field(default=60_000, ge=2_000, le=250_000)
    extraction_min_complete_chars: int = Field(default=700, ge=100, le=10_000)
    store_raw_html: bool = True
    raw_html_retention_days: int = Field(default=30, ge=1, le=365)
    normalized_retention_days: int = Field(default=365, ge=30, le=3650)

    relevance_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    clustering_threshold: float = Field(default=0.58, ge=0.1, le=1.0)
    pipeline_max_candidates_per_run: int = Field(default=1000, ge=1, le=1000)
    model_max_requests_per_run: int = Field(default=5, ge=0, le=50)
    model_daily_request_cap: int = Field(default=30, ge=0, le=500)
    model_daily_input_char_cap: int = Field(default=500_000, ge=10_000, le=20_000_000)
    analysis_max_input_chars: int = Field(default=24_000, ge=2_000, le=200_000)
    analysis_model: str = "gpt-5.6-luna"
    embedding_model: str = "text-embedding-3-small"
    model_input_usd_per_million_tokens: float = Field(default=0.2, ge=0)
    model_output_usd_per_million_tokens: float = Field(default=1.2, ge=0)
    external_analysis_approved: bool = False
    # Discovery has a separate, bounded budget and never sends project data.
    discovery_model: str = "gpt-4.1-mini"
    google_search_api_key: SecretStr | None = None
    google_search_engine_id: str | None = None
    relevance_batch_size: int = Field(default=8, ge=1, le=20)
    relevance_max_requests_per_run: int = Field(default=10, ge=0, le=100)
    relevance_daily_request_cap: int = Field(default=100, ge=0, le=1000)

    scheduler_enabled: bool = True
    scheduler_poll_seconds: int = Field(default=30, ge=5, le=300)
    # A slot stays due for this many minutes, so a long scheduler tick that
    # crosses the slot minute delivers late instead of silently skipping it.
    # Claims keep delivery idempotent; older slots are recorded as missed.
    schedule_grace_minutes: int = Field(default=10, ge=1, le=30)
    missed_run_recovery_hours: int = Field(default=8, ge=1, le=48)
    auto_publish: bool = False
    pilot_mode: bool = True
    weekly_report_weekday: int = Field(default=6, ge=0, le=6)
    weekly_report_time: str = "20:00"
    allowed_telegram_usernames: str = "farhaadnoroozi"
    telegram_polling_enabled: bool = True

    admin_bootstrap_username: str = "admin"
    # The account owner is identified only by this verified e-mail address.
    # Usernames are editable by administrators and are therefore never an
    # ownership signal.
    owner_email: str = "farhad.dgm@gmail.com"
    # Used only once by migration 0037 to attach ``owner_email`` to the
    # pre-existing owner row; runtime authorization never reads it.
    admin_owner_username: str = "admin"
    # The bootstrap password can create the owner account only while the
    # account table is empty (first installation).
    admin_bootstrap_password: SecretStr | None = None
    # Google sign-in (OpenID Connect, authorization code + PKCE). The button is
    # enabled when all three values are configured.
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_redirect_uri: str | None = None
    # Legacy setting retained for old deployment configuration only.
    admin_session_ttl_hours: int = Field(default=6, ge=1, le=6)
    # Approved Contenter-style rolling lifetime; hours above is legacy metadata.
    # Reader sessions are additionally bounded by the next local 02:00.
    account_session_ttl_days: int = Field(default=30, ge=1, le=30)
    admin_cookie_secure: bool = True
    # Prefer a service-only signing key for CSRF tokens. The security module
    # retains a derived fallback so existing deployments keep their contract
    # until the owner provisions this independent secret.
    csrf_signing_secret: SecretStr | None = Field(default=None, min_length=32)
    # TOTP secrets are encrypted at rest with this dedicated key.  The MFA
    # module falls back to csrf_signing_secret for existing deployments until
    # this independent secret is provisioned.
    mfa_encryption_secret: SecretStr | None = None
    # A bounded per-username/per-client counter protects the sign-in endpoint
    # without turning Redis into an authentication dependency.
    login_max_attempts: int = Field(default=10, ge=3, le=20)
    login_ip_max_attempts: int = Field(default=30, ge=10, le=200)
    login_window_seconds: int = Field(default=900, ge=60, le=3600)
    max_request_body_bytes: int = Field(default=2_000_000, ge=64_000, le=10_000_000)

    # The nonce-based strict policy is the default. Legacy handlers/styles
    # are migrated to ordinary listeners and nonce-authorized rules at runtime;
    # compatibility remains an explicit rollback only, not the normal posture.
    csp_report_only: bool = True
    csp_strict: bool = True
    csp_report_uri: str = "/admin/api/security/csp-report"

    openai_api_key: SecretStr | None = None
    telegram_bot_token: SecretStr | None = None
    # Dedicated source credentials are environment-only. The back-office
    # stores a reference name, never the secret itself.
    telegram_source_bot_token: SecretStr | None = None
    instagram_source_access_token: SecretStr | None = None
    x_source_bearer_token: SecretStr | None = None
    # Extra hosts (comma-separated) that may receive a connector credential,
    # e.g. an owner-approved gateway. Provider API hosts are always allowed.
    connector_gateway_hosts: str = ""
    telegram_channel_id: str | None = None
    telegram_observer_channel_id: str | None = None
    telegram_silent_notifications: bool = False
    # WhatsApp is intentionally disabled until the owner supplies official
    # Meta credentials and a public webhook. Secrets never enter the sheet.
    whatsapp_enabled: bool = False
    whatsapp_destination_type: Literal["cloud_api", "channel"] = "cloud_api"
    whatsapp_business_account_id: str | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_channel_id: str | None = None
    whatsapp_webhook_public_url: str | None = None
    whatsapp_access_token: SecretStr | None = None
    whatsapp_webhook_verify_token: SecretStr | None = None
    # Per-assistant, owner-managed safe message templates. The deployment
    # default remains the renderer's tested legacy layout when this is empty.
    message_templates: dict[str, dict[str, object]] = Field(default_factory=dict)

    model_config = SettingsConfigDict(
        env_prefix="MARKET_INTELLIGENCE_",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("database_schema")
    @classmethod
    def isolated_schema_only(cls, value: str) -> str:
        if value != "market_intelligence":
            raise ValueError("database schema must remain market_intelligence")
        return value

    @field_validator("queue_namespace")
    @classmethod
    def valid_queue_namespace(cls, value: str) -> str:
        if not NAMESPACE_PATTERN.fullmatch(value):
            raise ValueError("queue namespace must be a lowercase kebab-case identifier")
        if value in {"ai-assistant", "research", "tasks"}:
            raise ValueError("queue namespace collides with an existing runtime")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value

    @field_validator("schedule_times")
    @classmethod
    def normalized_schedule_times(cls, value: str) -> str:
        values = [part.strip() for part in value.split(",") if part.strip()]
        if not values or any(not TIME_PATTERN.fullmatch(part) for part in values):
            raise ValueError("schedule_times must be comma-separated HH:MM values")
        return ",".join(dict.fromkeys(values))

    @field_validator("weekly_report_time")
    @classmethod
    def valid_weekly_report_time(cls, value: str) -> str:
        value = value.strip()
        if not TIME_PATTERN.fullmatch(value):
            raise ValueError("weekly_report_time must use HH:MM")
        return value

    @field_validator("domain", "legacy_domain")
    @classmethod
    def valid_public_domain(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip().lower().rstrip(".")
        if "://" in value or "/" in value or any(char.isspace() for char in value):
            raise ValueError("public domain must be a host name without a scheme or path")
        return value

    @field_validator("csp_report_uri")
    @classmethod
    def valid_csp_report_uri(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith("/") or value.startswith("//") or "://" in value:
            raise ValueError("csp_report_uri must be a same-origin path")
        return value

    @model_validator(mode="after")
    def enforce_production_cookie_security(self) -> "Settings":
        if self.environment.strip().lower() == "production":
            if not self.admin_cookie_secure:
                raise ValueError("admin_cookie_secure must be enabled in production")
            bootstrap = self.admin_bootstrap_password.get_secret_value() if self.admin_bootstrap_password else ""
            if bootstrap.strip().lower() in {"change_me_to_a_long_random_password", "change-me", "password", "admin"}:
                raise ValueError("admin_bootstrap_password must be replaced before production startup")
        return self

    @field_validator("telegram_channel_id")
    @classmethod
    def valid_telegram_channel_id(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not re.fullmatch(r"(?:-100\d{6,20}|\d{5,20})", value):
            raise ValueError("telegram_channel_id must be a numeric private chat or channel id")
        return value

    @field_validator("telegram_observer_channel_id")
    @classmethod
    def valid_observer_channel_id(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not re.fullmatch(r"(?:-100\d{6,20}|\d{5,20})", value):
            raise ValueError("telegram_observer_channel_id must be a numeric private chat or channel id")
        return value

    @field_validator("whatsapp_destination_type")
    @classmethod
    def valid_whatsapp_destination_type(cls, value: str) -> Literal["cloud_api", "channel"]:
        value = value.strip().lower()
        if value == "cloud_api":
            return "cloud_api"
        if value == "channel":
            return "channel"
        raise ValueError("whatsapp_destination_type must be cloud_api or channel")

    @field_validator("whatsapp_webhook_public_url")
    @classmethod
    def valid_whatsapp_webhook_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not value.startswith("https://"):
            raise ValueError("whatsapp_webhook_public_url must use HTTPS")
        return value

    @field_validator("owner_email")
    @classmethod
    def valid_owner_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("owner_email must be an e-mail address")
        return value

    @field_validator("google_client_id", "google_redirect_uri")
    @classmethod
    def empty_google_value_is_unset(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return value.strip()

    @field_validator("google_redirect_uri")
    @classmethod
    def valid_google_redirect_uri(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise ValueError("google_redirect_uri must use HTTPS")
        return value

    @field_validator(
        "openai_api_key",
        "google_search_api_key",
        "telegram_bot_token",
        "csrf_signing_secret",
        "mfa_encryption_secret",
        "google_client_secret",
        "telegram_source_bot_token",
        "instagram_source_access_token",
        "x_source_bearer_token",
        "whatsapp_access_token",
        "whatsapp_webhook_verify_token",
        mode="before",
    )
    @classmethod
    def empty_secret_is_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def schedule_time_values(self) -> tuple[str, ...]:
        return tuple(self.schedule_times.split(","))

    @property
    def allowed_telegram_username_values(self) -> frozenset[str]:
        return frozenset(
            value.strip().lower().lstrip("@")
            for value in self.allowed_telegram_usernames.split(",")
            if value.strip()
        )

    @property
    def google_login_ready(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret and self.google_redirect_uri)

    @property
    def connector_gateway_host_values(self) -> frozenset[str]:
        return frozenset(
            value.strip().lower().rstrip(".")
            for value in self.connector_gateway_hosts.split(",")
            if value.strip()
        )

    @property
    def telegram_ready(self) -> bool:
        return self.telegram_bot_token is not None and self.telegram_channel_id is not None

    @property
    def openai_ready(self) -> bool:
        return self.external_analysis_approved and self.openai_api_key is not None

    @property
    def database_url(self) -> str:
        user = quote(self.postgres_user, safe="")
        password = quote(self.postgres_password.get_secret_value(), safe="")
        database = quote(self.postgres_db, safe="")
        return (
            f"postgresql+asyncpg://{user}:{password}@{self.postgres_host}:"
            f"{self.postgres_port}/{database}"
        )

    @property
    def redis_url(self) -> str:
        password = quote(self.redis_password.get_secret_value(), safe="")
        return (
            f"redis://:{password}@{self.redis_host}:{self.redis_port}/"
            f"{self.redis_database}"
        )


@lru_cache
def get_settings() -> Settings:
    # Required values are loaded from the environment by BaseSettings; mypy
    # cannot see those values at construction time.
    return Settings()  # type: ignore[call-arg]
