"""Typed portal boundaries, independent of session lifetime and account role."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Portal:
    path: str
    session: str
    csrf: str
    nightly: bool


PORTAL_REGISTRY = {
    "admin": Portal(
        "/admin", "research_bee_admin_session", "research_bee_admin_csrf", False
    ),
    "user": Portal(
        "/user", "research_bee_user_session", "research_bee_user_csrf", True
    ),
    "report": Portal(
        "/report", "research_bee_report_session", "research_bee_report_csrf", True
    ),
}


def portal_spec(name: str) -> Portal:
    if name not in PORTAL_REGISTRY:
        raise ValueError("unknown portal")
    return PORTAL_REGISTRY[name]
