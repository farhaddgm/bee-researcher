# Security audit — v3.10.5

Date: 2026-08-25

Scope: Bee CFO / Market Intelligence only: application code, its back-office,
its Compose service, and its Caddy boundary. Bee Researcher and Bee Consultant
containers, schemas, queue namespaces, and credentials remain outside this
change.

## Residual-risk review and actions

| Risk | Decision | Action/result |
| --- | --- | --- |
| CSRF token forgery or cross-project reuse | Closed | HMAC-signed token bound to the active session; optional dedicated CFO signing secret; strict Origin/Referer policy and SameSite cookies remain enabled. |
| Credential brute force | Closed | Username/client and client-IP Redis budgets; Redis outage fails closed for authentication. |
| Host-header abuse | Closed | Trusted Host middleware uses configured public hosts plus loopback/test hosts; service port remains loopback-only. |
| Oversized request/resource exhaustion | Closed | Caddy 2MB edge limit plus application `Content-Length` limit and bounded route models. |
| Error/URL/token leakage | Closed | Recursive HTTP exception redaction, operational error redaction, and bounded public-source URL handling. |
| Browser XSS policy | Reduced and tracked | Nonce-based script/style CSP is active. Legacy inline attribute handlers remain the only compatibility exception; no dynamic unescaped HTML sink is intentionally accepted. Full removal is isolated as the next UI-only refactor. |
| Dependency CVEs | Closed for Python dependencies | FastAPI 0.141.1 + Starlette 1.6.0 are pinned; `pip-audit` reports no known vulnerabilities. |
| Image/base OS supply chain | Mitigated, CI action remains | Base image is digest-pinned, container is non-root/capability-free/read-only. SBOM, signature verification, and approved OS scanner must be added to CI/deployment promotion. |
| MFA/WebAuthn | Open owner decision | Not silently enabled because recovery/enrollment UX and owner enrollment are required to avoid lockout. |
| Secret-store isolation | Mitigated, owner action remains | Dedicated CFO OpenAI and CSRF secret variables are supported. Owner must set unique values and rotate any credential that may have been exposed. |

## Verification

- `docker compose --profile market-intelligence config --quiet`: passed.
- `git diff --check`: passed.
- Full suite: **255 tests passed**.
- `pip-audit`: **no known vulnerabilities found**.
- Caddy config validation: passed; public request body limit is 2MB.
- Runtime: healthy; PostgreSQL and Redis healthy; UID/GID `10002:10002`, read-only root, `CAP_DROP=ALL`, `no-new-privileges`, loopback-only `127.0.0.1:8010`.

## Owner actions before treating the release as fully closed

1. Set a unique random `MARKET_INTELLIGENCE_CSRF_SIGNING_SECRET` in the secret store.
2. Remove the bootstrap admin password from runtime configuration after first login and password rotation.
3. Promote the image by digest only after the organization’s signed-SBOM and OS-CVE gates pass.
4. Decide and enroll MFA/WebAuthn for the owner account.
