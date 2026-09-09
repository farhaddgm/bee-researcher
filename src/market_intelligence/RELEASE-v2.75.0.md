# Bee Researcher v2.75.0

## Roadmap delivery

- MI-123: dynamic account/settings navigation now uses the selected language on first render, so an English refresh does not briefly show Persian labels.
- MI-124: the standalone «امنیت / Security» sidebar button was removed. User and session controls remain inside «حساب کاربری / Account».
- MI-125: security audit hardening was applied to the back-office and operational endpoints.

## Security changes

- `/meta` is authenticated and no longer exposes deployment metadata publicly.
- Manual ingestion, rescoring, fallback regeneration, preview refresh, publication, weekly report and retention mutations require authenticated owner/workspace scope.
- Same-origin Origin validation protects cookie-authenticated `/admin/api` mutations.
- Security response headers include CSP, frame denial, no-store for admin pages, restrictive permissions and cross-origin isolation headers.
- HSTS is emitted when the request is served through HTTPS (including an HTTPS reverse proxy).

## Verification

- Python compilation and `git diff --check` pass.
- Targeted back-office/security tests pass in the release image.
- Container health: `healthy` (Postgres and Redis healthy).
