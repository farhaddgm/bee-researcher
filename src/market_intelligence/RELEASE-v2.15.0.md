# Bee Researcher v2.15.0

## MI-032 — Backoffice workspace and account management

- Added complete assistant editing from the backoffice, including status and sanitized JSON configuration.
- Added workspace member assignment and role changes from the assistant view.
- Added source priority/rate-limit and topic importance/threshold editing controls.
- Added business-profile editing through the authenticated API/UI.
- Added admin account management: username, role, activation state, audit logging, and safe self-account guardrails.
- Added active-session inventory and administrator-only session revocation.
- Password hashes, session tokens, bot tokens, and channel credentials remain excluded from UI/API output.
- The existing password-change flow remains available and is audited.

## Verification

- Python source compiles successfully with `python3 -m compileall`.
- Full runtime tests require the project container/dependencies; the host environment does not have FastAPI/Pydantic installed.
- MI-033 remains unstarted because its roadmap row has no product description or final document.
