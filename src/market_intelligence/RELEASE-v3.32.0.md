# Bee Researcher v3.32.0 — grounded discovery and preselection AI

- Overview renders actual dependency health. Locale switches no longer restore
  the cached initial “Checking” string or assume a healthy service.
- Media discovery uses real web-search evidence, not model memory. It supports
  multilingual queries, up to three evidenced name alternatives, ten distinct
  suggestions, and refresh excluding saved and previously seen publishers.
- Provider failures are distinguished from no matches. Google is optional for
  existing Custom Search customers; OpenAI web search is the working fallback.
  The UI shows the actual provider and clickable evidence.
- Public publisher references can validate an actual link to an official site.
  RSS/Atom/JSON feed discovery reads real alternate links, never guessed feeds.
  Public-only, robots, redirect and SSRF checks remain enforced.
- AI scores every approved topic before selection. A business profile is
  optional; unrelated projects, financial vocabulary and lexical/embedding
  blending no longer exclude directly relevant cross-language news.
- An admin-managed project threshold is combined with the topic threshold.
  Its help tooltip is keyboard/hover accessible in all eight UI languages.
- Score context hashes invalidate evidence after topic/profile/model/threshold
  changes. Delivery checks fresh, enabled, same-project AI evidence again and
  rejects fallback analyses and stale or below-threshold scores.
- Failed provider calls consume bounded per-project request budgets. Pending
  scores and temporary fallback analyses are retried after provider recovery.
  Collection capacity no longer prevents processing an existing analysis queue.
- Migration 0038 adds nullable AI scores and context hashes. Existing lexical
  scores are not reinterpreted as AI evidence; no records are deleted.
- CI adds mandatory real-PostgreSQL pipeline integration and authenticated
  media/Overview browser regression alongside the existing Admin/User suites.

## Deployment

Apply migration before starting this version. Use only the scanned and signed
main-branch image, pinned to its digest and source commit. Preserve existing
workspace schedules and channel destinations. Never start the candidate compose
stack against production data.

`ops/production-ai.override.yaml` is a scoped production overlay: it forwards a
dedicated Researcher key, or the existing deployment OpenAI key if the dedicated
one is absent, and enables the owner-approved AI capabilities. No credential is
committed. Apply only to `market-intelligence` with `--no-deps --no-build`.
The candidate stack remains deliberately unable to send model/Telegram requests.

Google Custom Search JSON API does not accept new customers and retires for
existing customers on 2027-01-01. This release does not require a new Google
account or claim that every page on the Internet is searched. Search yields
only as many verified public candidates as the evidence supports.

See `docs/media-discovery-relevance-2026-10-04.md` for the product analysis,
verified original faults, acceptance criteria and test evidence.
