# Bee Researcher v3.30.7

## Reliable workspace actions and diagnostics

- Workspace-gated actions now replay on the live DOM node after an async
  workspace refresh, so a render replacement cannot discard the click.
- Add Media/Add Topic and the other workspace-dependent controls expose a
  bounded action trace and a localized failure instead of silently returning.
- Client diagnostics contain only an allow-listed action, phase, outcome and
  view; article text, credentials and customer data are never sent.
- Server logs now distinguish action failures from generic browser errors.

## Regression coverage

- Added first-paint/replacement-safe browser coverage for Add Topic and Add
  Media.
- Full isolated CI and public browser checks remain green.
