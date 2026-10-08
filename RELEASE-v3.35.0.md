# Bee Researcher 3.35.0 — trustworthy diagnostics and scoped recovery

- Legacy fallback recovery now reuses the workspace pipeline with optional
  business, current evidence/thresholds, bounded budget and no publication.
- Complete translations and published analyses/previews are not rewritten by
  fallback regeneration or automatic report retries.
- Same-article in-flight analysis reservations are deduplicated. Provider
  cooldowns do not consume nonexistent API attempts.
- Metrics use workspace model, timezone and limits; request caches include
  workspace and authenticated account identity.
- Overview and Operations show dated actual AI observations, actionable safe
  quota/auth/model blockers, pending articles and owner-only request budgets.
- News List includes a read-only decision inbox: pending/selected/review/rejected,
  source/title search, numbered pages, reason and quotes, keyboard/focus support.
  The latest-500 matching-article window is explicitly disclosed.
- Source checks use only the current fetch response and explicitly label lexical
  diagnostics, not AI relevance; cross-language absence is not an AI rejection.
- Weekly report inserts include assistant identity. Schema migration 0040 scopes
  period uniqueness to workspace, preserves rows and refuses destructive rollback.
  Trends use current AI evidence; duplicate generation returns the real record ID.
- New UI strings reviewed in all eight supported locales, with original article
  content excluded from UX translation. Separate scoped JS/CSS avoids new inline
  event/style attributes, polling or AI calls on page load.
- README/runbook removes stale lexical-publication and destructive shared-server
  recovery guidance. Added unit, real SQL and browser product regressions.

Provider account funding and a successful real semantic benchmark remain
external prerequisites; no accuracy improvement percentage is claimed from mocks.
Existing models, destinations, sources and schedules are not altered by release.
