# Bee Researcher v3.29.0 — Admin UX and Support workspace

This release is a focused Admin UI improvement pass. It keeps the existing
API, permissions, project isolation, and publishing behavior unchanged.

## Delivered improvements (20)

1. Support now has one deterministic renderer; legacy support layers cannot
   overwrite or duplicate its cards.
2. The new-ticket form and ticket queue use equal-width cards on desktop.
3. The two cards stretch to a shared visual baseline without forcing a fixed
   height on long ticket content.
4. The layout collapses to one column at tablet width and remains usable on
   narrow screens.
5. Ticket search has a clear action that returns focus to the search field.
6. Search input, priority filter, and status tabs share one predictable
   toolbar rhythm.
7. Loading tickets uses reserved skeleton rows instead of a blank or jumping
   panel.
8. The Support root exposes an accessible label and `aria-busy` during loads.
9. Refresh, filtering, and retry actions are safe against stale responses.
10. Empty and no-match states explain the next action in the selected locale.
11. Ticket cards keep subject, ticket number, metadata, status, and priority
    visually separated.
12. Owner replies and status controls remain scoped to the owner queue.
13. Form validation remains inline and preserves focus on the invalid field.
14. Character count and priority controls remain visible without crowding the
    submit action.
15. All Support labels and states retain the eight-language catalog contract.
16. Support styles respect reduced-motion preferences for loading shimmer.
17. Owner-only labels are idempotent and never duplicate after a re-render.
18. The Collection and analysis schedule keeps a single Owner-only badge.
19. The publication-limit helper sentence was removed from Channels as
    requested; processing and publication limits remain independent in code.
20. The template security helper sentence was removed from Content; server
    validation and safe preview behavior remain unchanged.

The visual choices follow established dashboard patterns: concise search with
clearable input, consistent form labels and spacing, compact status feedback,
and responsive data-list behavior. References used for the review include
[Carbon Search](https://carbondesignsystem.com/components/search/usage/),
[Carbon Forms](https://carbondesignsystem.com/components/form/usage/),
[Carbon Notifications](https://carbondesignsystem.com/components/notification/usage/),
and [Carbon Data Table](https://carbondesignsystem.com/components/data-table/usage/?source=post_page---------------------------).

## Verification

- Admin HTML contract tests verify removal of the two requested sentences,
  equal-width Support layout, clear-search control, skeleton loading, and
  single Owner-only labeling.
- Python syntax and catalog JSON validation completed.
- Release version: `3.29.0`.
