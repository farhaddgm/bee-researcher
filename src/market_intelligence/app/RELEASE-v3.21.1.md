# Bee Researcher v3.21.1

## Collection controls hardening and operations visibility

- Kept the Owner-only collection and analysis settings introduced in v3.21.0.
- Redacted collection cadence and limits from non-owner runtime-settings and
  scheduler-status responses; collection writes remain rejected with `403`.
- Added collection state, weekly slot count, per-run cap, and daily budget to
  the Owner Operations view for faster runtime verification.
- No publication behavior or publication limits changed.

