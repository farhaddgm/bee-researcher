# Bee Researcher v2.85.0

## News List review flow

- Needs Review items now expose one consistent **Approve & publish** action in the details drawer.
- Publishing requires a second confirmation step before a Telegram delivery is started.
- The old Operation column is removed from the main table; selecting a news title opens its drawer.
- Raw Telegram HTML tags are removed from list and drawer previews while preserving readable content.
- The table shows the source article date separately from the Telegram publication date.
- Persian uses Jalali/localized dates and English uses Gregorian/localized dates.

## Verification

- `test_main.py`: 72 passed; one pre-existing environment assertion fails because `pipeline.pilot_mode` is enabled in the test environment.
- `test_pipeline_components.py`: 25 passed.
