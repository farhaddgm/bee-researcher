# Bee Researcher v3.20.10

## Session bootstrap race fix

- Prevented the appearance-preferences panel from calling an authenticated
  endpoint before `/admin/api/me` has resolved.
- An early 401 can no longer invalidate a valid session bootstrap or leave the
  sign-in flow waiting on a conflicting auth transition.
- Retained the bounded session, login, and post-login request timeouts from
  v3.20.9.

## Verification

- Full automated test suite passes.
- Production health and unauthenticated login paths were checked after deploy.
