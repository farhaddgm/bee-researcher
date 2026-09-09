# Bee Researcher v3.20.1

## Removed accidental MFA login screen

- Removed the two-step verification challenge from the back-office sign-in
  form and deleted its client-side handlers and styling.
- Removed the unused back-office MFA management panel and routes.
- Back-office sessions now complete password sign-in directly, including for
  accounts that had a legacy MFA preference; the read-only `/user` portal's
  independent MFA flow remains unchanged.
- Added a contract test that prevents the removed challenge from returning in
  the back-office HTML or routes.
