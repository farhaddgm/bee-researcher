# Bee Researcher — v3.12.0

## Scope

This release records and advances the remaining security and quality items
MI-206 through MI-209.

## Included

- Added the additive locale registry and selector for English, Persian,
  Turkish, Arabic, Spanish, Italian and German. Direction and common product
  copy follow the selected locale; native review remains a release gate for the
  five new locales.
- Added the owner-safe MFA/WebAuthn enrollment contract and recovery design;
  enforcement is intentionally gated until the owner registers a factor.
- Added a staged CSP migration plan that preserves the existing nonce policy
  while the legacy inline shell is refactored.
- Added a CI supply-chain gate with `pip-audit`, image SBOM generation, Trivy
  OS/library scanning and strict Cosign signature verification for main-branch
  promotion.

## Verification

- Python compilation and `git diff --check`: passed.
- Full Market Intelligence suite: 255 tests passed before this release;
  targeted locale and workflow checks are added for the next CI run.
- Production promotion remains gated on CI registry/OIDC variables for signed
  image verification.
