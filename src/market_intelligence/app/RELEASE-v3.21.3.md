# Bee Researcher v3.21.3

## Performance and reliability

- Compress text responses (including the self-contained admin shell) with
  gzip when the client supports it. This reduces refresh/download time without
  changing the UI or the API contract.
- Keep each workspace's daily collection and analysis budget on its configured
  IANA timezone, with a safe UTC fallback for malformed legacy values.

## Verification

- Full unittest suite: 299 tests passed.
- Python compilation and `git diff --check` passed.
