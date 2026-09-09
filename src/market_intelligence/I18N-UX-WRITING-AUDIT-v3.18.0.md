# UX Writing audit — v3.18.0

## Scope

- Source: `app/admin_ui.py` (static markup, dynamic labels, placeholders,
  dialogs, actions and accessibility labels).
- Reference: the `UX Writing` tab in the Bee Researcher spreadsheet.
- Columns: Persian, English, Turkish, Arabic, Italian, Spanish, German and
  French, plus the existing page/section/type/source metadata.

## Result

- 392 catalog rows are present after the source audit (246 original rows plus
  newly discovered UI strings and action messages).
- The English column is populated for all discovered Persian strings that have
  a canonical `copyMap` entry.
- Reviewed translations are populated for the shared navigation and workflow
  vocabulary. Specialized copy is explicitly held for native review; the
  running UI uses the canonical English fallback instead of leaking Persian.
- French is registered as `fr-FR` and uses LTR layout.

## Maintenance rule

When a new visible string is added, add its Persian key and canonical English
value to `copyMap`, then add reviewed locale values before enabling that locale
for general users. The source audit and the UX Writing tab are the release
gate for preventing untranslated static UI text.
