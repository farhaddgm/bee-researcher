# Bee Researcher v3.21.7

## Support workspace reliability

- Replaced the layered support-page renderers with one request-safe controller;
  stale responses, duplicate renders and duplicate submissions are ignored.
- Added server-side search, status/priority filters, bounded pagination and
  status/priority summaries while preserving owner-only full-inbox access.
- Tightened ticket validation so whitespace-only descriptions and empty owner
  updates are rejected, and non-custom categories receive a human-readable
  subject instead of a technical category key.
- Owner updates now return the complete ticket identity and workspace context;
  requester notifications retain a structured event key.
- Added a responsive, localized support workspace with clear lifecycle badges,
  priority controls, retry/error states, character count and owner reply tools.
- Kept the owner's personal queue independent from the full-inbox page limit,
  so older owner-created tickets are not hidden by a busy support queue.
- Added localized inline validation for short ticket descriptions and an
  explicit overflow hint when more than one page of tickets is available.

## Verification

- Python compilation and `git diff --check` pass.
- Full application test suite passes in the release container.
- Production health endpoint reports healthy PostgreSQL and Redis dependencies.
