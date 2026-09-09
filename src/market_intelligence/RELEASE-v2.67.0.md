# Bee Researcher v2.67.0

## Freeze fix

- Removed the self-triggering `MutationObserver` from the insights panel.
- The observer rewrote the same subtree it was watching, causing an endless render loop and blocking interaction after the dashboard loaded.
- Insights are now rendered only when data or language changes.

## Verification

- Full unit test suite: 133 tests passed.
- Service health: `healthy`.
