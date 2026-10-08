# Bee Researcher 3.33.1 — log-driven ingestion fixes

## Verified production findings (2026-10-05)

- App loggers inherited WARNING with no handler. Scheduler INFO and authenticated
  browser diagnostics were not visible even though Uvicorn startup logs worked.
  Configure only the `app` namespace, with bounded JSON and content-free exception
  frames; HTTP clients remain quiet. Redact secrets in fields, URL credentials and
  API keys. Source outcomes now log only IDs, status, counts and probe flags.
  Browser CSP reporting excludes policies/nonces, URL queries/fragments,
  userinfo, private paths and source samples; legacy and modern report formats
  are supported. Limit public CSP log entries to 60/minute per process.
- Zoomit's HTTP 200 RSS used `Content-Encoding: br`, but HTTPX had no Brotli
  decoder. Install pinned Brotli 1.2.0 and test actual compressed feed parsing.
- Health probes could advance ETag/Last-Modified without storing articles and
  delay subsequent ingestion. Probes now fetch full content and never update
  ingestion cache validators or its cooldown. Real ingestion still caches.
- Source-key-only Redis locks collided across independent workspaces. Lock on
  source UUID instead. Production has eight shared source keys.
- Global source-item uniqueness discarded common news across assistants.
  Migration 0039 scopes uniqueness to `(assistant_id, fingerprint)` and updates
  inserts. Within-workspace duplicates and retention tombstones stay protected.
  Reset operational feed-cache validators once to recover previously skipped
  content; administrator configuration and existing articles are unchanged.
- Response byte limits were checked after loading the entire body. Enforce
  bounds during streamed, decoded reads, including discovery and robots reads.
  Oversized failures retain status and attempt counts; DNS errors use retries.
- HTML returned from an RSS endpoint is reported as a wrong feed rather than
  falsely presenting a publisher HTML DOCTYPE as an unsafe XML feed.

## External issues, not application regressions

Seven-day history included Redis disk-full errors; at inspection there was 70 GB
free and all Redis persistence checks were OK. Do not disable Redis safeguards.
Publisher HTTP 403/404, DNS/timeouts and robots denials are not bypassed. Fars's
configured RSS currently returns HTML. Do not silently replace saved source URLs
or change user settings. Missing private destination credentials likewise require
valid administrator configuration, not guessed tokens or channels.

## Verification and deployment

Run full unit/static/security checks, mandatory browser E2E, existing pipeline
PostgreSQL integration and `scripts/verify_ingestion_regressions.py` against the
isolated test PostgreSQL/Redis. No production test news or channel messages.
Verify the real Zoomit feed with the candidate image without storing its content.

Back up only `market_intelligence` before migration. No source, topic, workspace,
channel or model configuration is rewritten. Only Researcher's service changes.

Migration 0039 never deletes/rewrites rows. Rolling back to 3.33.0 also requires
the explicit 0039 downgrade before starting old code: its legacy INSERT depends
on global uniqueness. Downgrade deliberately refuses if cross-assistant copies
have since been ingested. In that case keep the migration and roll forward; do
not delete articles, restore the shared database or blindly start the old image.

References: HTTPX binary-response documentation explains Brotli requires its
optional decoder: https://www.python-httpx.org/quickstart/#binary-response-content
Pinned package: https://pypi.org/project/brotli/1.2.0/
