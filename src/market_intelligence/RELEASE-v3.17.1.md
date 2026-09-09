# Bee Researcher v3.17.1

## Security-gate follow-up

- Added a nonce-authorised runtime migrator for the remaining legacy inline
  event/style attributes. It converts handlers to ordinary listeners and
  styles to generated stylesheet classes without evaluating arbitrary code.
- Kept CSP in Report-Only during the staged migration and locked the current
  inline surface in CI (42 event attributes / 54 style attributes); any new
  growth fails the gate.
- Added regression coverage for the runtime migrator and corrected the staged
  budget check.
- The v3.17.0 owner-only MFA/TOTP enrollment and recovery controls remain
  enabled and are covered by this patch release.

## Verification

- `python -m unittest discover -s tests`: 277 tests passed.
- TOTP replay/window check: passed.
- Alembic head: `0034_mfa_sessions`.
- Production image `ai-market-intelligence:3.17.1` is healthy after deploy.

The final CSP enforcement, native review of the five additional locales, and
registry/OIDC configuration for signed-image promotion remain explicit release
gates; none is enabled silently.
