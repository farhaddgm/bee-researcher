# Bee Researcher v2.7.0

## Workspace-scoped API reads and ingestion

- `GET /sources`, `GET /publications`, ingestion and pipeline execution accept `assistant_id`.
- Source and publication queries apply the workspace predicate at the database query boundary.
- Pipeline ingestion forwards the selected workspace without changing legacy default behavior.
- This closes the first API enforcement slice of MI-027; downstream analysis/cache/report filters remain in the next slice.
