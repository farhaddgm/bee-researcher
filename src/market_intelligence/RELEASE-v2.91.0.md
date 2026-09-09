# Bee CFO / Bee Researcher v2.91.0

## Bee CFO approved roadmap delivery

- Added an article-level media forecast ledger; one outlet can now contribute
  multiple articles, analysts, horizons, or conflicting statements without
  losing any evidence.
- Added discrete horizon buckets for 24 hours, 48 hours, 3–7 days, 8–30 days,
  over 30 days, and unspecified horizon.
- Added transparent media consensus with source, analyst, article-quality,
  independence, horizon-fit, and recency components.
- Added horizon-specific expiry and a no-look-ahead guard for future-dated
  article statements.
- Added syndicated-narrative downweighting, same-outlet conflict marking,
  media history/transition data, and article-level outcome evaluation.
- Added owner-editable weighting scenarios, reset, immutable weighting audit,
  and scorecard endpoints for media, horizon, and analyst views.
- Updated the Telegram media message to show horizon-separated, hyperlinked
  outlet names and conflict disclosure without truncating HTML anchors.

## Isolation and verification

- Bee CFO remains a bounded, removable context and does not change Researcher
  tables, routes, queues, or runtime namespaces.
- Added migrations `0025_bee_cfo_media_ledger` and
  `0026_bee_cfo_weight_audit`.
- Bee CFO regression and release-gate tests pass; the image is rebuilt as
  `ai-market-intelligence:2.91.0`.
- Live Telegram publishing remains subject to the existing owner credentials,
  destination, pilot, and publication gates.
