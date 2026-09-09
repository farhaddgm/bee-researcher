# Bee Researcher v2.41.0

## Outcome

Completes the reopened MI-050 backoffice requirements with project-scoped,
visible feedback, Telegram destination, bot identity and dashboard data.

## Changes

- Feedback opens as a first-class 30-day table grouped by Telegram user with
  total, relevant, irrelevant and timeline actions.
- The selected project's Telegram destinations are listed with numeric ID,
  role, message behavior, configuration source and readiness state.
- Bot username and numeric ID use a working edit action; the token remains a
  deployment-managed secret and is never returned to the browser.
- The legacy Dotin workspace displays its effective server-configured channels,
  while new workspaces do not inherit those destinations.
- Overview KPIs use successful analyses and actual Telegram deliveries for the
  current Tehran day, show pending previews, and include a 30-day feedback
  total instead of leaving cards blank.
- Feedback reports now enforce membership of the requested workspace.
- The admin HTML response disables caching so deployed UI corrections are not
  hidden by a stale browser document.

## Verification

- Python compilation
- Full container unit test suite
- Effective Telegram configuration regression tests
- Backoffice structure and no-cache regression tests
- Post-deploy health, metadata and HTML smoke checks
