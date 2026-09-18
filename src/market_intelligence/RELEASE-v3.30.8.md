# Bee Researcher v3.30.8

## Action diagnostics

- Added a bounded client action trace for workspace-dependent controls.
- Every action can now be correlated with its live DOM phase, API route class,
  HTTP status and duration without recording article text, credentials or
  customer data.
- A 3.2-second watchdog reports an action that received a click but never
  reached a handler or modal, making silent failures distinguishable from
  permission and network failures.
- Server logs now include the sanitized route, status and duration for action
  failures.

## Regression coverage

- Added endpoint coverage for structured action telemetry.
- Full isolated CI and public browser checks remain green.
