# Bee Researcher 3.29.19

## Collection and analysis schedule

- Prevented duplicate localization/data observer passes from rebuilding an
  unchanged 7×24 collection grid. Schedule buttons now remain attached and
  clickable while the page settles.
- Rebinding the collection-settings save action is idempotent when the card is
  moved or reused, so owner changes always reach the runtime-settings API.
- Fixed the performance-guard TTL scope error that produced a browser runtime
  exception during admin bootstrap.
- Verified the owner flow end to end: toggle a collection hour, save it,
  re-read runtime settings, then restore the original schedule.
