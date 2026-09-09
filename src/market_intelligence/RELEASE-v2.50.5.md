# Bee Researcher v2.50.5

## Stable signed-in identity in the back office header

- The signed-in username is now an authoritative header value and is not replaced by a transient empty response during background refreshes.
- A guarded identity sync revalidates `/admin/api/me` while the app is visible and respects the authentication transition counter.
- A focused header observer restores the current username if a late repaint mutates the slot; it stops being active for the signed-out shell.
