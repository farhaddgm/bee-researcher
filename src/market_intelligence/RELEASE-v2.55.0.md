# Bee Researcher v2.55.0

## MI-081 — Simple content-template editing

- Removed version numbers and previous-version history from the owner template editor.
- Removed the rollback UI and rollback API route; a template edit now saves the current selected blocks only.
- Existing stored templates are read safely and reduced to their current blocks/status on the next save.
- The editor keeps the approved drag-and-drop, visibility toggles, safe preview, and owner-only access.

Verification: full service test suite and health check after deployment.
