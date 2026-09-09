# Bee CFO v2.99.0

## Scope

This release closes the technical implementation pass for the complete Phase-1
proposal set while keeping the approved Telegram price and media-outlook cards
immutable.

## Delivered

- Forecasting now records a conservative baseline, trend/regime and optional
  local statistical component, with per-component availability and a hard
  no-call for macro-factor inputs that have no aligned, source-grounded data.
- Coverage disclosures now identify actionable gaps in independent-source,
  Persian/English, official and news coverage. These are coverage limitations,
  never market-direction assertions.
- Open checks reuse the recorded coverage gaps so follow-up work is traceable
  and idempotent.
- New material is only eligible for existing append-only follow-up cards;
  the approved price, media title and horizon cards are unchanged.

## Safety

- No Bee Researcher schema, queue, configuration or catalog was modified.
- No macro price target is emitted from missing external data.
- External calendar and relative-benchmark feeds remain disabled until the
  product owner supplies an approved direct source.
