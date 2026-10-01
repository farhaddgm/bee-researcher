"""Google sign-in (OpenID Connect authorization code flow with PKCE).

The flow state (state, PKCE verifier, nonce, target portal) lives in a short
signed cookie, so no server storage is needed.  The ID token is received
directly from Google's token endpoint over TLS, authenticated with the client
secret; per OpenID Connect Core 1.0 §3.1.3.7 (6) that TLS channel validates
the issuer in place of the token signature.  Issuer, audience, expiry, nonce
and ``email_verified`` are still checked.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.config import Settings
from app.security_controls import service_signing_key


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})
FLOW_COOKIE = "research_bee_google_flow"
FLOW_COOKIE_PATH = "/auth/google"
FLOW_TTL_SECONDS = 600
CLOCK_SKEW_SECONDS = 60
PORTALS = frozenset({"admin", "user"})
# Machine-readable codes shown by the login pages.
ERROR_CODES = frozenset({"not_configured", "cancelled", "expired", "not_gmail", "not_allowed", "inactive", "rate_limited", "failed"})


class GoogleAuthError(Exception):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code if code in ERROR_CODES else "failed"


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    sub: str
    email: str
    email_verified: bool
    name: str | None = None


def normalize_email(value: str) -> str:
    """Normalize an address for comparison.

    Gmail ignores dots, ``+tag`` suffixes and letter case, and
    ``googlemail.com`` is the same mailbox; other domains are only
    lower-cased.  Keep in sync with migration 0037.
    """
    value = str(value or "").strip().lower()
    local, _, domain = value.partition("@")
    if domain in {"gmail.com", "googlemail.com"}:
        local = local.split("+", 1)[0].replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}" if local and domain else ""


def is_gmail(value: str) -> bool:
    return normalize_email(value).endswith("@gmail.com")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign(settings: Settings, payload: bytes) -> str:
    return _b64(hmac.new(service_signing_key(settings, "google-oauth-flow:v1"), payload, hashlib.sha256).digest())


def start_flow(settings: Settings, portal: str) -> tuple[str, str]:
    """Return Google's consent URL and the signed flow cookie value."""
    if not settings.google_login_ready:
        raise GoogleAuthError("not_configured")
    portal = portal if portal in PORTALS else "admin"
    verifier = _b64(secrets.token_bytes(48))
    flow = {
        "state": _b64(secrets.token_bytes(24)),
        "verifier": verifier,
        "nonce": _b64(secrets.token_bytes(24)),
        "portal": portal,
        "exp": int(time.time()) + FLOW_TTL_SECONDS,
    }
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": flow["state"],
        "nonce": flow["nonce"],
        "code_challenge": _b64(hashlib.sha256(verifier.encode("ascii")).digest()),
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    payload = json.dumps(flow, separators=(",", ":")).encode("utf-8")
    return f"{AUTH_URL}?{urlencode(params)}", f"{_b64(payload)}.{_sign(settings, payload)}"


def read_flow(settings: Settings, cookie: str | None) -> dict[str, object]:
    """Verify the flow cookie; raise ``expired`` when it is missing or stale."""
    try:
        encoded, signature = str(cookie or "").split(".", 1)
        payload = _unb64(encoded)
        if not hmac.compare_digest(signature, _sign(settings, payload)):
            raise ValueError("signature")
        flow = json.loads(payload)
        if not isinstance(flow, dict) or int(flow.get("exp", 0)) < int(time.time()):
            raise ValueError("expired")
    except (ValueError, TypeError, json.JSONDecodeError):
        raise GoogleAuthError("expired", "missing or expired Google sign-in flow") from None
    return flow


def flow_portal(flow: dict[str, object] | None) -> str:
    portal = str((flow or {}).get("portal") or "admin")
    return portal if portal in PORTALS else "admin"


def _claims(id_token: str) -> dict[str, object]:
    parts = id_token.split(".")
    if len(parts) != 3:
        raise GoogleAuthError("failed", "malformed id_token")
    try:
        claims = json.loads(_unb64(parts[1]))
    except (ValueError, json.JSONDecodeError):
        raise GoogleAuthError("failed", "malformed id_token") from None
    if not isinstance(claims, dict):
        raise GoogleAuthError("failed", "malformed id_token")
    return claims


def identity_from_claims(settings: Settings, claims: dict[str, object], nonce: str) -> GoogleIdentity:
    now = int(time.time())
    exp = claims.get("exp")
    if (
        str(claims.get("iss")) not in ISSUERS
        or claims.get("aud") != settings.google_client_id
        or not isinstance(exp, (int, float))
        or exp < now - CLOCK_SKEW_SECONDS
        or not hmac.compare_digest(str(claims.get("nonce") or ""), nonce)
        or not isinstance(claims.get("sub"), str)
        or not isinstance(claims.get("email"), str)
    ):
        raise GoogleAuthError("failed", "invalid id_token claims")
    verified = claims.get("email_verified") in (True, "true")
    name = claims.get("name")
    return GoogleIdentity(
        sub=str(claims["sub"])[:255],
        email=str(claims["email"]).strip().lower(),
        email_verified=verified,
        name=name if isinstance(name, str) else None,
    )


async def finish_flow(
    settings: Settings,
    *,
    code: str | None,
    state: str | None,
    error: str | None,
    flow: dict[str, object],
    transport: httpx.AsyncBaseTransport | None = None,
) -> GoogleIdentity:
    if not settings.google_login_ready:
        raise GoogleAuthError("not_configured")
    if error:
        raise GoogleAuthError("cancelled", "Google returned an error")
    if not code or not state or not hmac.compare_digest(str(state), str(flow.get("state") or "")):
        raise GoogleAuthError("expired", "OAuth state mismatch")
    if not re.fullmatch(r"[\x21-\x7e]{1,2048}", code):
        raise GoogleAuthError("failed", "malformed authorization code")
    secret = settings.google_client_secret
    if secret is None:
        raise GoogleAuthError("not_configured")
    client_secret = secret.get_secret_value() if hasattr(secret, "get_secret_value") else str(secret)
    async with httpx.AsyncClient(timeout=httpx.Timeout(15), transport=transport, follow_redirects=False) as client:
        try:
            response = await client.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": client_secret,
                    "redirect_uri": settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                    "code_verifier": str(flow.get("verifier") or ""),
                },
            )
        except httpx.HTTPError as exc:
            raise GoogleAuthError("failed", f"token exchange failed: {type(exc).__name__}") from None
    try:
        body = response.json()
    except ValueError:
        body = {}
    id_token = body.get("id_token") if isinstance(body, dict) else None
    if response.status_code != 200 or not isinstance(id_token, str):
        raise GoogleAuthError("failed", f"token exchange failed: HTTP {response.status_code}")
    return identity_from_claims(settings, _claims(id_token), str(flow.get("nonce") or ""))
