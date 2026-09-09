# Bee Researcher v2.90.1

## Hotfix

- Fixed an infinite `MutationObserver` loop in the News List header normalizer that could repeatedly rewrite the table header and freeze the back-office browser.
- No API or database changes; this is a safe UI-only patch on v2.90.0.

## Verification

- Python syntax and diff checks pass.
- Existing pipeline and API/config contract tests pass in the production-contract test environment.
- Production health is checked after deployment.
