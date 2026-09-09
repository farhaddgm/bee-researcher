# Bee Researcher Admin — v3.29.10

## Navigation consistency patch

- Prevented the legacy Support-nav injector from re-adding a duplicate primary-sidebar entry after route changes.
- Support remains a single dedicated destination in the sidebar account menu, with a semantic life-buoy icon.
- All account-menu icons and labels remain synchronized across locale changes.

## Verification

- Python syntax and `git diff --check` pass.
- Full service tests pass before deployment.
- Deployed health, public health, migration head, and published HTML checks pass.
