# Bee Researcher v3.29.13

## Sidebar collapse stability

- Desktop hamburger collapse is now a shell-only layout action and preserves the active page.
- Initial URL routing is applied once after authentication instead of on every shell class mutation.
- Preference hydration no longer navigates the user back to Assistants after a page is open.
- Collapsed layouts keep page grids, tables, cards and action groups responsive without an Assistant-only resize override.
- Sidebar state exposes consistent `aria-expanded`, `aria-pressed` and `data-sidebar-collapsed` values.

## Verification

- Full Python test suite: 325 tests passed.
- Image: `ai-market-intelligence:3.29.13`.
