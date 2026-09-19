# Bee Researcher v3.30.6

## Back-office buttons that silently did nothing

- Root cause: the MI-208 runtime migrator, which turns legacy inline
  `onclick`/`oninput` attributes into ordinary listeners, was written with
  doubled backslashes (`\\w`, `\\(`, `\\d`) inside a raw Python string. The
  browser therefore received regular expressions that required literal
  backslashes and never matched `closeModal()`, `toggleTopic('id',true)` and
  similar handlers.
- Impact: under the enforcing strict CSP
  (`MARKET_INTELLIGENCE_CSP_STRICT=true`, which forbids inline event
  attributes) every dynamically rendered inline handler was dead. The modal
  close (×) and Cancel buttons, table row actions (Settings, Enable/Disable,
  Delete) and the media/topic search boxes did nothing and showed no error.
  The default compatibility CSP masked the defect because the browser ran the
  attributes natively.
- Fix: corrected the patterns, added a proper string-literal decoder for
  handler arguments (numbers are now real numbers), and allowed a trailing
  semicolon and multi-line attribute values. Migrated nodes have the attribute
  removed, so a control still runs exactly once in both CSP modes.

## Regression coverage

- `test_runtime_migrator_regexes_are_not_double_escaped` fails if a doubled
  escape returns to the migrator.
- Browser checks (strict and compatibility CSP, real login flow): Add Media and
  Add Topic open, the modal closes via × and Cancel, row Settings and
  Enable/Disable send exactly one request, and search filters the table.
