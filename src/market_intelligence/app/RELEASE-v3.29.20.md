# Bee Researcher 3.29.20

## Support ticket conversations

- Disabled legacy support renderers as soon as the threaded v4 workspace is
  active; delayed responses from the old renderer can no longer overwrite the
  conversation UI.
- Reply inputs are always blank compose fields. Existing owner replies are
  shown only as immutable conversation messages, never as editable drafts.
- Owner replies continue through the append-only messages endpoint and the
  requester/owner ticket lists remain scoped by the server response.
- Verified in a browser: ticket card → conversation dialog → blank reply
  input → owner reply persisted and shown in the thread, with no browser
  errors.
