# Bee Researcher Market Intelligence — v3.10.4

Security hardening patch released 2026-08-25.

## Changes

- Client-side error telemetry now sends only a fixed event class (`window` or
  `promise`); exception text is never placed in an unauthenticated health URL
  or proxy access log.
- The public researcher edge now rejects request bodies larger than 2 MB before
  they reach the application, reducing resource-exhaustion exposure while
  retaining the existing application-level limits.
- The production image remains digest-pinned and the release is promoted as a
  distinct immutable image tag.

## Verification

- Full Market Intelligence unit suite passed.
- Compose configuration and Caddy configuration validated.
- HTTPS endpoint and dependency health checked after deployment.
