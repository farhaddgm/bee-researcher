# Bee CFO v3.9.0

This release completes the approved, implementation-ready Phase 1 roadmap
controls without activating a market, source, scheduler, or Telegram delivery.

- Provider contracts can now retain a secret-free, offline response-shape
  fixture. A drift from a registered fixture is quarantined before price
  delivery and recorded in Bee CFO's isolated audit ledger.
- Every newly generated report carries an evidence-quality gate covering the
  hash-verified evidence pack, citable evidence, coverage sufficiency, media
  links, and explicit no-call reasons. Delivery is held when that gate fails.
- Point-in-time replay now returns a deterministic replay manifest with source
  content hashes, the captured evidence manifest, cutoff, output contract and
  a replay hash. It contains no raw response bodies or secrets.
- Capacity is evaluated before a model call. An excessive source/evidence
  budget is stopped in a controlled way and recorded without a model, delivery,
  or scheduler action.

Migration `0032_bee_cfo_provider_capacity_controls` expands only Bee CFO's
governance-event category constraint. Bee Researcher and Consultant tables,
queues, destinations, configuration, and runtime behavior are not changed.

Verification: 97 Bee CFO unit/release-gate tests pass in the project runtime.
