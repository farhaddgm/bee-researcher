# Bee Researcher — v3.29.17

## Media and Topics action reliability

- Media and Topics page-head actions now share one guarded action layer.
- Add media, add topic, public-social source, source suggestions, and health
  checks recover an authorized workspace before running, so an early click
  during first paint is no longer lost.
- A stale workspace id from a previous account is rejected and replaced only
  with an assistant returned for the current authenticated account.
- Legacy direct/inline handlers are always routed through the guarded wrapper;
  duplicate clicks are ignored while an action is in progress.
- Dynamic row actions (enable/disable, settings, delete) are explicitly
  exposed on `window` for the CSP compatibility migration.

## Verification

- `python -m unittest discover -s tests -q`: 329 tests passed.
- `python3 -m py_compile app/market_intelligence/app/admin_ui.py`: passed.
- `git diff --check`: passed.
- Service health: healthy after deployment.
