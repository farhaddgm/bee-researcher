# Bee Researcher v3.31.0

## Access control and account security

- The account owner is identified only by `MARKET_INTELLIGENCE_OWNER_EMAIL`
  (default `farhad.dgm@gmail.com`). Usernames and the stored role no longer
  grant ownership; the stored `owner` role is retired (migration 0037 moves
  the address onto the existing owner row and keeps its password). The owner
  address can never be assigned to another account.
- The bootstrap password can create the owner only on an empty account table.
- A lower or equal role can no longer reset the password of, disable,
  rename, re-role, remove from a project, or close the sessions of a peer
  or superior (rank is checked against the target's current role).
- The reader portal password login now shares the back-office brute-force
  budget; disabled or Google-only accounts are no longer revealed without
  the correct password.
- Google sign-in (OpenID Connect + PKCE) for both portals, modelled on
  Contenter: `/admin` and `/user` show only "Sign in with Google" when it is
  configured; the unlinked `/admin/login-up` and `/user/login-up` pages keep
  the password form. The owner manages an allowlist of Gmail accounts
  (Gmail-only or Gmail + password) on the Security page. The Google subject
  is bound on first sign-in. See `GOOGLE-LOGIN.md`.

## Tenant isolation and authorization

- `PATCH /admin/api/assistants/{id}` merges only free-form configuration
  keys; limits, runtime/collection, Telegram, sandbox, share links,
  notifications, privacy and templates stay with their dedicated endpoints.
- Telegram delivery through `/pipeline/run` (`publish: true`) and
  `/pipeline/manual-publish` is owner-only, matching
  `/publications/{id}/publish`; other runs never publish.
- `/admin/api/topics` without `assistant_id` is owner-only.
- `/feedback` records feedback only as the signed-in account and only on a
  workspace that account can access.
- Owner-only routes no longer depend on a stored role, so the owner can edit
  sources, topics and the business profile again.

## Connector credentials

- Each server credential is bound to its connector family and to the
  provider API hosts (X: api.x.com/api.twitter.com, Instagram:
  graph.facebook.com/graph.instagram.com, Telegram: api.telegram.org) over
  HTTPS, checked on every redirect hop. Extra gateways must be approved with
  `MARKET_INTELLIGENCE_CONNECTOR_GATEWAY_HOSTS`.
- Source updates validate URLs and the merged connector configuration;
  model-drafted source suggestions can only become plain public feeds.

## Delivery and scheduling

- A publication is claimed (`publishing`) before it is sent, so concurrent
  scheduler and manual runs cannot send it twice; a delivered-but-unrecorded
  message is never re-sent automatically.
- "Publish one now" sends exactly one (the newest eligible) item.
- One failing workspace no longer stops collection or delivery for the
  others; failing bootstraps back off from 5 minutes up to 1 hour.
- A schedule slot stays due for `MARKET_INTELLIGENCE_SCHEDULE_GRACE_MINUTES`
  (default 10) so an overrunning tick delivers late instead of skipping;
  slots beyond the grace window are recorded and logged as missed.

## Data

- Saving business knowledge no longer strips Telegram destinations and
  share-link hashes from the workspace configuration.
- The privacy panel retention is enforced daily per workspace (minimum 30
  days; unset workspaces follow `MARKET_INTELLIGENCE_NORMALIZED_RETENTION_DAYS`).
  Deleted articles leave content-free source tombstones so feeds cannot
  resurrect and republish them; empty clusters are removed.
- Bulk archive/reject now work: the publication status check accepts the
  `archived`, `rejected` and `publishing` states.
- "Close all other sessions" works again (route ordering).
- Extraction no longer picks up items from disabled sources.

## Upgrade notes

- Run migrations (automatic on start). Production check before release:
  owner row `owner`, no credentialed sources and no saved retention values,
  so no articles are deleted by this upgrade.
- To enable Google sign-in set `MARKET_INTELLIGENCE_GOOGLE_CLIENT_ID`,
  `MARKET_INTELLIGENCE_GOOGLE_CLIENT_SECRET` and
  `MARKET_INTELLIGENCE_GOOGLE_REDIRECT_URI`; until then password sign-in is
  unchanged.
