# Bee Researcher v3.29.31

## Reliability and audit hardening

- Added the unauthenticated `/ready` probe. It reports PostgreSQL/Redis plus
  scheduler heartbeat and Telegram poller readiness without making a Telegram
  network call on every probe; `/health` remains a cheap liveness check.
- Removed the 15-second identity polling loop and scoped the final UI
  normalizer to the app root to prevent background repaint/freeze cycles.
- Disabled legacy Support compatibility bootstraps from first paint; the
  threaded Support controller is now the single DOM owner.
- Renamed runtime defaults to Bee Researcher and made the Compose build
  context relative so clean clones and CI builds are reproducible.
- Added an opt-in Playwright inventory harness and static-analysis CI job
  (Ruff, Bandit, Mypy). Browser credentials remain repository secrets and the
  inventory never clicks destructive actions.
- Fixed unittest discovery so the security test module seeds its test-only
  settings before importing the application.
- Made language changes atomic across all eight supported locales; the UI no
  longer renders a Persian intermediate shell before committing the selected
  language and direction.
- Added compact, redacted JSON scheduler/pipeline events for operational
  observability while keeping high-frequency health access logs disabled.
- Switched the market-intelligence container healthcheck to `/ready`, so a
  live process whose scheduler or Telegram poller is unavailable is no longer
  reported as healthy to Compose.
- Added an authenticated Playwright locale smoke that iterates every language
  option and fails on incorrect `lang`/direction metadata or Persian copy
  leaking into non-Persian navigation labels.

## Verification

- Python compilation, 332 unit/contract tests, Compose contract, i18n catalog
  and CSP budget checks are required release gates.
- `/ready` is used by the Compose healthcheck, load balancers and deployment
  monitors; use `/health` only for a cheap process/dependency liveness probe.

## Operational note

An assistant can still be legitimately *not ready* when its owner has not
configured Telegram destinations or enabled collection. The readiness API
surfaces that state; it does not invent channel identifiers or mutate the
owner's workspace.
