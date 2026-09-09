# Bee Researcher v3.21.6

## Settings access hardening

- The collection and analysis settings card remains Owner-only in both the
  navigation and direct view routing; lower roles cannot open or read it.
- The Channels page contains only publication scheduling, Telegram readiness,
  and destination-channel configuration.

## Verification

- Python compilation and `git diff --check` passed.
- Full unittest suite is run as part of the release deployment.
