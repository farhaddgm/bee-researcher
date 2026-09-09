# Bee Researcher v2.65.0

## Refresh responsiveness

- Back-office refresh is now single-flight: an initial load or an in-progress refresh is reused instead of starting a competing full request chain.
- The header and Operations refresh buttons are rebound to the final project-scoped loader, so every refresh uses the same authorization-safe data path.
- Both buttons are disabled and marked busy while data is loading, preventing accidental double-clicks and making progress visible.
- Action-triggered reloads use the same guard, so a save, probe, or workspace switch cannot silently create overlapping refreshes.

## Verification

- Full unit test suite: 133 tests passed.
- Service health: `healthy`.
