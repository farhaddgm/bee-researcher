# Bee Researcher v3.19.0

## Spreadsheet-backed UX Writing

- Added a generated snapshot of the UX Writing Google Sheet with ۳۵۵
  canonical text entries and all eight locale columns.
- The admin UI resolves visible labels, placeholders, titles, accessibility
  labels, navigation text and toast copy through the sheet-specific
  translation before using the legacy English fallback.
- Existing manual Persian/English copy remains the fallback for rows not yet
  present in the sheet; user-generated names and article content are never
  translated.
- The snapshot is refreshed from the sheet when the catalog is regenerated,
  keeping the Google Sheet as the reviewed source of truth.

## Verification

- Full market-intelligence test suite: ۲۷۸ tests passed.
- /health: healthy.
