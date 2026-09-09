# Bee Researcher v3.17.0

## MI-207 — MFA enrollment and recovery

- Added owner-only TOTP enrollment with a short-lived encrypted pending draft.
- Added explicit policy enable/disable controls; MFA is never enabled silently.
- Added one-time recovery codes, replay-resistant TOTP verification, session
  verification state, and audit events for enrollment, policy changes,
  verification and recovery rotation.
- Added the same second-step challenge to the read-only `/user` portal so the
  separate reader session cannot bypass account MFA.
- No WebAuthn factor is silently registered: the enrollment contract remains
  ready for a future passkey adapter, while TOTP is the available fallback.

## Verification

- `py_compile` for the modified application modules: passed.
- Static admin and reader MFA route/UI contracts: passed.
- Migration `0034_mfa_sessions` is included; existing sessions default to
  verified during the additive rollout.
- Production image `ai-market-intelligence:3.17.0` is built and deployed.

## Approved security gates progressed

- The staged CSP budget is now measured in CI at 42 event attributes and 54
  style attributes; any further growth fails closed. The two compatibility
  directives remain Report-Only until the remaining inline handlers are
  migrated and browser smoke is signed off.
- The supply-chain workflow keeps dependency audit, SBOM generation, Trivy
  CRITICAL/HIGH scanning and Cosign verification as required promotion gates.
  A real registry reference and OIDC signer are intentionally still required
  before a production promotion can pass.
- The additive locale registry and QA checklist remain available for the five
  new locales; native terminology and layout review is still a human release
  gate and is not replaced by machine fallback.
