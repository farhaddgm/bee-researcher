# Bee Researcher v3.30.6

## Workspace action reliability

- Workspace-dependent controls now wait for the authorized assistant list when
  the first paint exposes a button before data loading has completed.
- The original click is replayed once the workspace is ready, preventing Add
  Media, Add Topic, pipeline, schedule, and related project actions from
  appearing inert during a load race.
- Catalog creation handlers now use the same asynchronous workspace gate and
  surface a localized error when the selected assistant cannot be loaded.
- Replay markers are consumed after one pass so later clicks are guarded again.

## Regression coverage

- Added static contract coverage for the shared workspace gate and async
  catalog handler.
- Full isolated CI suite remains green.
