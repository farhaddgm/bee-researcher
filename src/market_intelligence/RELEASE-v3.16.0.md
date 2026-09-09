# Bee Researcher v3.16.0

## MI-216 — UX Writing inventory

- Added the `UX Writing` Google Sheet tab with a source-backed inventory of the
  back-office navigation labels, visible copy, placeholders, accessibility
  labels, and bilingual dynamic copy maps.
- The inventory records the route, Persian section name, concise purpose,
  Persian copy, English copy, content type, and source location.

## MI-217 — Read-only news portal

- Confirmed and documented the separate `/user` portal and its own session
  cookie. It exposes only published content for assistants the signed-in user
  may read; no settings or publishing mutation endpoints are exposed.
- Browser notifications, multi-assistant selection, project membership scope,
  and private no-index/no-follow headers remain covered by the portal contract.

## MI-218 — Stable account navigation

- Removed the legacy dynamic Account navigation button from the primary
  sidebar. Account remains available from the authenticated avatar menu only,
  eliminating the refresh-time flash and duplicate navigation surface.
- Added a static contract check for the no-flash behavior.

## Verification

- Python syntax checks passed for the changed application modules.
- Static contracts passed for the read-only portal and account navigation.
