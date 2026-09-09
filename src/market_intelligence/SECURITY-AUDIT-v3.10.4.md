# Security audit — v3.10.4

Date: 2026-08-25

This patch closes two residual low-risk leakage/resource controls identified in
the v3.10.3 review. The implementation was checked against the control themes
in OWASP ASVS and the OWASP API Security Top 10: authenticated state changes
remain CSRF/origin protected, project scope is enforced server-side, and the
edge now has a bounded request body.

## Closed in this release

- **Diagnostic data leakage:** browser telemetry is reduced to fixed labels;
  raw JavaScript exception text is not sent to `/health`.
- **Unbounded edge body:** Caddy limits requests to the researcher service to
  2 MB; route-specific Pydantic limits remain authoritative inside the app.
- **Supply-chain drift:** the Docker base is pinned by digest and the image is
  promoted under immutable release tag `3.10.4`.

## Controls retained from v3.10.3

- Secure, HttpOnly, SameSite=Strict six-hour idle sessions.
- Double-submit CSRF and strict same-origin checks for mutations.
- Redis-backed bounded login throttling.
- SSRF/DNS/redirect/response-size controls for public source fetching.
- Non-root, capability-free, read-only application container.
- HSTS, clickjacking, MIME-sniffing, referrer, permissions, and no-index
  response headers.

## Follow-up requiring an explicit owner decision

- MFA/WebAuthn enrollment and recovery UX must be designed and enrolled before
  it can be made mandatory; silently enabling it would risk locking out the
  owner.
- Removing `unsafe-inline` from CSP requires the legacy inline admin shell to
  be split into nonce/hash-backed static assets and event handlers.
- CI should promote signed, SBOM-attested images and run dependency CVE scans.
