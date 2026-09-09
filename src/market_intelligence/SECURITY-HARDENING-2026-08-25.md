# Bee CFO / Market Intelligence — Security Hardening

Date: 2026-08-25  
Scope: `app/market_intelligence`, its back-office, compose service, and the Bee CFO API boundary. Bee Researcher/Consultant data and code were not changed.

## Implemented

- Production admin sessions require `Secure`, `HttpOnly`, `SameSite=Strict` cookies. The six-hour idle ceiling remains enforced.
- Added a rotating, HMAC-signed, session-bound double-submit CSRF token for cookie-authenticated mutations. A dedicated `MARKET_INTELLIGENCE_CSRF_SIGNING_SECRET` is supported; the existing back-office automatically sends `X-CSRF-Token`.
- Added bounded login-failure throttling using independent one-way Redis counters for username/client and client IP. Credentials never enter a key, and Redis failure now fails closed with `503` rather than allowing unbounded guesses.
- Password changes now revoke every session for that account, including the current session.
- The HTTP feedback mutation is authenticated; Telegram polling continues to process feedback internally.
- Same-origin validation no longer blindly trusts forwarded host/protocol headers from arbitrary clients. Configured public domains and private reverse-proxy addresses are used.
- Added Trusted Host validation, application-level request-size rejection, no-store cache policy for private responses, and recursive redaction of credentials from HTTP exception details and operational errors.
- Admin CSP now uses per-response nonces for scripts/styles; `unsafe-inline` is limited to legacy attribute handlers while the inline UI migration remains isolated and tracked.
- Template previews are sanitized to a small Telegram-style tag allow-list before being inserted into the back-office DOM.
- Bee CFO discovery reuses bounded redirect and DNS validation and rejects oversized homepage responses. This closes the public-URL-to-private-redirect path.
- Market Intelligence receives a dedicated `MARKET_INTELLIGENCE_OPENAI_API_KEY`; it no longer receives the shared Bee Researcher `OPENAI_API_KEY`.
- The service container runs as UID/GID `10002`, drops all Linux capabilities, uses `no-new-privileges`, `read_only`, `tmpfs /tmp`, `init`, and exposes port 8010 only on loopback.
- The Python base image is digest-pinned and the previously ranged Alembic/TZData dependencies are pinned to the reviewed resolved versions. FastAPI/Starlette are pinned to the security-reviewed `0.141.1/1.6.0` pair.

## Verification

- `docker compose --profile market-intelligence config --quiet`: passed.
- `git diff --check`: passed.
- Python compile check: passed.
- Full Market Intelligence test suite: **255 tests passed**.
- `pip-audit`: **no known vulnerabilities found** in the installed Python environment.
- Running container: **healthy**; PostgreSQL and Redis dependencies healthy.
- Runtime hardening verified: UID/GID `10002:10002`, read-only root filesystem, `CAP_DROP=ALL`, `no-new-privileges`, loopback-only port binding.

## Remaining owner/operations actions

1. Put a strong, unique value in `MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD`, log in once, change it, and remove/blank the bootstrap value from the deployment secret store.
2. If external model analysis is intentionally enabled, put its credential only in `MARKET_INTELLIGENCE_OPENAI_API_KEY` and set `MARKET_INTELLIGENCE_EXTERNAL_ANALYSIS_APPROVED=true` after review. Do not copy the Bee Researcher key.
3. Keep `.env` and monitoring secret files mode `600`; rotate Telegram/OpenAI/database credentials if they were ever exposed outside the secret store.
4. Set `MARKET_INTELLIGENCE_CSRF_SIGNING_SECRET` to a unique random service secret. Until it is set, the compatible derived fallback is used; setting it invalidates old CSRF tokens after the next login/session renewal.
5. Add image signing/SBOM and a base-OS CVE scan to CI. `pip-audit` is now run locally and clean, but the final deployment artifact should also be promoted by digest and scanned with the organization’s approved image scanner.

## Deliberate follow-up

The back-office is currently a single inline HTML/JavaScript document. Its CSP uses per-response nonces for the script/style blocks, while legacy `onclick` and `style` attributes still require the narrowly scoped `script-src-attr`/`style-src-attr` compatibility directives. The preview sink is sanitized and reviewed dynamic values use escaping. The remaining hardening item is to migrate those attributes to delegated listeners/classes and then remove both attribute directives entirely.
