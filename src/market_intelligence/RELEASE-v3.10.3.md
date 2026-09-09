# Bee Researcher / Market Intelligence v3.10.3

## Security hardening

- Enforced secure admin cookies whenever the service runs in production; the
  Compose fallback now defaults to `true` instead of silently weakening the
  session boundary.
- Production startup rejects the documented bootstrap-password placeholder,
  preventing an unrotated first-login secret from reaching a live service.
- Added a bounded Redis-backed login-failure counter (10 failures per
  username/client identity in 15 minutes). It stores only a one-way digest,
  fails open if Redis is unavailable, and clears after a successful login.
- Extended the same-origin mutation guard from only `/admin/api/*` to every
  state-changing control-plane route. Requests without an `Origin` remain
  compatible with server-to-server scheduler and Telegram callbacks.
- Changed the admin session cookie to `SameSite=Strict` and clear all browser
  site data on logout.
- Added `X-Permitted-Cross-Domain-Policies`, `X-DNS-Prefetch-Control` and
  `Origin-Agent-Cluster` response/proxy headers.
- Replaced internal exception text in pipeline and reanalysis 500 responses
  with stable public messages; full diagnostics remain server-side in logs.

## Verification

- Full container unittest suite: run with
  `python -m unittest discover -s tests -p 'test_*.py'`.
- Production checks: secure cookie, authenticated `/meta`, HTTPS headers,
  cross-origin mutation rejection, and health endpoint.
