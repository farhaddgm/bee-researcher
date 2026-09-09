# Bee CFO / Bee Researcher v2.92.0

## Approved ideas delivered

- Added a benchmark playbook mapping source-grounded research, alerts,
  factorized news analytics, historical replay, and market-intelligence
  workflows to isolated Bee CFO controls.
- Added decomposed confidence budgets, explicit coverage gaps, and a bounded
  capacity budget to every new report snapshot.
- Added price-source health with primary/failover visibility while preserving
  owner-approved source ordering and the existing quote safety boundary.
- Added alert maturity states: `candidate`, `corroborated`, and `suppressed`.
  A candidate is not treated as a corroborated public alert.
- Added horizon/source/analyst media scorecards with minimum-sample gating and
  visible owner priors.
- Added report diff, point-in-time replay with no look-ahead, open checks, and
  Telegram UAT endpoints.
- Kept all new logic in `app/bee_cfo` and reused Researcher only through its
  existing read-only adapter boundary.

## API additions

- `GET /bee-cfo/benchmarks`
- `GET /bee-cfo/reports/replay?cutoff=...`
- `GET /bee-cfo/reports/{report_id}/diff`
- `GET /bee-cfo/reports/{report_id}/telegram-uat`
- `GET /bee-cfo/checks`
- `GET /bee-cfo/capacity`

## Verification

- `194` service tests pass inside the rebuilt image.
- Golden fixture, architecture/isolation audit, offline Telegram UAT, parser
  safety, media horizon/conflict tests, and new operations tests pass.
- No live Telegram message was sent by this release validation run. A real
  channel UAT remains an explicit owner-controlled check because it is an
  external side effect.
- Image: `ai-market-intelligence:2.92.0`.
