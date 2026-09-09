# Bee Researcher Market Intelligence v2.27.0

## MI-033/MI-034 — back-office corrective pass

- Project deletion now pauses the workspace and removes workspace-owned rows in dependency order before deleting the workspace. This prevents the server error seen on upgraded databases with incomplete foreign-key cascade actions; the protected default «داتین» workspace remains undeletable.
- Admin user password rotation is presented next to the username in the users table, with the same secure modal and session revocation behavior.
- Existing MI-033/MI-034 UX work remains active: Persian numerals, 7×24 scheduling, channel details, table sorting, stable action spacing, responsive layout, and immediate publish controls.

## Verification

- 43 regression tests pass.
- The image and Compose service are versioned `2.27.0`.
