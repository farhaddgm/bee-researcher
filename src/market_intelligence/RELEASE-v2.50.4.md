# Bee Researcher v2.50.4

## Workspace media health probe

- The “Check all health” action now probes every enabled media source in the selected project, including newly-created sources whose initial status is `unknown`.
- The probe bypasses the normal ingestion rate-limit gate for this explicit health check, does not store articles, and never publishes content.
- The endpoint is workspace-scoped and the media table refreshes after the probe so each row shows `healthy` or `degraded` with the latest error/success information.
