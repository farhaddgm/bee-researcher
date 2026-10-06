# Bee Researcher 3.38.0 — Google-first account access

- Contenter-style Google-first login for Admin and User, with separately unlinked
  password pages. The mode is rendered before paint, not changed by a delayed fetch.
- One independent Researcher account directory, email/legacy-name password login,
  Gmail/Googlemail normalization, PASSWORD/GOOGLE/BOTH methods, owner-managed Google
  allowlist and duplicate-free grants to existing accounts.
- Account management under Admin → Account: names, roles, status, project grants,
  separate User/feedback permissions, search/pagination and safe confirmation dialogs.
- Independent RS256 Google ID-token verification against the fixed Google JWKS
  endpoint, alongside PKCE, signed expiring state, nonce and verified-email checks.
- Persistent rolling 30-day Admin sessions, immediately revocable in the database;
  User always expires at the next 02:00 in the configured service timezone.
- Explicit session portal markers prevent moving a User token into an Admin cookie.
  Changes to credentials, role, membership or grants revoke both portal sessions.
- Eight-language shared UI, responsive login/account forms, native dialogs with
  keyboard containment and focus restoration. No account data is inserted as HTML.
- Additive migration 0043; all old sessions sign in again once because those
  rows did not identify the portal. Accounts, grants and content remain intact.
- Required signed-OIDC/SQL and authenticated browser CI tests; existing password
  E2E suites now use the unlinked password routes.

No Contenter account, database, session, Google client or cookie is shared. Existing
Researcher project scoping and User/feedback permissions are intentionally retained.
MFA and WhatsApp were not changed. This release includes the approved 3.37.0 business
research context; it never auto-activates a real project's business analysis.

Production activation requires independent Researcher Google OAuth configuration.
Do not deploy the Google-first login without that configuration. This release note
is not a production deployment receipt. See docs/ACCOUNT-ACCESS-fa.md.
