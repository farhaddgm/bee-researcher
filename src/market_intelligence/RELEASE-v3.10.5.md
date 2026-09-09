# Bee CFO / Market Intelligence — v3.10.5

Security hardening release.

- Upgraded and pinned FastAPI `0.141.1` and Starlette `1.6.0`; Python dependency audit is clean.
- Added HMAC/session-bound CSRF, per-IP login throttling with fail-closed Redis behavior, Trusted Host validation, request-size limits, cache isolation, and error redaction.
- Added nonce-based CSP for the inline back-office shell while keeping Bee Researcher/Consultant boundaries unchanged.
- Verified with 255 tests, `pip-audit`, Compose validation, Caddy validation, and a healthy hardened container runtime.

Owner actions remain: provision the dedicated CFO CSRF signing secret, remove bootstrap credentials after first login, and enforce signed-SBOM/base-image scanning in deployment CI.
