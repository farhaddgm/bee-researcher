# Bee Researcher v2.77.0

## Roadmap delivery

- **MI-131 — canonical account rows:** the admin users API now collapses legacy duplicate rows by normalized username. The active session identity is preferred, followed by the row with project-access metadata, so the owner is rendered once without weakening RBAC visibility.
- **MI-132 — sidebar account menu:** account identity, account/security shortcuts, and sign-out now live in a keyboard-friendly dropdown at the bottom of the sidebar. The header no longer renders the account chip or sign-out control.
- **MI-133 — shared header shell:** the Assistant header layout is applied consistently across authenticated back-office views, with responsive logical positioning and bilingual account-menu labels.

## Verification

- Python bytecode compilation completed for the market-intelligence app and tests.
- `git diff --check` completed without whitespace errors.
- The dependency-backed unittest suite could not run in the current shell because `pytest`, FastAPI, and Pydantic are not installed locally; run the service test container before production deployment.

## Deployment

This change is versioned in source as `2.77.0`. Production deployment remains a separate operational action.
