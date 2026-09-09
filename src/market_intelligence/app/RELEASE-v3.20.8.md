# Bee Researcher v3.20.8

## Login flow reliability

- Treat a `401` from `/admin/api/login` as an invalid-credentials response instead of an expired session.
- Keep the login error visible; a failed login no longer increments the auth transition and suppresses its own message.
- Serialize login submissions and disable the submit button while authentication is in flight, preventing duplicate requests and race conditions on slow connections.
- Restore the button after a failed attempt while preserving the loading state during a successful transition into the admin UI.

## Verification

- Full automated test suite passes.
- Production health endpoint reports healthy after deployment.
