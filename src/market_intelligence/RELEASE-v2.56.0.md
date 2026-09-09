# Bee Researcher v2.56.0

## MI-082 — Preserve the source headline in Telegram messages

- Telegram title rendering now uses the exact normalized article title stored from the media source, rather than the model-generated analysis headline.
- The source title is used consistently for feedback and observer channels, new previews, refreshed previews, fallback regeneration, reanalysis, and delivery-time re-rendering.
- Summaries, business relevance, opportunity/risk analysis, and safe template behavior are unchanged.

Verification: full service test suite and health check after deployment.
