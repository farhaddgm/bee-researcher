# Bee Researcher v2.54.0

## MI-080 — Project business name in published templates

- The `ارتباط با …` heading is now rendered from the active business profile of the current project instead of the deployment-wide `داتین` fallback.
- Feedback and observer Telegram messages, saved previews, reanalysis refreshes, and owner template previews all use the project business name.
- Business names are HTML-escaped before Telegram rendering; existing message length and safe-template limits remain unchanged.
- Queued previews are re-rendered immediately before delivery, so previews created by an older release also use the current project's business name.
- Legacy/default workspaces retain `داتین` only when no project business profile exists.

Verification: focused renderer coverage plus the full service test suite; health check after deployment.
