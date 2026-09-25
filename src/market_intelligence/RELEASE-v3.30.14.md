# Bee Researcher v3.30.14

## Reliability, security and operational visibility

- Assistant readiness now evaluates the effective inherited Telegram channels
  used by delivery, avoiding false `not ready` reports for the legacy assistant.
- Owner operations now surface a per-assistant collection-freshness incident
  when enabled sources have no successful pipeline run in 36 hours. The alert
  is independent of process `/ready`, is translated in all eight admin
  locales, and uses aggregated queries rather than per-assistant query loops.
- Explicit incident refreshes bypass both concurrent-GET coalescing and the
  short-lived admin read cache, so the Refresh action cannot return stale
  incident data.
- Authenticated client-error telemetry is bounded per session, stores only a
  one-way session key, rejects noisy bursts, and continues to omit exception
  text and user content.
- Strict CSP is the default. Compatibility exceptions remain only as an
  explicit rollback; the CI migration budget is clearly separated from
  enforced policy exceptions.
- Support ticket dialogs now keep keyboard focus contained and restore focus
  after close/refresh. Required local browser coverage exercises creation,
  owner response, immutable ticket text, closed-ticket controls, role grants,
  workspace scope and all eight alert translations.
- CI browser checks now boot an isolated local service and fail when required
  authenticated checks cannot run. Python type analysis, dependency auditing,
  image scanning, signing and SBOM-attestation verification are promotion
  gates.
- Market Intelligence image builds embed the source revision. Promotion trace
  artifacts bind the signed image digest to its commit, and an operator-side
  verifier checks the actual running container before declaring it promoted.
- Reader-session tests cover the nightly cutoff across daylight-saving
  transitions and confirm that a future idle deadline cannot extend a session
  beyond the 02:00 service cutoff.
- Analysis-window and quote parsers now validate scalar numeric inputs before
  conversion, ignore malformed non-scalar quote values, and retain Decimal
  compatibility instead of raising at runtime.
- Report renderers, benchmark scoring, alert rules, assistant media drafts,
  persisted knowledge and workspace access checks now validate dynamic JSON
  values before iterating, converting or indexing them. Malformed optional
  values degrade safely; malformed workspace membership fails closed.
- The full application now has zero Mypy diagnostics. CI runs Mypy as a hard
  failure gate and retains the baseline comparison as an additional summary.

## Verification status

Verified locally in isolated Python 3.13, PostgreSQL/Redis, and Playwright
containers. E2E ran against an image built from the clean PR worktree and used
the exact Playwright 1.55.1 version pinned in the package lock. Database and
Redis data lived only in disposable containers on an internal Docker network:

- 363 Python unit tests passed; Python compilation and offline Alembic SQL
  rendering passed. A clean PostgreSQL database applied every migration through
  `0036`, and the app's `/health` endpoint became healthy.
- CSP budget passed (`onclick=52/132`, `style=53/54`); the translation
  catalog passed with 960 static keys and 7,681 locale entries.
- All eight Admin locales passed 11 page-heading checks each and all 16
  operational alert/severity combinations.
- Admin inventory captured 15 page states; interaction smoke passed 8
  scenarios. Support E2E passed ticket creation, owner reply, immutable body,
  closure, focus handling, explicit portal grants and workspace isolation.
- User E2E passed saved notification preferences/delivery and verified text
  direction remains scoped to article content; no uncaught browser errors.
- Ruff passed for application/tests, Bandit passed at the CI severity threshold,
  dependency audit found no known vulnerabilities, and `git diff --check`
  passed. Mypy reports zero diagnostics; comparison with the local development
  baseline on `main` resolved 506 diagnostics with none introduced.
- The candidate was tested locally but has not yet been published as an
  immutable registry image or deployed. GH Actions remains responsible for the
  full image scan, signing, SBOM attestations, and promotion after merge to
  `main`.

This note records local verification only. A signed registry image, immutable
digest, and production deployment are separate release artifacts and must not
be inferred from these local tests.
