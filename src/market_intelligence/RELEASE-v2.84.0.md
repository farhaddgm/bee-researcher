# Bee CFO / Bee Researcher v2.84.0

## Release scope

- Adds a separate linked media-outlook Telegram message after the live gold
  price card and before the normal market report.
- Directional groups are built only from explicit media opinions; articles
  without a forward view are shown separately rather than inferred.
- Adds auditable media-message IDs to the Bee CFO delivery ledger.

## Isolation

- The new migration changes only the Bee CFO delivery ledger. Existing
  Researcher ingestion and shared fetch infrastructure remain unchanged.

## Verification

- Media grouping, hyperlink rendering, source safety and the full service test
  suite are release gates.
