# Bee Researcher — v3.29.26

## Assistants layout stability

- Fixed translated/draft assistant cards whose final action row could extend beyond the card boundary.
- Assistant cards now grow to fit their localized content while preserving a stable minimum height.
- Action rows stay pinned to a shared baseline across cards and locales, with the primary action remaining last.

## Verification

- `python3 -m compileall -q app/market_intelligence/app`
- `python -m unittest discover -s /app/tests -p 'test_*.py'` — 329 tests passed in the container.
- Browser smoke check across English, Turkish, Persian and German confirmed no card overflow.
