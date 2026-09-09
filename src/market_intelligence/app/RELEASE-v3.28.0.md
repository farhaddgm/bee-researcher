# Bee Researcher v3.28.0 — User portal UX pass

This release improves the read-only `/user` news portal and keeps workspace and
publishing permissions unchanged.

## Delivered

1. Redesigned search field with a stable 46px target, focus ring, icon, clear action, and responsive sizing.
2. Search is a semantic `role="search"` form and Enter applies the query immediately.
3. Escape clears an active search; the clear action returns focus to the field.
4. Search requests remain debounced and cancel stale requests to avoid request storms.
5. Search context is announced to assistive technology with a hidden hint and live result status.
6. URL state keeps the query, assistant, filters, sort, and date window shareable and restorable.
7. Source, status, sort, and date filters keep a consistent toolbar layout on narrow screens.
8. Numbered pagination remains available for direct page access, while the verbose “Page 1 of 8” footer label is removed.
9. Previous/next pagination controls retain disabled states and accessible labels.
10. Loading skeletons reserve card space while a feed request is in flight.
11. Empty, error, and cached-snapshot states explain what the reader can do next.
12. News direction remains scoped to card and full-reading content only.
13. Reader settings use aligned responsive cards with consistent padding, borders, and focus treatment.
14. Settings remain a dedicated `/user/settings` page with a clear return path.
15. Preferences show an inline save status so readers know when an automatic change is stored.
16. A reset-preferences action restores the documented defaults after confirmation.
17. The hamburger control now collapses the desktop sidebar and persists that choice locally.
18. On small screens the same control opens a drawer with an overlay, Escape-to-close, and outside-click close.
19. Sidebar labels expose accessible names and active navigation state; collapsed items provide hover titles.
20. Responsive cards, controls, reduced-motion handling, keyboard shortcuts, saved/read state, export, and browser notifications are kept consistent across the portal.

## Verification

- User portal contract tests cover the search form, sidebar overlay/collapse hooks,
  dedicated settings route, pagination numbers, and removal of the verbose page
  status label.
- Release version: `3.28.0`.
