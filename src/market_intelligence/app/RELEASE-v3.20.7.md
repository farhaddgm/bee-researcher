# Bee Researcher v3.20.7

## Owner support inbox

- Renamed the personal support queue to **Tickets**.
- Added an owner-only **Submitted tickets** panel containing every user's
  submitted tickets.
- Owners can reply and update status from the submitted-ticket cards.
- Non-owner accounts receive only their own tickets; the complete owner queue
  is not included in their API response.

## Verification

- The existing support API and RBAC checks remain authoritative.
- Full application tests and the localization audit pass in the container.
