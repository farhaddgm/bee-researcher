# Release v2.64.0

## Stable overview bootstrap

- Prevented the independent overview initializer from issuing repeated `/admin/api/me` requests on every KPI DOM mutation.
- Added an in-flight request guard and a debounced mutation retry so the backoffice no longer floods the browser/API during first load or refresh.
- Reuses the authenticated user already established by the main session bootstrap and resets that state cleanly on logout.

