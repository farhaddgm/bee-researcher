# Bee Researcher v3.29.1 — User reader workspace

This patch improves the read-only `/user` portal without changing its
permissions or publication API.

## Delivered

- Reader Settings and News Reader now use the same 1240px content canvas;
  switching between the two routes no longer changes the body width.
- The assistant selector is disabled and labelled as loading until its
  accessible workspace list is ready, preventing a blank or misleading
  control during first paint.
- Assistant-load failures now render an actionable empty state instead of
  leaving an apparently frozen page.
- News responses carry a sequence guard in addition to `AbortController`, so
  a late response cannot replace a newer assistant or search result.
- Preference writes are queued in order, preventing rapid settings changes
  from being persisted out of order.
- Source filters reset when the reader switches assistant and are preserved
  in the URL for refresh/share continuity.
- The `?` keyboard shortcut no longer navigates away while the reader is
  typing in an input, textarea, or select.
- Login and initial data loading expose busy state to assistive technology.

The layout follows Carbon’s responsive shell and form guidance: a stable
content measure, proportional responsive columns, and consistent spacing.
References: [Carbon UI Shell](https://carbondesignsystem.com/components/UI-shell-header/usage/),
[Carbon Forms](https://carbondesignsystem.com/components/form/usage/), and
[Carbon 2x Grid](https://carbondesignsystem.com/elements/2x-grid/overview/).

## Verification

- `python3 -m py_compile app/user_ui.py` passed.
- User portal contract tests: 9 passed.
- Full market-intelligence suite: 308 passed.
- Container health check passed after deployment.
