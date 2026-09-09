# MFA/WebAuthn enrollment design

MFA is deliberately not enabled silently. The safe rollout contract is:

- owner-only enrollment first, followed by an explicit policy toggle;
- WebAuthn/passkey as the preferred factor, with TOTP as a fallback;
- single-use, hashed recovery codes shown once and rotated on regeneration;
- step-up authentication for password, user-role, project deletion and secret
  configuration changes;
- rate limits, replay protection, device revocation and an audit event for each
  enrollment, recovery and policy change;
- a tested recovery path before enforcement, so the owner cannot be locked out.

The production dependency is an owner decision for the primary factor and
recovery contact/device. Until that enrollment is completed, the existing
session and password controls remain active and no partial MFA gate is exposed.
