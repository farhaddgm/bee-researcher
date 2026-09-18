# Bee Researcher v3.30.0

- Repaired the Media and Topics primary-action lifecycle so one authorized
  workspace is resolved before the modal opens, without retry loops or a
  document-wide capture handler.
- Removed the repeated full-document action reconciliation observer that made
  table refreshes and first paint slower.
- Made the collapsed-sidebar account control use the same account menu as the
  expanded sidebar; avatar upload remains only in Account settings.
- Replaced unauthenticated health-query client telemetry with a bounded,
  authenticated endpoint that excludes exception text and user content.
- Strengthened the authenticated browser smoke workflow: Media and Topics now
  fail the gate if their creation modal does not open.

Verification: 333 automated tests, Python compilation, i18n catalog and CSP
budget checks passed before deployment.
