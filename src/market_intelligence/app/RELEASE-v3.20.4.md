# Bee Researcher v3.20.4

## Locale-safe error and first-paint handling

- Keeps the selected locale active from the first language render instead of
  collapsing non-English locales to Persian while the page initializes.
- Routes validation and API error messages through the eight-locale UX writing
  catalog, preventing Persian leakage in Turkish, Arabic, Italian, Spanish,
  German and French.
- Corrects short, action-oriented translations for common statuses and
  assistant-card actions; compact buttons now ellipsize safely when a locale
  needs more space.
