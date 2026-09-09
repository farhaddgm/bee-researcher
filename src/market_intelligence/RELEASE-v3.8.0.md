# Bee CFO v3.8.0

This release completes the six approved Phase 1 quality gates within the Bee
CFO bounded context:

- immutable, hash-verified evidence packs for every newly generated report;
- article-level media-claim lifecycle tracking with explicit conditions,
  replacement, and withdrawal states;
- independent direct-price reconciliation, with mismatches held before a quote
  snapshot or Telegram send;
- source-contract fingerprints, expiry-aware revalidation and a read-only
  ledger view that makes drift explicit;
- a private Canary preview with evidence, link, length and phase-one safety
  checks, plus a separate manual approval record; and
- a time-ordered Champion–Challenger gate that keeps numerical public targets
  suppressed until the candidate wins and an owner separately approves it.

The new migration extends the Bee CFO governance-event enum/check constraint
for canary and source-revalidation records only. No Bee Researcher or
Consultant tables, queues, configuration, runtime paths, sources, schedules,
or Telegram destinations are changed. Canary enforcement is off by default;
enabling it and approving a preview are explicit owner actions.

Verification: 89 Bee CFO unit/release-gate tests pass in the project runtime.
