"""Shared login composition, separately scoped private portal UI."""

from pathlib import Path
import re

from app.auth_ui import decorate_auth_html
from app.user_ui import USER_HTML

ROOT = Path(__file__).parent
login_match = re.search(r'<main id="login"[\s\S]*?</main>', USER_HTML)
style_match = re.search(r"<style>([\s\S]*?)</style>", USER_HTML)
assert login_match is not None and style_match is not None, (
    "shared login composition missing"
)
login = login_match.group(0)
login = re.sub(r'<p class="sr-only">This is a read-only[\s\S]*?</p>', "", login)
shared_styles = style_match.group(1)
body = (
    """<!doctype html><html lang="en" dir="ltr" data-portal="report" data-theme="honey" class="session-checking">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive,nosnippet"><title>Bee Researcher | Private reports</title>
<link rel="icon" href="/favicon.svg"><link rel="preload" as="font" href="/assets/Vazirmatn-Regular.woff2" crossorigin>
<style>"""
    + shared_styles
    + """</style><style>"""
    + (ROOT / "portal.css").read_text()
    + """</style></head>
<body>"""
    + login
    + """<div id="app" class="report-app hidden">
<aside class="report-sidebar"><a href="/report" class="report-brand"><img src="/assets/bee-researcher-grey.svg" alt="Bee Researcher"></a>
<nav id="reportNavigation"></nav><div class="report-account"><span id="reportAccount"></span><button id="reportLogout" class="report-btn" type="button"></button></div></aside>
<main class="report-main"><header class="report-topbar"><h1 id="reportHeading"></h1><select id="reportLanguage" aria-label="Language"></select></header>
<div id="reportMessage" role="status" aria-live="polite" hidden></div>
<div id="reportScope" class="report-scope"></div><section id="reportCompose" class="report-panel"></section>
<section id="reportList" class="report-panel hidden"></section></main></div>
<dialog id="reportDialog" class="report-dialog" aria-labelledby="reportDialogHeading"><div class="report-dialog-head"><h2 id="reportDialogHeading"></h2><button id="reportDialogClose" type="button"></button></div><div id="reportDialogContent"></div></dialog>
</body></html>"""
)
REPORT_HTML = decorate_auth_html(body, admin=False).replace(
    "</body>",
    "<script>"
    + (ROOT / "i18n.js").read_text()
    + "</script><script>"
    + (ROOT / "portal.js").read_text()
    + "</script></body>",
)
