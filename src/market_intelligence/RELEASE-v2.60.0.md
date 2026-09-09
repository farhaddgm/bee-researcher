# Release v2.60.0

## Approved market-insight ideas

- Added a review-first `/insights` projection per workspace with urgent/digest priority, explainable quality score, source-conflict signals, trend radar and source-health summary.
- Added a controlled official-homepage fallback action for degraded sources. It never bypasses robots, paywalls or access controls and requires an authenticated project write permission.
- Added on-demand, non-persistent translation through the already approved OpenAI connection. The translated result is returned for review and is not published automatically.
- Added the back-office quality/trend panel to the news review page. It is additive and keeps the existing queue available if insight loading fails.
- Existing feedback storage already accepts an optional note; the insight projection surfaces the resulting review signal without applying ranking automatically.

## Verification

- All existing tests plus insight projections and UI regression checks must pass before deployment.
- No secrets are stored in the roadmap, UI, insight response or translation result.
