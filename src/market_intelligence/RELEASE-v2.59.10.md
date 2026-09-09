# Release v2.59.10

## Multi-project pipeline ownership

- Scheduled and manual pipeline jobs now persist the selected assistant ID.
- New projects no longer have their execution history attributed to the
  legacy Dotin workspace by the database default.
- Telegram readiness and delivery remain scoped to the selected project and
  its configured destination channels.
- Repaired the Wepod workspace's stale Rade feed URL; partial source failures
  no longer prevent other sources from being processed and delivered.
