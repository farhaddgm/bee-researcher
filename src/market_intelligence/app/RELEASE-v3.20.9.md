# Bee Researcher v3.20.9

## Reliable login and first-page loading

- Added a bounded 20-second timeout to authenticated back-office requests so a
  stalled upstream cannot keep the locale gate or the application shell stuck.
- Added a five-second timeout to the initial session check, with a recoverable
  sign-in shell when `/admin/api/me` is unavailable.
- Added a four-second shell watchdog so the authenticated UI can show its
  loading/error states even while a slow optional panel is still settling.
- Preserved the existing shorter login and `/me` timeout and credential-error
  handling, including the duplicate-submit guard.

## Verification

- Full automated test suite passes.
- Production health and login failure paths were checked after deployment.
