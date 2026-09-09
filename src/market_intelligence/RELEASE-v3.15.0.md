# Bee Researcher — v3.15.0

## Read-only news portal

- A separate `/user` portal lets an authenticated account read only the published messages for assistants it can access.
- The portal uses a dedicated `research_bee_user_session` cookie and never exposes settings, sources, credentials, publishing controls, or admin APIs.
- Owners can read active/testing assistants; other accounts are limited to their explicit assistant memberships.
- News is sourced from the persisted `published` publications, so the browser view matches the final Telegram-ready message.
- The browser can request notifications and polls for new publications every 60 seconds; no server-side push permission is required.

## Verification

- The existing back-office contract remains unchanged.
- New portal contract tests cover non-indexability, separate authentication, and the read-only route surface.
- Publish and Telegram behavior are not changed by this iteration.
