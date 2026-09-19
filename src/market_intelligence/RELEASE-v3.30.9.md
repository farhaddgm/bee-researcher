# Bee Researcher v3.30.9

## CSP legacy-handler migration

- Corrected the JavaScript regular expressions emitted by the raw Python
  ADMIN_HTML template.
- Added safe decoding for quoted legacy handler arguments, including escaped
  newlines, tabs, carriage returns and characters.
- Added support for nested/multiline arguments and optional trailing
  semicolons.
- Replaced the compatibility-sensitive Array.prototype.at usage in the
  migration path.

## Regression coverage

- Added a static guard that fails if double-escaped \w/\d patterns or
  .at(-1) return to the CSP migration block.
- Existing isolated and browser smoke tests remain required before release.
