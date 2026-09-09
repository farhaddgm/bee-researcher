# Bee Researcher v2.83.0

## Release scope

- Removed the Quality and trends card from News list as requested.
- Added a consistent manual approval and publish action for every publication
  that was not approved automatically, including the news detail drawer.
- Reworked the shared header into a direction-aware flex layout so its title,
  project selector, search and actions do not overlap in Persian or English.
- Pinned toast placement to the language direction: bottom-right in English
  and bottom-left in Persian.

## Verification

- Python compilation and `git diff --check` pass.
- Admin contract tests cover the removed panel, manual-review action and header
  cascade.
- Deployment health and the existing two environment-dependent test failures
  are documented at handoff.
