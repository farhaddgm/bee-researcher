# Release v2.63.0

## Backoffice bootstrap recovery

- Prevented a failed early script or delayed session response from leaving both login and app shells hidden indefinitely.
- Added a fail-safe recovery path that returns to the login shell after eight seconds, and immediately recovers on an uncaught startup error.
- Kept the normal authenticated bootstrap unchanged when the session/API responses are healthy.
- Corrected the HTTPS proxy route so Bee Consultant branding assets are served by the consultant service instead of returning 404 from Market Intelligence.

