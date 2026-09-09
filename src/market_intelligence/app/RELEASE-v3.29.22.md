# Release v3.29.22

## Support conversation stability

- The threaded Support workspace is now the only visible surface after any
  delayed compatibility callback; the old inline reply form cannot overwrite
  it.
- A short pending state hides the stale DOM before the threaded shell is
  restored, eliminating the visual/input flash during navigation or locale
  refresh.
- Ticket replies remain append-only messages and appear in the chronological
  conversation modal for both requester and owner.
