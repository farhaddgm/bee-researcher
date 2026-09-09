# Bee Researcher v2.8.0

## Workspace-scoped operations

- Metrics and weekly reports accept `assistant_id` and filter counts, health, publications, analyses, feedback, topics and competitor mentions.
- Pipeline locks are now per workspace, so one assistant cannot suppress another assistant's run.
- Existing requests without `assistant_id` retain the default workspace behavior.
