# Release v2.50.12

## Authorization-scoped project loading

- Project and business cards remain in a loading state until the authenticated account's `/admin/api/assistants` response is received.
- Failed or stale project-list requests cannot render cached or unscoped cards from a previous account.
- Project-scoped business panels use the same authorization gate.
