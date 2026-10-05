# Bee Researcher 3.33.2 — complete report translations

## Root causes and changes

- Original English titles unconditionally replaced the translated headline.
  Keep native-language titles canonical, but use the faithful translated title
  for foreign-language reports; original source evidence remains unchanged.
- Deterministic fallback summaries copied English excerpts next to Persian
  analysis/template headings. Incomplete translations now render a localized
  pending state and cannot be delivered, including through manual overrides.
- Explicit all-fields language instructions and a conservative prose gate
  cover headlines, summaries, business context, opportunities, risks, actions,
  facts, inferences, time horizons and topic-score explanations. Proper names,
  acronyms, model identifiers and URLs are preserved, not blindly translated.
- Per-source/report language is distinct from the user's backoffice language.
  Persist language provenance in citations; localize template headings and the
  time-horizon vocabulary in the eight supported report languages.
- Remove fictitious banking/customer claims from new deterministic fallbacks.
- A later budget/provider failure cannot overwrite an already translated
  fallback with the source excerpt. Successful retry refreshes existing
  previews, not only the analysis record.
- Explicit repair tool for existing previews: workspace scoped, dry-run by
  default, no source/configuration/relevance/status changes, no Telegram send
  or edit, optimistic concurrency protection, idempotent, bounded batches of
  three with exact IDs/evidence-list validation and existing model budgets.

## Verification

Unit tests cover mixed-language rejection, proper-name preservation, the full
field contract, template locale, incomplete provider responses, missing
evidence and batch identities. Real isolated PostgreSQL tests verify the
repair, exact token accounting, unchanged source evidence/scores/status,
other-workspace isolation, published-message immutability, retries and
idempotency. No schema migration is required.

The script quality gate detects script/prose leakage; it does not certify
human-level fluency or factual equivalence of every possible translation.
Budget exhaustion shows a pending translation, never invented translated
news. Completed translation alone never upgrades fallback analysis to a
successful analysis or bypasses relevance/publication gates.
