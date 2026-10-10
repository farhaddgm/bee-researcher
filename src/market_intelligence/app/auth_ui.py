"""One auth UI and account controller for both portals; no delayed overlays."""
from pathlib import Path
import re

ROOT = Path(__file__).parent


def decorate_auth_html(html: str, *, admin: bool) -> str:
    # Retire the two-language, timer-driven Google/login/allowlist layers.
    html = re.sub(r'<script id="google-(?:login|access)-layer">[\s\S]*?</script>', '', html)
    css = (ROOT / "account_access.css").read_text(encoding="utf-8")
    js = (ROOT / "auth_portal.js").read_text(encoding="utf-8")
    if admin:
        js += (ROOT / "admin_accounts.js").read_text(encoding="utf-8")
        css += (ROOT / "login_history.css").read_text(encoding="utf-8")
        js += (ROOT / "login_history.js").read_text(encoding="utf-8")
    return html.replace('</head>', '<style id="account-access-styles">' + css + '</style></head>', 1).replace(
        '</body>', '<script id="account-access-controller">' + js + '</script></body>', 1)
