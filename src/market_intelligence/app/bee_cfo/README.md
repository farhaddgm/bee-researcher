# Bee CFO phase one: Market Analyst

Bee CFO is a separate product boundary inside the independent Market
Intelligence runtime. Phase one is public-market analysis only. It does not
read holdings, goals, risk tolerance, or any other personal-finance data and
does not issue personalized buy/sell/allocation instructions.

## Delivered contract

- A profile controls timezone, weekday/time slots, selected markets, source
  policy, and the fixed output sections.
- User-provided sources are recorded with URL, origin, authority, freshness,
  access status, and provenance. Discovered sources are always stored as
  `draft` suggestions and require explicit activation.
- Same-domain feed discovery is bounded, public-only, robots-aware through the
  shared adapter, and never promotes a candidate automatically.
- Active watches collect public articles through the existing fetch/extraction
  boundary, then create an immutable snapshot and a structured report with
  current state, three probability-bearing scenarios, horizons, triggers,
  invalidation conditions, changes, uncertainties, and citations. For
  registered news sources, the report also preserves each source's explicit
  forward-looking market view, stance, horizon, publication time, and URL;
  it never infers a media opinion from a price number or page title.
- A failed or unapproved model call falls back to a deterministic, low-
  confidence report. External model egress still requires the existing
  `MARKET_INTELLIGENCE_EXTERNAL_ANALYSIS_APPROVED` gate.
- Forecasts are persisted and can be evaluated after their horizon. State
  changes generate deduplicated, explainable alerts.
- Each report now stores factor attributions with direction, strength,
  evidence snippets, source keys, horizon and invalidation. These are
  explainable associations; the service does not claim causal contribution or
  fabricate a numeric effect for a source.
- When at least 30 valid price observations exist, the report adds 1/7/30-day
  point forecasts, 80% ranges, up/down/flat probabilities, data cutoff,
  sample size and model components. With insufficient history it emits an
  explicit `no_call` instead of a made-up number.
- Numeric forecasts have a separate evaluation endpoint. Realized values are
  recorded for MAE, MAPE, directional accuracy, interval coverage and Brier
  score, so future model changes can be judged by walk-forward evidence.
- Benchmark capabilities are now isolated in Bee CFO: evidence cards with
  exact snippets, novelty and duplicate metrics, descriptive Media Pulse,
  configurable alert-rule storage/evaluation, compact scheduled-digest
  output, bilingual indicator aliases, model agreement flags, a coverage
  score, a deduplicated event ledger, and a delayed media scorecard. A
  scorecard stays `insufficient_sample` until 20 evaluated observations;
  missing external calendar or benchmark feeds are shown as incomplete and
  are never silently filled.

## API surface (no back-office UI)

All endpoints are private and workspace-scoped under `/bee-cfo`:

- `GET/PUT /profile`
- `PUT /configuration` (secret-free Sheet-to-workspace sync; drafts by default)
- `GET /readiness`
- `GET/POST /sources`
- `POST /sources/{id}/status`
- `POST /sources/discover`
- `GET/POST /watches`
- `POST /reports/run`, `GET /reports`, `POST /reports/{id}/deliver`
- `POST /forecasts/{id}/evaluate`
- `POST /price-forecasts/{id}/evaluate`
- `GET /synonyms`
- `GET/PUT /alerts/rules`
- `GET /events`
- `GET /coverage`
- `POST /media-forecasts/evaluate`
- `GET /media-scorecards`
- `GET /infrastructure-audit`

The migration seeds a draft workspace with slug `bee-cfo` and UUID
`00000000-0000-0000-0000-000000000002`. It has no sources, watches, schedule,
or delivery destination until the owner configures and activates them.

## Telegram delivery

Scheduled Bee CFO reports use the shared Telegram HTTP transport but their own
renderer and `bee_cfo_deliveries` ledger. The ledger makes delivery idempotent
per report and destination, records Telegram message IDs, and never writes a
bot token to Bee CFO data or the Google Sheet. The destination is configured in
the workspace Telegram settings; the token remains deployment-managed through
`MARKET_INTELLIGENCE_TELEGRAM_BOT_TOKEN`. A private chat must start the bot;
for a channel, the bot must be allowed to post. The compact renderer keeps
media views in a separate `نظر رسانه‌ها درباره روند آتی` section and does not
add an inferred “news impact” section.

## Reuse and separation

The `SharedResearcherAdapter` reuses only public URL validation, bounded fetch,
robots/retry handling, article extraction, and provenance. Bee CFO owns all
`bee_cfo_*` tables, report/forecast contracts, scheduling branch, and alerts.
There is no import or runtime dependency on `app.consultant_bee`, `research_*`
tables, or the legacy research queue. The audit records this decision and the
package can be extracted into a separate service later.

## Benchmark release boundary

The benchmark layer is a Bee CFO-owned module and migration (`0023`). It does
not alter Researcher tables, queues, prompts, or delivery behavior. External
economic-calendar and relative-benchmark values have a contract and explicit
missing-data state, but require an owner-approved direct source before they
become publishable.
