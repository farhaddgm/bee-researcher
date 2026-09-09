# Release v2.50.15

## New-project catch-up pipeline

- Derived article, relevance, analysis and publication rows now retain their source workspace instead of falling back to the legacy default project.
- Existing misassigned derived rows are repaired by migration `0012_pipeline_workspace_ownership`.
- New projects queue one forced first run after activation/testing; that run uses the configured freshness window before normal schedule slots continue.
