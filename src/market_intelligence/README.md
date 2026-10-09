# Bee Researcher — 3.40.0

A private, multi-workspace news collection, evidence-based AI relevance and
publication service. The administration portal is `/admin`; authorized readers
use `/user`. `market-intelligence` is the legacy deployment service name, NOT
permission to modify other Bee applications.

## Product flow

1. Create an assistant workspace with its mission. A business is optional.
2. Add readable public sources; select each source's report output language.
3. Add enabled topics, definitions, positive/excluded terms and thresholds.
4. Owner configures collection/analysis slots in Settings. Publication slots
   belong to Channels. These schedules are independent.
5. Collection stores source items; extraction retains original article evidence.
6. AI evaluates every active topic with score, confidence and verifiable quotes.
7. Current topic threshold plus any explicit project floor decides selected,
   borderline, rejected or pending. Lexical matches and user feedback NEVER
   authorize publication on their own.
8. Selected or eligible borderline articles receive a complete localized report.
9. Scheduled delivery requires current evidence, full valid report language,
   active workspace/source, authorized destination and publication limits.
   Manual borderline approval is bounded and tied to the exact current score,
   content and threshold. No report/provider failure silently publishes fallback.

Changing a threshold does not require a paid re-score. Changing topic meaning,
model, business or article content invalidates incompatible cached evidence.
Pending articles are retained and retryable; they are not confirmed irrelevant.

## Approved business research context

An optional Contenter link remains read-only and never activates AI on its own.
Project writers can select approved sections/facts, consent to AI processing,
preview recent news and explicitly save a shadow or live policy in Business.
Topic relevance and business relevance are separate, evidence-backed scores:
topics-only, contextual (no business-score cutoff), or focused (both gates).
Shadow preserves the existing live policy. Facts are private in public reports
by default, output languages/schedules are unchanged, and access withdrawal or
expired facts cannot silently fall back to another business. A complete preview
is required for live activation; provider failure does not fabricate a score.

Design, operator steps and boundaries: `docs/RESEARCH-CONTEXT-fa.md`.
Measured test evidence: `docs/RESEARCH-CONTEXT-VERIFICATION-fa.md`.

## Operator diagnostics

- Overview/Operations distinguish process liveness from observed AI health.
  API configuration is not proof that the account has credits or model access.
- Quota, authentication and model errors are safe actionable codes, with a dated
  observation and owner-only request budgets. Read-only diagnostics do not call AI.
- News List's expandable collected-news list shows all four AI decision states,
  title/source search, numbered pages and quote/rationale details. Its disclosed
  window is the most recent 500 search matches within the freshness window.
- Source Check verifies connection, extraction and keyword matches only. It does
  not calculate AI relevance or claim cross-language matches are irrelevant.
- Recovery endpoints reuse the scoped pipeline: current AI gates, optional
  business, per-workspace budgets and immutable published content. Complete
  translations survive provider outages and fallback regeneration.

## Runtime boundaries

- Python 3.13, FastAPI, PostgreSQL schema `market_intelligence`, private Redis
  database/namespace. Current Alembic revision: `0045_news_chat`.
- Never restore the shared database, restart the entire compose project, or edit
  Consultant/other services to publish Researcher. Only the Researcher service
  may be recreated. The reports migration changes one unique constraint and
  retains every report; no article, user or source is deleted.
- Secrets remain server environment/secret-manager values. Do not paste keys,
  cookies or account data into reports, commits or tickets.
- OpenAI API funding is separate from Codex usage. A quota error is an external
  account blocker, not evidence of successful AI operation.
- Official Google Search is used only with configured API key and engine ID.
  Otherwise discovery uses actual provider web-search evidence, never guessed
  URLs. No implementation can promise exhaustive coverage of the entire web.
- Existing configured models are preserved; releases do not silently substitute
  a cheaper model, raise budgets or change schedules.

## Private news conversations (opt-in)

Authorized readers can study one published report with OpenAI, Claude or Gemini
models approved by the owner. Chat has its own account grant, project/model
allowlist, daily budgets, concurrency cap and private history. It never invokes
collection, analysis, publication or a Contenter business. Brand changes start a
new conversation; existing history is not passed to the new brand.

The server feature flag defaults to **off**. Provider keys remain secure server
settings. Owner must verify model access, token prices and data terms, register
the API ID/prices and enable project access in Account. API configuration is not
proof that a real provider call succeeds. Citations validate report segment IDs,
not the semantic truth of an AI answer; model accuracy still needs an explicitly
budgeted live evaluation. Full original-source retrieval is not part of this UI.

Implementation, safe activation, acceptance results and remaining limits:
`docs/NEWS-CHAT-IMPLEMENTATION-fa.md` (repository root). Isolated gate:
`python3 ops/scoped-release/verify_news_chat.py --image <candidate-image>`.

## Verification

Run in an isolated `test` database (`assistant_test`) with real AI and Telegram
credentials disabled. Never point regression fixtures at production.

```bash
python -m unittest discover -s tests -v
ruff check --config ruff.toml app
mypy app --ignore-missing-imports
python scripts/check_csp_inline_budget.py
python scripts/check_i18n_catalog.py
alembic upgrade head
python scripts/verify_media_pipeline.py
python scripts/verify_product_reliability.py
python scripts/verify_ingestion_regressions.py
python scripts/verify_report_translations.py
python scripts/verify_media_discovery_sql.py
python scripts/verify_contenter_sql.py
python scripts/verify_research_context_sql.py
npm ci --ignore-scripts --no-audit --no-fund
node scripts/verify_product_diagnostics.mjs
npm run admin:media:e2e
npm run admin:models:e2e
npm run admin:locales
npm run admin:support:e2e
npm run admin:research-context:e2e
npm run user:e2e
```

Browser scripts require isolated `BEE_ADMIN_URL`/`BEE_USER_URL` and test account
environment variables. Semantic accuracy needs the separate opt-in,
budget-reserved live benchmark `scripts/verify_live_relevance.py`; mocks do not
prove model quality or account access. Dry run makes zero provider calls.

## Release and recovery

Build an immutable image from the reviewed commit. Record source/image identity,
actual tests/scans, a fresh schema-scoped backup, signed manifest and deployment
receipt. Deploy only `market-intelligence` with `--no-deps --no-build --pull never`.
Check `/health`, `/ready`, authenticated diagnostics and both public Bee domains.

Prefer a forward fix. Do NOT run automatic Alembic downgrade or restore shared
PostgreSQL to roll back an application image. The previous image does not know
revision 0040; a reviewed rollback override must retain the forward-compatible
schema and start its Uvicorn process directly (without its Alembic startup step).
Weekly reporting remains fixed only in 3.35.0 and later. No schema downgrade may
remove duplicate per-workspace reports to satisfy an older global constraint.

Design and prioritized steps: `docs/product-reliability-3.35.0-fa.md`.
Earlier media/relevance rationale: `docs/media-discovery-relevance-3.34.0-fa.md`.
