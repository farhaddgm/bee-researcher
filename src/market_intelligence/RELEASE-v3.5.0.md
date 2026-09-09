# Bee CFO v3.5.0

This release implements the six approved post-phase-one foundation items while
preserving the established Bee CFO report cards and the strict separation from
Bee Researcher and Consultant.

- `PILOT-001`: append-only, 14-day / 30-run shadow-pilot ledger. It measures
  price, links, horizons, conflicts, no-call behavior, length, output safety,
  and duplicate delivery without enabling the scheduler.
- `SRC-001`: per-workspace direct-source decision ledger. A decision records
  ownership, permission basis, URL, unit, timezone, cadence, fallback, expiry,
  and UAT. Recording it cannot activate a source.
- `ALRT-001`: explainable attention budget with severity threshold, quiet
  hours, daily cap, expiry policy, and deduplication. Evaluation records an
  eligible/suppressed audit result but performs no Telegram delivery.
- `MKT-001`: staged USD-free then BTC/USDT market packs, each blocked until an
  approved and passed source-decision record exists. No market is activated by
  the pack endpoint.
- `WHY-001`: an authorised private-chat `/why <report-uuid>` command and API
  endpoint build a bounded response only from a report and its prior stored
  state. It is rate-limited, audited, and does not run a model or new forecast.
- `PRIV-001`: design-only phase-two data boundary. Phase one rejects personal
  data and blocks phase-two processing; its consent, minimisation, tenant,
  retention, export/delete and threat-model controls remain explicit.

Migration `0029_bee_cfo_governance` creates one Bee CFO-only, append-only
governance ledger in the `market_intelligence` schema. No Bee Researcher table,
queue, configuration, token, or runtime path is modified.
