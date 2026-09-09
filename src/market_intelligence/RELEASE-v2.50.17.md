# Release v2.50.17

## Admin account and session security

- Disabled accounts now receive a clear sign-in response: «حساب شما غیرفعال است. با مدیر حساب‌ها ارتباط بگیرید.» (or the equivalent English copy).
- Deactivation invalidates existing sessions immediately; a race-winning request is rejected with the same disabled-account state.
- Administrator sessions now use a sliding inactivity timeout capped at six hours. Every authenticated request renews the deadline, while six hours without activity closes the session.
- Existing sessions are capped by migration `0013_admin_session_idle_cap`.
- Browser cookies no longer impose an unintended absolute six-hour limit; the server-side idle boundary remains authoritative.
