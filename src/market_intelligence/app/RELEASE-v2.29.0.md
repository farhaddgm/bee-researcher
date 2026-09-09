# Bee Researcher Market Intelligence v2.29.0

## MI-041 — assistant readiness feedback

- Fixed the “بررسی آمادگی” action on every assistant card. A not-yet-ready assistant is no longer presented as a generic error; the UI opens a clear readiness report showing each check, missing configuration, and the exact next items.
- The readiness endpoint now explicitly returns `404` for a missing workspace instead of allowing a null dereference to become a server error.

## Verification

- 44 regression tests pass.
- The image and Compose service are versioned `2.29.0`.
