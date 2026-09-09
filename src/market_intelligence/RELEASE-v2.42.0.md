# Bee Researcher v2.42.0

## Weekly 7×24 publishing schedule

- Replaced every textual schedule entry path in the backoffice with a real weekly table containing all 7 days and all 24 hourly buttons.
- Persian view starts with Saturday while preserving the scheduler's canonical Python weekday values; English view starts with Monday.
- Selected cells are stored per assistant, restored on reload, announced accessibly and summarized by selected hours and days.
- Added server-side validation, normalization and de-duplication for the 168 supported whole-hour slots.
- Kept Telegram readiness and project channel details on the same page, below the full-width scheduling surface.
