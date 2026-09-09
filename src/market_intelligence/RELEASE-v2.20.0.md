# Bee Researcher v2.20.0

## Back-office lifecycle and scheduling

- Hardened project deletion and return a clear dependency error instead of a generic server error.
- Added administrator password rotation directly beside each user in the team directory.
- Added explicit media/topic display ordering with move-up and move-down controls.
- Added a seven-day by 24-hour schedule grid; selected cells are the actual scheduler slots.
- Added per-assistant Telegram channel cards showing feedback/view destinations and purpose.
- Added an immediate one-news publication action, separate from scheduled pipeline preview runs.
- Clarified the normal pipeline action so it prepares a preview without forcing an immediate publish.
- Added Persian numeral localization for visible back-office values and refreshed navigation icons/action spacing.

## Verification

- Database migration `0009_backoffice_ordering` applied.
- Automated test suite passes.
- Health and UI smoke checks pass after deployment.
