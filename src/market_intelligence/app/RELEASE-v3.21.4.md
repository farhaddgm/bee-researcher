# Bee Researcher v3.21.4

## Refresh resilience

- Always release the locale/session visibility gate when authentication fails,
  times out, or an optional render hook raises. The login form can no longer
  remain hidden behind a white page after refresh.
- Added an independent six-second last-resort release for the locale gate so a
  stalled data request cannot leave the control center blank indefinitely.
- Kept the gzip response optimization and project-local daily quota behavior
  from v3.21.3.

## Verification

- Full unittest suite: 299 tests passed.
- Python compilation and `git diff --check` passed.
