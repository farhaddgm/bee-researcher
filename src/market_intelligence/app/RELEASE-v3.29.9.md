# Bee Researcher Admin — v3.29.9

## UI consistency patch

- Added a semantic life-buoy icon to the Support entry in the sidebar account menu.
- Added matching user, security, and sign-out icons and preserved locale-aware labels.
- Fixed Support menu routing so selecting it opens the dedicated Support view.
- Kept Support out of the primary navigation according to MI-172; no footer/widget copy is introduced.

## Verification

- Python syntax and `git diff --check` pass.
- Full service test suite passes before deployment.
- Health and migration checks are performed on the deployed image.
