# Bee Researcher Back Office v3.20.11

## Login bootstrap hardening

- Authenticated UI requests are now blocked until the current `/admin/api/me` response commits the signed-in user.
- Optional panels no longer fetch account-scoped data while the login shell is still bootstrapping.
- This removes the pre-auth 401 race that could invalidate a valid session response and leave the login page incomplete or stuck.
- Existing request timeouts and the recoverable shell watchdog remain enabled.
- The bootstrap catch path now explicitly restores a usable login form after a failed `/me` response or a synchronous shell error.
