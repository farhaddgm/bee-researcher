# Bee Researcher v3.22.0 — User reading portal

## Benchmark basis

The redesign follows patterns documented by mature reading and support
products: Google News supports saving stories for later, while Intercom Inbox
supports scoped full-text search, combined filters, date ranges, sort order,
custom views and recoverable loading/filter errors. Sources:

- [Google News: Save stories](https://support.google.com/googlenews/answer/7690211)
- [Intercom: Inbox search and filter](https://www.intercom.com/help/en/articles/6516006-inbox-search-and-filter)
- [Intercom: Custom views and folders](https://www.intercom.com/help/en/articles/6588834-organize-your-inbox-with-custom-views-and-folders)

## Twenty implemented improvements

1. Full-text search across published message and source name.
2. Source filter populated from the current assistant's data.
3. Relative date filters for 24 hours, 7 days and 30 days.
4. Newest, oldest and source-name sorting.
5. All, unread and saved reading views.
6. Save-for-later bookmarks persisted per browser.
7. Read/unread state persisted per browser.
8. Full article dialog instead of forcing long text into a card.
9. Mark-all-visible-as-read action.
10. CSV export of the active filtered view.
11. Comfortable/compact reading density preference.
12. Two-, three- and four-column responsive layout preference.
13. Configurable page size (8, 12 or 24).
14. Optional one-minute or five-minute auto-refresh.
15. Browser notification opt-in for newly published items.
16. Assistant switcher remains scoped to the authenticated user's access.
17. Keyboard shortcuts for search, refresh, navigation and help.
18. Explicit loading, empty, retry and stale-snapshot states.
19. Last successful snapshot is available when a refresh fails offline.
20. Abortable refresh requests prevent stale responses and duplicate work.

## Security and data boundary

- The portal remains read-only: no source, credential, schedule or publish
  controls were exposed.
- Assistant access is checked server-side before every publication request.
- Search remains bounded by the existing 200-item API limit and query length
  validation.
- Saved/read state is stored only in the reader's browser; article content and
  workspace data are not written to a new server-side table.
- The existing no-store HTML and noindex/nofollow headers are unchanged.

## Verification

- Python compilation and `git diff --check` pass.
- Existing application test expectations were updated for v3.22.0.
- A production image should be built and deployed with the compose service
  after the normal health and smoke checks.
