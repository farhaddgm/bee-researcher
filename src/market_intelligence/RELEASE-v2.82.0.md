# Bee CFO / Bee Researcher v2.82.0

## Release scope

- Bee CFO now prefers the owner-approved structured TGJU endpoint for
  `IR_GOLD / GOLD_18K`, while retaining the existing profile as fallback.
- Implausibly low quotes are rejected before storage or Telegram delivery.
- News-site navigation and copyright boilerplate are removed from the media
  outlook section, and the Telegram renderer keeps the report within its
  delivery-size contract.

## Isolation

- The migration changes only Bee CFO indicator-source data and does not alter
  Bee Researcher tables, ingestion contracts, or shared runtime state.

## Verification

- Price safety and media extraction regression tests are included.
- The service image, database migration, health endpoint, and Telegram pilot
  delivery are checked before handoff.
