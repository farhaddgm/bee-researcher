# Bee Researcher v3.26.0 — User portal UX

## What changed

The User portal now follows a focused reader-shell pattern: navigation and identity live in a persistent sidebar, while the header stays reserved for page context. Reader settings are a real page at `/user/settings`; they no longer expand inside the news feed.

Twenty UX improvements are included:

1. Dedicated Reader settings route and back-to-news link.
2. Persistent sidebar navigation with clear active state.
3. Bee Researcher branding moved from the header to the sidebar.
4. Signed-in user identity shown in the sidebar with an initial avatar.
5. Mobile sidebar drawer closes after navigation.
6. Search input has a modern focus ring and elevated affordance.
7. Search has a clear action that appears only when needed.
8. Search supports `/` and `Ctrl/Cmd+K` shortcuts.
9. Search requests remain debounced to avoid request storms.
10. Search, assistant, sort and date state stays shareable in the URL.
11. Source filtering is generated from the loaded publication set.
12. Newest, oldest and source ordering remain explicit controls.
13. All, unread and saved views remain keyboard and screen-reader friendly.
14. Numbered pagination provides direct page jumps and a compact ellipsis pattern.
15. Page-size preference remains local to the reader.
16. Loading skeletons prevent blank layout shifts during refresh.
17. Last successful publication snapshot remains available when live refresh fails.
18. Read and saved state remain local and do not mutate workspace data.
19. Keyboard navigation supports card focus, read, save and full-content actions.
20. Full-content dialog retains copy, share, print, focus return and news-only text direction.

## Benchmark basis

- Material Design 3 navigation drawers informed the persistent, discoverable sidebar.
- Carbon Design System data-table guidance informed the search/toolbar hierarchy, visible pagination and readable content density.
- Intercom's inbox search pattern informed an always-available search field with lightweight filtering and clear state.

## Verification

- User portal contract tests include the new `/user/settings` route.
- Full market-intelligence test suite is run as part of deployment.
