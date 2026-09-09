# Bee Researcher v2.18.0

## Workspace-scoped backoffice mutations

- Source and topic updates now verify membership in the resource's assistant workspace before applying a change.
- Admin users retain global administration; assistant admins and editors can mutate only resources in assigned workspaces.
- Audit entries now include the affected `assistant_id` for source/topic changes.
- No secrets or channel credentials are returned by these operations.

## Verification

- 33 regression tests pass.
- The running service reports `health=healthy` with PostgreSQL and Redis healthy.
