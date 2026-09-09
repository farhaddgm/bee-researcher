# Release v3.29.21

## Support conversation stability

- Added a final ownership guard for the threaded Support workspace so delayed
  legacy locale/data callbacks cannot overwrite the v4 ticket interface.
- Ticket replies remain append-only conversation messages; the legacy owner
  reply input is never prefilled with an earlier response.
- The browser flow now keeps the requester ticket list, click-to-open
  conversation modal, owner reply action, and closed-ticket lock together.
