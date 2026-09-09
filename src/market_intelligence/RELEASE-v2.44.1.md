# Bee Researcher v2.44.1

Hardens legacy pipeline invocation: a missing workspace scope now resolves to
the stable default workspace before settings, locks, ingestion, clustering,
analysis, and publishing run. This prevents nullable `assistant_id` values
from reaching workspace-owned operational records such as event clusters.
