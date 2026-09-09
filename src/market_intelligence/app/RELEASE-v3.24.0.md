# Bee Researcher v3.24.0 — User portal navigation and reading UX

## Research basis

The redesign uses patterns documented by Google News and Intercom: save-for-
later reading, persistent search and filters, explicit result navigation,
customizable views, and keyboard-first operation. These patterns are adapted
to Bee Researcher's read-only, project-scoped portal.

- [Google News — Save stories](https://support.google.com/googlenews/answer/7690211)
- [Intercom — Inbox search and filter](https://www.intercom.com/help/en/articles/6516006-inbox-search-and-filter)
- [Intercom — Custom views and folders](https://www.intercom.com/help/en/articles/6588834-organize-your-inbox-with-custom-views-and-folders)

## Twenty new improvements implemented

1. A persistent reader sidebar replaces the header settings button.
2. The signed-in username is shown in the sidebar account area.
3. Sidebar contains clear News reader and Reader settings destinations.
4. Mobile sidebar drawer with an accessible menu toggle.
5. Larger, more legible header logo.
6. Numbered pagination buttons with current-page state.
7. Ellipsis pagination for long result sets.
8. Direct page selection works with mouse and keyboard focus.
9. Search clear button appears only when a query exists.
10. One-click reset of search, source, date, sort and view filters.
11. Query/filter/assistant state is shareable in the URL.
12. Returning to a shared URL restores the same reader view.
13. News-only text direction remains isolated from all UI chrome.
14. Font-size controls for news content.
15. Line-spacing controls for news content.
16. Full-news dialog supports copy to clipboard.
17. Native share action with clipboard fallback.
18. Print action produces a focused article printout.
19. Skip link and reduced-motion support improve accessibility.
20. Source names, metadata and result counts remain stable while filtering.

## Verification

- Full service suite: ۳۰۲ tests passed (including two new User navigation/direction contracts).
- Public `/user`: HTTP 200.
- Public `/health`: healthy; PostgreSQL and Redis healthy.
- Unauthenticated User API: HTTP 401.
- Deployed image: `ai-market-intelligence:3.24.0`.
- No workspace mutation or new credential exposure was added.
