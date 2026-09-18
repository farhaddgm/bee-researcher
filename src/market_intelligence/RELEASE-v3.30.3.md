# Bee Researcher v3.30.3

## Stable configuration actions

- Media and Topic actions are re-bound explicitly after every legacy renderer pass.
- The action layer keeps a single deterministic click path, restores buttons after errors, and reports failures instead of failing silently.
- The fix does not use a document-wide mutation observer, avoiding the page-performance regression that such observers can introduce.

## Verification

- Unit, API, security, and UI contract tests pass.
- Public-domain browser checks cover opening both Media and Topic forms for every assistant available to the owner account.
