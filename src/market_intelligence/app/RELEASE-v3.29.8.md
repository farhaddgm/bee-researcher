# Bee Researcher Admin — v3.29.8

## UI reliability and action hierarchy

- Added the correct Lucide `life-buoy` icon for the Support navigation item and a safe help-icon fallback for any future dynamic icon.
- Made Assistants the deterministic post-login landing view, including the pre-JavaScript first paint; saved appearance preferences no longer redirect a fresh login to another page.
- Scoped Support to its dedicated view and removed legacy support nodes that could escape into other views.
- Standardized admin action controls with one typography/height contract, equal sibling widths per action group, text-sized widths across unrelated groups, and primary actions last in each group.
- Added responsive mobile stacking without changing the existing page information architecture.

## Verification

- Python compile and focused UI contract tests passed.
- Full market-intelligence test suite passed before release.
- Docker image `ai-market-intelligence:3.29.8` deployed with a healthy `/health` response.
