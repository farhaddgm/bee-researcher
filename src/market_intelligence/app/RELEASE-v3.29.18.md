# Bee Researcher — v3.29.18

## Support conversation reliability

- Support ticket cards now use delegated clicks on the stable support view.
  Cards are loaded asynchronously, so Owner and requester ticket dialogs remain
  openable after the inbox refreshes instead of losing their click handlers.
- Retry controls and ticket cards continue to work after locale changes and
  every subsequent refresh; the root listener is installed only once.
- Owner replies continue through the append-only message endpoint, update the
  ticket to `answered`, preserve the legacy reply field for integrations, and
  notify the requester.

## Backup reliability

- PostgreSQL backups now write to a temporary file and atomically promote only
  a non-empty dump. Failed or empty dumps are removed and retried after five
  minutes, preventing a transient database restart from being treated as the
  latest valid backup.

## Verification

- Market Intelligence: 329 tests passed.
- Assistant API: 24 tests passed.
- Telegram bot: 4 tests passed.
- Consultant Bee: 160 tests passed (2 skipped).
- Consultant Telegram bot: 11 tests passed.
- Loan Telegram bot: 6 tests passed.
- Authenticated Owner support reply against production HTTPS endpoint: HTTP 200;
  reply persisted and ticket status updated.
- All compose services healthy; public `/health` reports healthy.
- `scripts/health-gate.sh`: passed with zero restarts/OOMs and a readable,
  non-empty PostgreSQL dump (`daily-20260904-092925.dump`).
- `python3 -m py_compile app/market_intelligence/app/admin_ui.py`: passed.
- `git diff --check`: passed.
