# Bee Researcher v2.25.0

## MI-038 — new-assistant functional readiness

- New assistants now receive an isolated runtime configuration with safe defaults for model, item cap, feedback allowlist and schedule slots.
- New assistants and clones copy the reusable media/topic catalog into their own workspace; operational health, channel destinations and secrets are never copied.
- Media and topic keys are now unique per assistant instead of globally, so a new bot can use the same catalog keys without cross-workspace collisions.
- Added a workspace readiness endpoint that reports safe checks for profile, catalog, channels, runtime settings and activation state.
- Added an explicit server-environment-only token status; tokens are never accepted from arbitrary workspace config or returned by the API.
