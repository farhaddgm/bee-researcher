"""Fail before migration if Google-first production login would lock users out.

Checks configuration shape only, never prints a credential or contacts Google.
The owner's real consent/login is a separate activation acceptance test.
"""
from urllib.parse import urlsplit

from app.config import Settings, get_settings
from app.google_auth import is_gmail


def check_account_deployment(settings: Settings) -> None:
    if settings.environment.strip().lower() != "production":
        return
    if not settings.google_login_ready:
        raise ValueError("Researcher Google OAuth must be configured before enabling Google-first production login")
    if not (settings.google_client_id or "").endswith(".apps.googleusercontent.com"):
        raise ValueError("Researcher Google client ID must be a Web application OAuth client")
    url = urlsplit(settings.google_redirect_uri or "")
    if url.scheme != "https" or not url.hostname or url.path != "/auth/google/callback" or url.query or url.fragment or url.username or url.password:
        raise ValueError("Researcher Google callback must be an HTTPS /auth/google/callback URL")
    if settings.domain:
        expected = urlsplit(settings.domain if "://" in settings.domain else "https://" + settings.domain).hostname
        if expected != url.hostname:
            raise ValueError("Google callback host must match the Researcher canonical domain")
    if not is_gmail(settings.owner_email):
        raise ValueError("Researcher owner must be an explicitly configured Gmail account")


if __name__ == "__main__":
    try:
        check_account_deployment(get_settings())
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    print("Researcher account configuration preflight passed; real Google consent/login still needs acceptance testing.")
