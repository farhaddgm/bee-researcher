# Bee Researcher v3.30.12

## Media discovery reliability

- Added a deterministic local public-media directory for common Persian and
  international sources, so Add media and Suggest media remain usable when the
  optional drafting provider is unavailable.
- Added keyword/tag matching for suggestions and a public-domain escape hatch
  for sources not in the directory.
- Kept final registration behind the real connector/parser verification step;
  no source is saved or published before that check succeeds.
- Unknown names now return actionable alternatives instead of a misleading
  provider-unavailable message.
