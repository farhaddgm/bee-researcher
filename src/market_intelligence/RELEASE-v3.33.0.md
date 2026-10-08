# Bee Researcher v3.33.0 — per-assistant AI model settings

- Settings contains an Assistant AI card with an explicit model selector.
  Authorized project admins/editors can select the model for their assigned
  assistant. Owner-only collection/capacity controls remain owner-only.
- Adds GPT-6.1 Sol (`gpt-6.1-sol`) and GPT-6 Luna (`gpt-6-luna`) and keeps all
  four previously supported choices. A server-owned catalog supplies both
  validation and UI options, preventing drift between the selector and API.
- Uses the existing approved OpenAI connection and Responses structured-output
  contract. API keys remain deployment-managed and are never sent to the UI.
- Moves model selection out of Channels. Saving/previewing publication settings
  no longer overwrites the assistant's model with a stale/default selection.
- Keeps every existing model selection and the deployment default unchanged.
  Model changes apply to subsequent analysis/relevance runs and invalidate
  score context through the existing model-aware context hash. Published news
  is not rewritten. Media discovery retains its separate search model.
- Model help, labels and confirmations are authored in all eight UI languages.
  Help works on hover and keyboard focus. Unsaved selections survive a locale
  switch; switching assistants cannot save a model to the wrong workspace.
- New-model token estimates use their standard text-token rates instead of
  inheriting the previous Luna estimate. They remain estimates, not invoices.

## Verification and deployment

Both new IDs were returned by the deployed account's model-list API, and both
completed a real, bounded synthetic-news structured analysis without database
writes or delivery. Automated tests cover validation, catalog/default retention,
runtime propagation and structured-output payloads. Mandatory browser E2E covers
eight locales, real persistence/reload, assistant isolation, publication saves
and role visibility. No database migration or change to existing selections is
required. Deploy only `market-intelligence`, with its scanned immutable image.

Official references checked on 2026-10-05:

- https://developers.openai.com/api/docs/models/gpt-6.1-sol
- https://developers.openai.com/api/docs/models/gpt-6-luna
- https://developers.openai.com/api/docs/guides/latest-model/gpt-6-astra.md#migration-quickstart
