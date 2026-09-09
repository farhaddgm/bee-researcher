# Bee Researcher v3.29.2 — Admin performance and Support workspace

This patch addresses the slow admin bootstrap, removes the unwanted skip-link
copy, and makes Support a single, predictable workspace.

## Delivered

- Metadata, dependency health, and the authorized project list now start in
  parallel; project-scoped requests begin as soon as the authorization
  boundary is known.
- A short-lived, mutation-invalidated read cache collapses duplicate panel
  requests during one paint. Refreshes are single-flight, so repeated clicks
  cannot start competing full-page loads.
- The visible “Skip to content” link, its styling, and its target are removed
  from the admin document.
- Support is rendered by one canonical workspace with equal responsive cards,
  searchable/filterable ticket queues, loading skeletons, explicit empty/error
  states, and an owner-only submitted-ticket queue.

The Support layout follows established enterprise patterns for searchable
forms, clear status feedback, and dense data tables: [Carbon Search](https://carbondesignsystem.com/components/search/usage/),
[Carbon Forms](https://carbondesignsystem.com/components/form/usage/),
[Carbon Notifications](https://carbondesignsystem.com/components/notification/usage/),
and [Carbon Data Table](https://carbondesignsystem.com/components/data-table/usage/).

## Verification

- `python3 -m py_compile app/admin_ui.py` passed.
- Admin UI contract tests cover skip-link removal, parallel bootstrap, cache
  guards, and Support rendering.
- Full market-intelligence test suite passed before deployment.
- Container health smoke test passed after deployment.
