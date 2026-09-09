# Bee Researcher v2.89.0

## Completed roadmap items

- **MI-164 — Support tickets:** added an owner-routed support inbox in the back office. Users can submit a ticket with priority and project context; the owner can update status and reply. Access is scoped to the creator or owner and actions are audited.
- **MI-165 — Explicit refresh:** removed the periodic appearance/status refresh job and its recurring toast. Manual refresh remains available, reducing background load and surprise UI updates.
- **MI-166 — Featured images:** extracts public `og:image`, Twitter image, or JSON-LD image metadata. The owner can opt the Featured image block into the content template; when enabled, Telegram publishes it as a photo with the existing feedback buttons. Missing or unsafe images fall back to text-only delivery.

## Verification

- Python compilation and unit/component tests passed before production rollout.
- Production health endpoint returned `healthy` on v2.89.0.

## Notes

WhatsApp roadmap rows MI-066 and MI-108 remain infrastructure-ready but require official Meta credentials and a public webhook before production activation.

## Bee CFO benchmark package

- Added isolated evidence cards, novelty/duplicate metrics, descriptive Media Pulse, model-agreement and coverage disclosures.
- Added draft-by-default alert rules, bilingual indicator aliases, a deduplicated event ledger and a relative-benchmark contract.
- Added delayed media forecast evaluation and scorecards gated at 20 observations per source/horizon.
- Telegram renderer revision 9 now includes exact media snippets while preserving the price → media outlook → news order.

Alembic head is `0023_bee_cfo_benchmark`; the full suite passed with 179 tests. External economic-calendar and relative-benchmark feeds remain explicit incomplete states until owner-approved direct sources are registered.
