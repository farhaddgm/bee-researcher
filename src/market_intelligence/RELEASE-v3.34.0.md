# Bee Researcher 3.34.0 — grounded discovery and evidence-based relevance

- Worldwide multilingual search, bounded additional search for publisher diversity,
  Unicode/spelling normalization, exact platform-publisher identities and verified
  outbound references. Up to ten evidenced suggestions; never fabricated filler.
- Confirm the chosen website rather than re-searching its name on approval. Try
  two actual alternate feeds, then the evidenced HTML, within a 30-second bound.
  Transport unavailability is not confused with a publisher not existing.
- AI assessments require complete topic coverage, calibrated scores, confidence,
  explanation and validated verbatim evidence. Article content, selected model,
  mission/business and active topics identify the cache. Thresholds do not bias
  the model or consume new model requests when changed.
- One decision policy drives queue display, live per-topic thresholds, scheduling
  and final locked delivery. Invalid/stale/lexical scores cannot authorize delivery.
  Manual review cannot bypass absent evidence, explicit exclusions or incomplete
  AI analysis. Feedback ranking cannot mutate the authoritative AI score.
- Provider outages retain prior evidence but never validate changed context.
  Review records are not mislabeled as failed delivery jobs.
- Billing exhaustion/authentication/model errors have safe actionable codes;
  depleted API credits are not retried as transient rate limits or presented as
  missing publishers. Eight-locale explanations and explicit public-URL entry
  remain available. Stop additional analysis calls in the affected run.
- Scoped read-only relevance assessments expose pending and rejected source
  articles without generating a paid report or publishing test messages.
- Explanation API also uses the live decision; report prompts do not reuse
  feedback-adjusted scores. Overview recognizes incomplete topic coverage.
- Successful search evidence has a bounded ten-minute, model/provider-scoped
  cache. Identical concurrent searches share evidence; failures are not cached.
  At most two paid searches run concurrently. Terminal account errors open a
  sixty-second circuit, independent of healthy PostgreSQL/Redis status.
- Opt-in semantic benchmark covers seven multilingual, homonym, exclusion and
  injection cases; dry by default, one budgeted request, no news/publications.
- Existing completed report translations, budgets, publication schedules and
  originals are preserved. No database schema migration; schema stays 0039.

Google search is used only with configured official credentials. Otherwise the
existing actual OpenAI web-search tool provides citations. This is not a claim
to exhaustively index the web or a quantified accuracy/human-review guarantee.

Live investigation returned HTTP 429, code `credit_balance_exhausted`, type
`insufficient_quota`. Successful live discovery and rescoring require funding
the connected API account; Codex subscription credits do not fund this API.
