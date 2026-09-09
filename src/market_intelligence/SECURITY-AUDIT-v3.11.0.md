# Security audit — v3.11.0

The release keeps the v3.10.x security controls and adds no new secret-bearing
client fields. Slug changes are constrained by a strict allow-list and a
database uniqueness constraint; template content is normalized and rendered by
the existing escaped Telegram renderer. The new Content page uses the same
owner-only API gate as the previous editor and does not expose credentials.

Remaining operational controls are unchanged: MFA/WebAuthn enrollment and
recovery, removal of legacy `unsafe-inline` CSP allowances, and CI image
signing/SBOM/CVE scanning are planned hardening work.
