# Bee Researcher v3.19.1

## UX Writing lookup hardening

- Added normalized alias matching for the Google Sheet UX Writing catalog.
- Zero-width characters, Persian half-spaces, repeated whitespace and Unicode
  ellipsis variants now resolve to the same reviewed translation key.
- Legacy bilingual fallback remains available for catalog entries that are
  intentionally English-only or not yet reviewed.

## Verification

- Full market-intelligence test suite: ۲۷۸ tests passed.
- `/health`: healthy.
