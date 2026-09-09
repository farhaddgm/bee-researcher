# Bee Researcher v3.29.6 — Consistent admin action controls

## Delivered

- Standardized page-level action groups on a shared responsive grid with equal-width controls.
- Put the primary action first in the DOM and visual order, including late-created controls such as Sandbox and report actions.
- Applied a clear hierarchy: blue primary actions, neutral gray secondary actions, and red destructive actions.
- Made Assistant card actions equal-width and resilient to longer localized labels without breaking the card layout.
- Kept the existing responsive behavior and limited the change to action controls; navigation and data tables retain their existing geometry.

## Verification

- Full application unit suite: 322 tests passed in the production container.
- Health endpoint and container readiness checked after deployment.
