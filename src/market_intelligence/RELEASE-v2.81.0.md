# Bee Researcher v2.81.0

## Approved roadmap scope

- MI-143 adds a dedicated Settings surface with a desktop-assistant style
  Appearance section: System/Light/Dark and existing branded themes, accent
  color, compact/comfortable density, collapsed sidebar and launch view.
- Codex-inspired workspace controls are included for automatic refresh and
  optional technical details, while project limits remain owner-only.
- Preferences are stored per signed-in account and apply immediately without
  changing project data or pipeline configuration.

## Verification

- Backend schema and preference persistence are covered by container contract
  checks.
- Python compilation and `git diff --check` are required release gates.
