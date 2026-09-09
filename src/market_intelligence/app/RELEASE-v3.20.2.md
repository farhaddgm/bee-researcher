# Bee Researcher v3.20.2

## Fixed locale digit flicker in the back office

- Removed the global 500 ms digit-rewrite timer that raced with view
  renderers and caused visible Persian/Latin number flicker.
- Made digit normalization idempotent and event-driven: it runs after a
  language change and for newly inserted content only.
- The final `html[lang]` value is observed so additive locales cannot leave
  numbers formatted in the temporary legacy language.
- Added a contract test that prevents the polling timer from returning.
