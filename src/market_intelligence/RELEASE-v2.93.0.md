# Bee CFO / Bee Researcher v2.93.0

## Price-unit correction

- Fixed the Bee CFO direct-price defect where unitless TGJU API values were
  stored as toman even though the owner-approved source contract is rial.
- Added explicit source-unit contracts for the active TGJU and Navasan price
  sources, with conflict rejection when a page and catalog disagree.
- Repaired legacy TGJU API snapshots created without a unit conversion and
  preserved their original raw quote for auditability.
- Added a pre-delivery price-jump safety gate that holds a quote instead of
  publishing a likely 10x/0.1x unit error.
- The follow-up patch release `v2.93.1` rebuilds denormalized price deltas
  after this repair, so the current card cannot retain the legacy `-90%`
  comparison.
- Bumped the standalone Telegram price-card renderer revision to
  `bee-cfo-price-2`.

## Scope and isolation

- Only the Bee CFO market-intelligence service and its isolated schema/data
  were changed. Bee Researcher and Bee Consultant runtime code was not
  modified.
- No corrective Telegram message is sent automatically by this release; on
  owner request, the existing price message `31` was edited in place and kept
  auditable in the delivery ledger.

## Verification

- Full Bee CFO test suite must pass before image promotion.
- Database migration `0027_bee_cfo_price_unit_contract` must be at the head.
- Production health and price-source probe must pass before enabling delivery.
