# Bee Researcher v3.21.8

## Support workspace reliability and UX

- Kept the owner's personal queue independent from the full inbox page limit,
  so older owner-created tickets are not hidden by a busy support queue.
- Added localized inline validation for short ticket descriptions and an
  explicit hint when more than one page of tickets is available.
- Made request-load errors visible in both the personal and owner queues, with
  a single retry action for a clean recovery path.
- Kept the support workspace localized across all eight supported languages,
  with lifecycle and priority filters, summaries, and owner reply controls.

## Verification

- Python compilation and `git diff --check` pass.
- Full application test suite passes in the release container (300 tests).
- Production health endpoint reports healthy PostgreSQL and Redis dependencies.
