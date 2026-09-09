# Release v2.59.6

## Refresh and branding stability

- Added an early session-check gate so the login form and authenticated shell
  remain hidden until `/admin/api/me` resolves. Hard refreshes no longer show a
  login-form flash while an existing session is restored.
- Hid the legacy `R / Bee Researcher` login markup before first paint and use the
  preloaded Bee Researcher asset as the first-frame brand. The old logo is not
  rendered during logo replacement.
- Added regression coverage for the session gate and first-paint branding.

## Verification

- 118 automated tests passed.
- `GET /health` reports `healthy` with PostgreSQL and Redis healthy.
