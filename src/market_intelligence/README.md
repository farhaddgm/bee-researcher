# Dotin Market Intelligence

Bee CFO v3.5.1 adds the approved post-phase-one governance layer: measurable
shadow-pilot runs, direct-source decisions, attention budgets, staged USD/BTC
packs, a private typed `/why <report-uuid>` explanation, and a design-only
phase-two privacy boundary. These controls are append-only and fail closed;
they do not enable scheduling, markets, sources, personal-data processing, or
personalized advice. The latest source-decision gate also requires an approved,
passed and unexpired owner record before any live price can be published; an
active catalog source alone is not sufficient.

Bee CFO phase one is implemented as an independently removable bounded
context in [`app/bee_cfo/README.md`](app/bee_cfo/README.md). It adds public
market analysis, source provenance, scenarios, change alerts, and forecast
evaluation without enabling the back-office UI or personalized advice.

The v2.97.0 operational layer stores one auditable row per article-level forecast
statement. It preserves different horizons and same-outlet conflicts, groups
the Telegram outlook by horizon, downweights syndicated narratives, keeps a
source/analyst/horizon evaluation ledger, and exposes owner-editable weighting
scenarios through the Bee CFO API. Horizon-specific expiry and no-look-ahead
guards keep stale/future statements out of consensus; weighting changes and
resets are recorded in a separate audit table. Existing Researcher tables,
routes, and runtime namespaces remain outside this bounded context.

Independent Market Intelligence service through roadmap phases `MI-004` to
`MI-011`, version `2.97.0`.

v2.97.0 also adds the approved Telegram output contract: a standalone price
card followed only by one name-only media-direction card per active horizon;
the default historical media lookback is seven days while price comparison
remains twenty-four hours. It also retains the benchmark-informed operational
controls: decomposed
confidence budgets, actionable coverage gaps, alert maturity, source failover
health, horizon/source/analyst scorecards, point-in-time replay, source-aware
report diffs, bounded capacity budgets, and Telegram ordering/idempotency UAT.
All are persisted in report snapshots or derived from existing Bee CFO ledgers;
no new Researcher table or queue is required.

## Isolation contract

- Docker service and image: `market-intelligence` / `ai-market-intelligence:3.5.1`

v2.98.0 preserves those approved price and media cards exactly, then appends
bounded evidence-first cards for factors, model estimates/scenarios, data
quality, and follow-up items only when their individual publication gates pass.
- PostgreSQL schema: `market_intelligence`
- Alembic version table: `market_intelligence.alembic_version`
- Redis database: `2`
- Redis namespace: `market-intelligence:*`
- Environment prefix: `MARKET_INTELLIGENCE_`
- Runtime port: `8010` on the private Compose network; host binding is limited
  to localhost and public access is served only through the TLS domain.

The physical PostgreSQL and Redis services are reused. No Python module, table,
queue key, token, release number, or mutable runtime state is shared with the
legacy `research_*` implementation in `assistant-api`.

## Product defaults

- Business: داتین
- Topics: financial services, banking services, Central Bank of Iran, and
  Iranian financial-policy regulations
- Timezone: `Europe/Berlin` by default; each assistant may override it from the back-office settings.
- Daily schedule: `07:00`, `12:00`, `21:00`
- Maximum selected items per run: `5`
- Pilot mode: enabled
- Automatic Telegram publishing: disabled

## Pipeline

1. Fetch approved public feeds/listing pages with bounded retries, conditional
   requests, source health tracking, global fingerprint deduplication, public-URL
   validation, and `robots.txt` awareness.
2. Select a balanced candidate set across sources and fetch full public article
   pages with byte/time/concurrency limits.
3. Extract canonical URL, title, author, publication date, language, raw HTML,
   normalized text, quality, status, and provenance.
4. Score every active topic with explainable lexical evidence and optional
   embeddings, reject generic non-financial matches, and cluster similar events.
5. Produce a structured Persian business analysis. If the dedicated model key is
   absent or a cost cap is reached, use a zero-cost deterministic fallback.
6. Create auditable, formal HTML Telegram previews with no media preview, no
   informal emoji, and a 2,000-character maximum. Publish only when all pilot,
   configuration, permission, and explicit publish gates are open.
