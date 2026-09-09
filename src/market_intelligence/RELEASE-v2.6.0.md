# Bee Researcher v2.6.0

## Workspace data-scope foundation

- Added `assistant_id` ownership columns and indexes to all operational tables.
- Added the stable `default` workspace and assigned legacy single-workspace rows to it.
- Database defaults preserve existing pipeline writes while the workspace-scoped API migration proceeds.
- Kept the rollout backward-compatible; cross-workspace pipeline filtering remains the next hardening step.
