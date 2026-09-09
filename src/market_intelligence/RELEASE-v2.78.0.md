# Bee Researcher v2.78.0

## Roadmap delivery

- **MI-134 — clean sidebar footer:** the build version number is no longer rendered in the sidebar; the account dropdown remains anchored at the bottom of the navigation.
- **MI-135 — bilingual shared header:** the Assistant header shell is applied to every authenticated view in both English and Persian, while the active-page title and localized labels continue to update through the existing language flow.
- **MI-136 — editable bot ID:** bot identity settings expose a numeric bot-ID input and persist it through the existing Telegram settings API without exposing the secure token.
- **MI-137 — quick assistant setup:** the approved quick-setup action is visible again on the Assistants page. It generates an editable draft suggestion and requires review before creation.
- **MI-138 — unique security rows:** the user table now has a final client-side identity guard in addition to the API canonicalization, so duplicate owner rows cannot be rendered from a stale payload.

## Verification

- Python bytecode compilation and `git diff --check` completed successfully.
- Targeted security/UI tests cover the account dedupe, shared header, sidebar account menu, quick setup, version hiding, and bot-ID field.
- Full Docker test run: **160 tests executed; 158 passed**. The two existing failures are environment assertions for `scheduler_enabled` and `auto_publish`, not regressions from MI-134–MI-138.
