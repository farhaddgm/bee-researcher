# Bee Researcher v2.17.0

## Sheet media registry reconciliation

- Registered approved Bee Researcher media rows S-006, S-007 and S-008 in the operational source registry.
- S-007 (Donya-ye Eqtesad) uses its public `/feeds/` RSS endpoint.
- S-008 (Startup360) uses its public `/feed/` RSS endpoint.
- S-006 (Asr-e Tarakonesh) is registered but disabled until its public RSS endpoint returns a valid response; no access control is bypassed.
- All three records remain assigned to the default Dotin workspace and use public-only access with robots respected.

## Follow-up patch v2.17.1

- Fixed ingestion audit and source-item writes to always carry the source workspace owner.
- Default ingestion now scopes to the default workspace instead of mixing sources across workspaces.
