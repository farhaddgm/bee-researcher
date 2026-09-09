# Bee Researcher v2.66.0

## Faster project list on refresh

- The authorized project list and workspace selector are now painted as soon as `/admin/api/assistants` returns.
- Metrics, publication history, Telegram readiness and runtime settings continue hydrating afterward without blocking the project cards.
- Previous authorization-safe loading behavior is preserved: cards remain in a loading state until the account-scoped project response is available.

## Verification

- Full unit test suite: 133 tests passed.
- Service health: `healthy`.
