# Bee Researcher v3.25.0 — Admin UX quality pass

## Why

This release improves the Admin back office without changing the API or data
model. The goal is a faster, calmer and more predictable workspace for owners,
admins and editors.

## Implemented improvements

1. Command palette with `Ctrl/Cmd+K`, search and keyboard navigation.
2. A visible keyboard route: `/` focuses global search and `?` opens help.
3. Persistent desktop sidebar collapse with a responsive mobile drawer.
4. Correct `aria-current` state for the active navigation item.
5. Skip-to-content link for keyboard and assistive-technology users.
6. Page context in the header showing the selected assistant.
7. Last-refresh time in the header using the selected locale.
8. A lightweight progress bar for navigation and long-running actions.
9. Duplicate-click protection for refresh, health and pipeline actions.
10. Consistent view-enter motion with reduced-motion support.
11. Sticky filter toolbars on content, media and topic lists.
12. Removable filter chips and one-click “clear filters”.
13. Filter state persistence between refreshes for each list.
14. Compact/comfortable density toggle on the main Admin views.
15. Sticky table headers and clearer focused rows for long lists.
16. Copy affordance for IDs and URLs in article details.
17. Unsaved-change protection for schedule, settings and template editing.
18. Stronger empty states and clearer no-match feedback.
19. Responsive palette, tables and controls for smaller screens.
20. Centralized, locale-aware labels for the new controls with no API changes.

## Benchmark notes

- Intercom’s Inbox documents search, composable filters, bulk actions and a
  Command-K action menu as first-class workflows:
  <https://www.intercom.com/help/en/articles/6516006-inbox-search-and-filter>
- Intercom also documents keyboard shortcuts and a discoverable shortcut menu:
  <https://www.intercom.com/help/en/articles/8838656-inbox-faqs>
- Custom views and saved sidebar ordering informed the persistent navigation
  state:
  <https://www.intercom.com/help/en/articles/6588834-organize-your-inbox-with-custom-views-and-folders>

## Verification

- Python syntax check passed.
- Full market-intelligence unittest suite passed in the release container.
- `GET /health` reports `healthy` after deployment.
