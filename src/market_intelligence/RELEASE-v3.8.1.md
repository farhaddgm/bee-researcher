# Bee CFO v3.8.1

This release completes the approved Phase 1 shadow-execution ledger.

- A persisted report can be recorded through a dedicated no-send shadow run.
- Each run stores a stable output hash, its prior-report hash, an auditable
  read-only diff, evidence-pack verification, and the explicit no-send reason.
- Repeating the same stored output reuses the original audit record rather
  than creating an ambiguous duplicate.
- The API exposes create and read endpoints for the shadow-run ledger; neither
  endpoint collects sources, invokes a model, changes a scheduler, or contacts
  Telegram.

The migration adds only the `shadow_run` category to Bee CFO's existing
governance-event constraint. Bee Researcher and Consultant tables, routes,
sources, schedules, and Telegram destinations remain untouched.

Verification: 92 Bee CFO unit/release-gate tests pass in the project runtime.
