# Bee Researcher v3.30.13

## Media discovery and publication language

- Media discovery now ranks up to five candidates using topic fit, source
  confidence, language, region, evidence and media type, with a diversity
  pass so one category cannot fill the whole result list.
- Common keyword requests are resolved through the local public-media
  directory even when the optional external drafting provider is unavailable.
- A temporary DNS, transport or timeout failure no longer mislabels a valid
  source as “not found”. The candidate remains editable and can be saved after
  the owner reviews its homepage, feed and connector.
- Accepted and rejected suggestion cards are removed from the active queue;
  only an approved, verified source is added to the media list.
- Each source now has an independent publication-language setting (`source`,
  Persian, English, Turkish, Arabic, Italian, Spanish, German or French).
  Analysis and publication use that setting without changing the source's
  detected language; `source` keeps the existing business-language behavior.
- Source language itself can be corrected in the media editor, separately from
  the publication-language override.

## Verification

- 343 unit and contract tests pass.
- Python compilation passes for the changed service modules.
