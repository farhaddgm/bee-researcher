# Bee Researcher v2.21.0

## Back-office correctness pass for MI-033 / MI-034

- Multiple business profiles per assistant, with active-profile selection and safe deletion rules.
- Per-assistant execution settings: news cap, supported OpenAI analysis model, feedback allowlist and 7×24 schedule.
- Scheduler now executes active/testing assistants using their workspace schedule and assistant-scoped idempotency keys.
- Feedback API and Telegram callbacks enforce the selected assistant's allowlist; reports include per-user totals, related and unrelated counts.
- Role assignment prevents non-admin users from granting an equal or higher role.
- Responsive layout hardening, stable vertical scrollbar, business navigation and clearer schedule controls.
- Migration `0010_multi_business_profiles` removes the MVP singleton constraint while preserving existing profile id `1`.
