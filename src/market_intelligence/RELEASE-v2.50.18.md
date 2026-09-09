# Release v2.50.18

## Authorization-scoped loading states

- The Security page clears users and sessions immediately when the authenticated account changes.
- It shows an explicit loading state until `/admin/api/users` and `/admin/api/sessions` return the current account's authorized data.
- A failed authorized-list request leaves the table empty with a clear error state; stale owner or cross-project rows are not rendered.
- Business cards now use the same guarded loading flow and cannot flash the previous account's or project's businesses.
