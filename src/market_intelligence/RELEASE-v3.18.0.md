# Bee Researcher v3.18.0

## International UX Writing catalog

- Added an eight-locale UX Writing reference: Persian, English, Turkish,
  Arabic, Italian, Spanish, German and French.
- Registered French (`fr-FR`, LTR) in the back-office language selector while
  preserving the existing locale contract.
- Extended the runtime copy catalog so sign-in, navigation and common workflow
  actions are translated consistently in all selectable locales.
- Added a safe canonical-English fallback for specialized product copy; a
  fallback never returns Persian in a non-Persian locale.
- Added the source-audit entries needed to keep static labels, placeholders,
  actions, errors and accessibility labels discoverable in the UX Writing sheet.

## Verification

- `python3 -m py_compile app/admin_ui.py`
- Full market-intelligence unit test suite (including i18n contract checks).
- Runtime smoke check and migration-head check performed during deployment.

Native review remains required for Turkish, Arabic, Italian, Spanish, German
and French terminology, pluralisation, date formatting and RTL/LTR alignment
before those locales are promoted as final editorial copy.
