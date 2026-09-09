# Bee Researcher v3.21.2

## Reliability and operations

- Apply each workspace's configured IANA timezone to the daily collection and
  analysis budget. A project's daily quota now rolls over at its local
  calendar midnight instead of the server's UTC midnight.
- Validate configured timezone names safely and fall back to UTC when old or
  malformed workspace data is encountered; no request or scheduled run is
  blocked by an invalid persisted value.
- Keep publication caps independent from collection/analysis caps: the
  pipeline can inspect a larger candidate set while delivery remains bounded
  by the configured publication limit.

## Verification

- Full unittest suite: 296 tests passed.
- Python compilation and `git diff --check` passed.
