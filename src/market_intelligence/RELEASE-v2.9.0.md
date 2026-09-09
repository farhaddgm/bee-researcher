# Bee Researcher v2.9.0

## Workspace-scoped pipeline stages

- Extraction, relevance scoring, clustering and analysis now accept and enforce `assistant_id`.
- Topics, sources, articles, clusters, profiles and analyses are filtered at each stage.
- Pipeline forwards the workspace scope through all four stages.
- Publication rendering remains the final scope-hardening slice.
