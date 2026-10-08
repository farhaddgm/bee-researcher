"""Small security controls for the control plane.

Redis is the shared, bounded brute-force counter. Authentication deliberately
fails closed when the counter cannot be checked: allowing an unknown number of
password attempts is the less safe failure mode for this private back-office.
Keys contain one-way digests of identity and client address and never contain
credentials.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import ipaddress
from contextvars import ContextVar

from redis.asyncio import Redis
from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import Settings


ADMIN_SESSION_COOKIE = "research_bee_admin_session"
CSRF_COOKIE = "research_bee_admin_csrf"
USER_CSRF_COOKIE = "research_bee_user_csrf"
request_activity: ContextVar[bool] = ContextVar("request_activity", default=True)

def is_trusted_proxy(host: str, settings: Settings) -> bool:
    try:
        address = ipaddress.ip_address(host)
        return any(address in ipaddress.ip_network(c.strip(), strict=False)
                   for c in settings.trusted_proxy_cidrs.split(",") if c.strip())
    except ValueError:
        return False


_BOT_TOKEN_RE = re.compile(r"(https?://api\.telegram\.org/bot)\d{6,20}:[A-Za-z0-9_-]+", re.IGNORECASE)
_BEARER_RE = re.compile(r"(Bearer\s+)[^\s,;]+", re.IGNORECASE)
_SECRET_QUERY_RE = re.compile(r"(?i)([?&](?:token|access_token|api_key|apikey|secret|password|auth|signature)=)[^&\s]+")
_URL_CREDENTIAL_RE = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@")
_SECRET_FIELD_RE = re.compile(r'''(?ix)(["']?(?:password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|cookie|set-cookie)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;}]+)''')
_API_KEY_RE = re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}\b")


def redact_sensitive_text(value: str, *, limit: int = 1000) -> str:
    """Keep operational errors useful without copying credentials to logs/UI."""
    text = str(value or "")
    text = _BOT_TOKEN_RE.sub(r"\1[REDACTED]", text)
    text = _BEARER_RE.sub(r"\1[REDACTED]", text)
    text = _SECRET_QUERY_RE.sub(r"\1[REDACTED]", text)
    text = _URL_CREDENTIAL_RE.sub(r"\1[REDACTED]@", text)
    text = _SECRET_FIELD_RE.sub(r"\1[REDACTED]", text)
    text = _API_KEY_RE.sub("[REDACTED]", text)
    return text[:limit]


def _service_key_material(settings: Settings) -> bytes:
    if settings.csrf_signing_secret:
        return settings.csrf_signing_secret.get_secret_value().encode("utf-8")
    if settings.environment.strip().lower() == "production":
        raise HTTPException(status_code=503, detail="service signing secret is not configured")
    return b"development-only-signing-key-do-not-deploy"


def service_signing_key(settings: Settings, purpose: str) -> bytes:
    """Return a purpose-separated HMAC key derived from the service secret."""
    return hmac.new(hashlib.sha256(_service_key_material(settings)).digest(), purpose.encode("utf-8"), hashlib.sha256).digest()


def _csrf_signature(nonce: str, session_token: str, settings: Settings) -> str:
    key = hashlib.sha256(_service_key_material(settings)).digest()
    return hmac.new(key, f"{nonce}.{session_token}".encode("utf-8"), hashlib.sha256).hexdigest()


def new_csrf_token(session_token: str, settings: Settings) -> str:
    """Create a session-bound signed double-submit token."""
    nonce = secrets.token_urlsafe(32)
    return f"{nonce}.{_csrf_signature(nonce, session_token, settings)}"


def csrf_token_matches(
    cookie_value: str | None,
    header_value: str | None,
    session_token: str | None,
    settings: Settings,
) -> bool:
    """Validate a signed session-bound token in constant time."""
    if not cookie_value or not header_value or not session_token or cookie_value != header_value or len(cookie_value) > 512:
        return False
    try:
        nonce, signature = cookie_value.split(".", 1)
    except ValueError:
        return False
    if not nonce or not signature or len(signature) != 64:
        return False
    return hmac.compare_digest(signature, _csrf_signature(nonce, session_token, settings))


def login_attempt_key(settings: Settings, username: str, client_address: str) -> str:
    identity = username.strip().lower()[:512]
    digest = hashlib.sha256(identity.encode("utf-8", "replace")).hexdigest()
    return f"{settings.queue_namespace}:security:login:v2:{digest}"


def login_ip_attempt_key(settings: Settings, client_address: str) -> str:
    digest = hashlib.sha256(client_address.strip().encode("utf-8", "replace")[:256]).hexdigest()
    return f"{settings.queue_namespace}:security:login-ip:v1:{digest}"


async def _close(redis: Redis) -> None:
    close = getattr(redis, "aclose", None)
    if close is not None:
        await close()


# Reserve before verification, in one transaction. Concurrent workers cannot
# all pass a read-before-increment check. TTL is fixed from the first attempt.
_RESERVE = """
for i,key in ipairs(KEYS) do
  local value = redis.call('GET', key)
  if value and (not tonumber(value) or tonumber(value) >= tonumber(ARGV[i])) then return 1 end
end
for i,key in ipairs(KEYS) do
  local count = redis.call('INCR', key)
  if count == 1 then redis.call('EXPIRE', key, ARGV[#KEYS+1]) end
end
return 0
"""

async def _reserve(settings: Settings, keys: list[str], limits: list[int]) -> bool:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        result = await redis.eval(_RESERVE, len(keys), *keys, *limits, settings.login_window_seconds)
        if result not in (0, 1):
            raise ValueError("invalid security counter result")
        return bool(result)
    except (RedisError, OSError, ValueError, TypeError):
        raise HTTPException(status_code=503, detail="authentication temporarily unavailable", headers={"Retry-After": "30"}) from None
    finally:
        try:
            await _close(redis)
        except Exception:
            pass


async def login_attempts_exceeded(settings: Settings, username: str, client_address: str) -> bool:
    return await _reserve(settings, [login_attempt_key(settings, username, client_address),
        login_ip_attempt_key(settings, client_address), f"{settings.queue_namespace}:security:login-global:v1"],
        [settings.login_max_attempts, settings.login_ip_max_attempts, 1200])


async def record_login_failure(settings: Settings, username: str, client_address: str) -> None:
    # The attempt was already atomically reserved; failure never double counts.
    return None


async def login_ip_attempts_exceeded(settings: Settings, client_address: str) -> bool:
    return await _reserve(settings, [login_ip_attempt_key(settings, client_address),
        f"{settings.queue_namespace}:security:login-global:v1"], [settings.login_ip_max_attempts, 1200])


async def record_ip_login_failure(settings: Settings, client_address: str) -> None:
    return None


async def clear_login_failures(settings: Settings, username: str, client_address: str) -> None:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis.delete(login_attempt_key(settings, username, client_address))
    except (RedisError, OSError):
        # A failed cleanup only preserves the stricter existing budget.
        return
    finally:
        try:
            await _close(redis)
        except Exception:
            pass