7. Collect and analyse enabled media once per local hour with Redis locking and
   idempotency. Publish only at the project's selected Tehran schedule slots;
   the per-slot delivery cap is independent from the daily processing budget.
   Missed-slot recovery, weekly trend reports, feedback capture, metrics, and
   retention policies remain enabled.

## External-data safety gates

`MARKET_INTELLIGENCE_EXTERNAL_ANALYSIS_APPROVED` is a hard application gate.
Leave it `false` until the owner explicitly approves sending normalized article
text and the Dotin business profile to OpenAI. The deployment may reuse the
project's existing API key, but the client refuses egress without this flag.
Responses requests use strict JSON Schema and `store: false`.

Telegram also requires a dedicated bot. Never put either secret in source control
or Google Sheets. Configure only these deployment secrets after approval:

```dotenv
MARKET_INTELLIGENCE_EXTERNAL_ANALYSIS_APPROVED=false
MARKET_INTELLIGENCE_TELEGRAM_BOT_TOKEN=
MARKET_INTELLIGENCE_TELEGRAM_CHANNEL_ID=-1000000000000
```

For Telegram, create the private channel, add the dedicated bot as an administrator
with post/edit/delete permissions, obtain the numeric `-100...` channel ID, and
keep `MARKET_INTELLIGENCE_PILOT_MODE=true` plus
`MARKET_INTELLIGENCE_AUTO_PUBLISH=false` during UAT.

## Test, deploy, and verify

```bash
docker compose --profile market-intelligence build market-intelligence
docker compose --profile market-intelligence run --rm --no-deps \
  market-intelligence python -m unittest discover -s tests -v
docker compose --profile market-intelligence up -d market-intelligence
docker compose --profile market-intelligence ps
```

The service runs its independent Alembic chain before startup. The production
head for v1.0.0 is `0003_full_pipeline`.

Private-network operations endpoints:

- `GET /health`, `/meta`, `/metrics`, `/sources`, `/scheduler/status`
- `POST /ingestion/run`, `/pipeline/run`, `/relevance/rescore`
- `POST /analysis/reanalyze-fallbacks?limit=5` (requires the explicit external
  analysis gate and reanalyzes selected preview rows in place)
- `GET /publications`, `POST /publications/refresh-previews`,
  `POST /publications/{id}/publish`
- `GET /telegram/readiness`, `POST /feedback`
- `POST /weekly-reports/run`, `/retention/run`

Manual safe pilot run:

```bash
docker compose --profile market-intelligence exec -T market-intelligence \
  python -m app.pipeline_cli --idempotency-key manual-pilot-001
```

`--publish` cannot bypass pilot mode, disabled auto-publish, missing credentials,
or missing Telegram administrator permissions.

## Retention and backup

Raw HTML is cleared after 30 days and normalized articles after 365 days by
default. Retention is destructive; inspect eligible counts before invoking it
manually. The scheduler collects and analyses enabled media once per local hour;
publication is attempted only at the selected project schedule slots.

Create a PostgreSQL custom-format dump before and after deployment, validate with
`pg_restore --list`, and perform restore drills only in an isolated temporary
PostgreSQL instance.

## Rollback

1. Disable scheduling/publishing and stop only `market-intelligence`.
2. Preserve logs and create a current custom-format database dump.
3. Restore the previous image or Git revision.
4. If database rollback is required, downgrade from `0003_full_pipeline` to
   `0002_source_registry`; this removes only MI-004 through MI-010 tables and
   restores service metadata to `0.3.0 / mi-003`.
5. Verify the core `assistant-api`, both existing Telegram bots, task worker,
   PostgreSQL, Redis, and Qdrant remain healthy.

v2.99.0 completes the Phase-1 proposal traceability pass: the forecasting
engine now exposes its available conservative components and explicit no-call
for unproven macro inputs, while coverage gaps disclose language, authority,
and source-independence limitations without making market claims.

v2.99.1 is a safety hotfix for public media-outlook cards: directional calls
now require an asset-specific local context, generic “price” matches are not
accepted, and legacy stored calls are revalidated before Telegram delivery.

v2.99.2 tightens market relevance for public follow-up events: the canonical
article title is the final ingestion gate and a follow-up event must name the
selected market before it can reach Telegram.

v2.99.3 separates a controlled, explicitly requested manual pilot from
automatic scheduled publication. The readiness API now exposes both gates;
the former never turns the scheduler on, while the latter still requires an
active profile and owner-configured time slots.
