# Bee Researcher 3.37.0 — approved business research context

- Contenter stays the business-profile source of truth; link/sync alone never
  activate model use or change a real project's publication rules.
- Project-scoped approval UI selects approved sections and verified facts, gets
  explicit AI consent, previews recent news, then saves a shadow or live policy.
- Independent topic and business scores with validated exact news quotes and
  approved claim IDs; no weighted average or lexical publication shortcut.
- Topics-only, contextual and focused policies. Focused requires both gates;
  uncertainty, partial text, stale context and missing assessment fail closed.
- Shadow retains any previous live policy rather than accidentally disabling it.
- Immutable, pinned briefs and assessments; full news-text hashes, model identity,
  actor/project-bound one-use previews, expiry and config-change invalidation.
- Withdrawn/expired facts, revoked links and changed local business cannot send
  stale private claims to AI. Sync never silently approves a new business version.
- Private business facts are withheld from public report generation by default;
  disclosure needs explicit approval. Source output languages remain independent.
- Unpublished stale reports are regenerated with context provenance; delivery
  rechecks current relevance, provenance, language and existing idempotency.
- Separate, CSP-compatible UI controller/styles, eight locale catalogs, responsive
  modal/forms, keyboard/focus behavior and scoped viewer/editor permissions.
- Additive migration 0042; new context/preview/assessment tables and report
  provenance. No account, source, topic, schedule or real project auto-activation.
- Required SQL and browser regression steps added to CI, without successful skips.

Documentation: docs/RESEARCH-CONTEXT-fa.md.
Executed checks and limitations: docs/RESEARCH-CONTEXT-VERIFICATION-fa.md.
This release note is not a production deployment receipt.
