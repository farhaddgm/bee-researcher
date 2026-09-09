# Bee Researcher security audit — v3.10.3

This review uses OWASP ASVS 5.0 and the OWASP API Security Top 10 (2023) as
the application-security baseline. It covers the FastAPI control plane,
browser session flow, project-scoped authorization, ingestion boundaries,
container deployment and the Caddy edge.

## Implemented controls

| Area | Control |
| --- | --- |
| Authentication | Scrypt password hashes, random opaque sessions stored as SHA-256 digests, six-hour sliding idle ceiling, immediate invalidation for disabled accounts, secure/HttpOnly/SameSite=Strict cookie. |
| Brute force | Redis-backed 10-attempt/15-minute counter keyed by a one-way username/client digest; successful login clears it and Redis failure does not take authentication down. |
| CSRF | Same-origin validation for all state-changing requests that carry an Origin header, including operational and publication routes, while preserving server-to-server callbacks without Origin. |
| Authorization | Project/workspace scope checks and role checks are enforced server-side; UI visibility is not treated as authorization. |
| Data exposure | `/meta` and admin responses are non-cacheable; secrets are excluded from configuration clones and public readiness payloads. |
| SSRF/ingestion | Global-host validation, DNS re-resolution, redirect limits, robots policy, byte/item caps and secret-bearing URL query rejection. |
| Browser/edge | HTTPS-only public domain, HSTS, CSP, frame denial, MIME sniffing protection, no-referrer, Permissions-Policy, COOP/CORP, noindex and additional cross-domain hardening headers. |
| Runtime | Pinned images, non-root app user, read-only filesystem, `no-new-privileges`, private backend network, localhost-only app port, resource/pid limits and health checks. |
| Error handling | Public 500 responses no longer include exception class or internal message; details are logged server-side. |

## Required operational controls

- Keep `.env` outside source control and rotate bootstrap, database, Redis,
  OpenAI and Telegram secrets through the server secret mechanism.
- Keep the app reachable only through the TLS reverse proxy; do not publish
  port 8010 on a public interface.
- Review audit logs and failed-login counters, test PostgreSQL restore, and
  rebuild pinned images regularly for security updates.
- Treat any future third-party connector as a new trust boundary: use
  least-privilege credentials, webhook signature verification, replay
  protection and a dedicated threat-model/release gate.

## Residual risk

The admin HTML is currently an inline legacy shell, so the CSP retains
`unsafe-inline` for compatibility. Removing it requires extracting the inline
script/style into nonce- or hash-protected assets; it is a planned hardening
step rather than a safe hot change.

