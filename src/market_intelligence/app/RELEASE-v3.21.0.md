# Bee Researcher v3.21.0

## Owner-controlled collection and analysis

- Added a separate owner-only collection/analysis schedule, independent from
  publication hours.
- Added an owner-only 7×24 schedule grid with day/hour bulk selection.
- Added safe controls for enabling collection, per-source items, per-run
  analysis items, and the project daily analysis budget.
- Preserved the existing publication cap of seven items per publication slot.
- Kept the project timezone and freshness window as shared project settings;
  collection never publishes directly.
- New workspaces retain the immediate bootstrap scan, unless the owner
  disables automatic collection.
- Non-owner API responses omit collection-control values; writes containing
  collection fields return `403 owner role required`.
- Scheduler status also redacts the collection cadence for non-owners while
  retaining the publication status needed by their workspace view.
- The owner Operations view now surfaces collection state, weekly slot count,
  per-run analysis cap, and daily analysis budget for faster verification.
