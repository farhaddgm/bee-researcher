# Bee Researcher Admin — v3.29.7

## Support ticket conversations

- Added an append-only `support_ticket_messages` thread for every support ticket.
- All signed-in users can create tickets, see only their own tickets, open a read-only detail dialog, and add follow-up messages.
- The owner has a separate all-ticket inbox with search, priority/status sorting, multi-message replies, and close/reopen controls.
- Ticket bodies are immutable. A closed ticket rejects status changes and new messages for requesters.
- Status flow is explicit: `open` (waiting for owner), `in_progress`, `answered`, `waiting_user`, and `closed`.
- Owner replies move a ticket to `answered`; a requester follow-up moves it back to `open`.
- Requesters may close their own ticket; the owner receives an in-app notification.

## Interface

- Replaced the legacy support view with a responsive two-column workspace.
- Added read-only ticket cards, a conversation modal, localized status/priority labels, loading skeletons, and rounded controls consistent with the admin design system.
- Added Persian, English, Turkish, Arabic, Italian, Spanish, German, and French copy for the complete workflow.

## Data and verification

- Alembic migration `0035_support_ticket_messages` adds the message table and the `answered` status constraint.
- Full test suite: 323 tests passed.
- Deployment health check and migration head must report `3.29.7` / `0035_support_ticket_messages`.
