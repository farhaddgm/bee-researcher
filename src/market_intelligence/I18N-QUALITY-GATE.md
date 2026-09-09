# Bee Researcher internationalisation quality gate

## Supported locales

The back-office now exposes `en`, `fa`, `tr`, `ar`, `es`, `it`, `de` and `fr` in
the same language selector. Persian and Arabic use RTL layout; the other
locales use LTR layout. The UX Writing sheet is the eight-column source of
truth (`فارسی`, `انگلیسی`, `ترکی`, `عربی`, `ایتالیایی`, `اسپانیایی`, `آلمانی`,
`فرانسه`).

## Promotion rules

- Every static label, placeholder, action, error and accessibility label must
  have a row in the UX Writing catalog and a locale entry or an intentional
  English product term. Runtime fallback must never return Persian for a
  non-Persian locale.
- Dynamic cards and dialogs must be checked after a project switch and a full
  refresh; no stale language from the previous account may remain.
- A native reviewer for each locale signs off terminology, pluralisation,
  dates and RTL/LTR alignment before that locale is enabled for general users.
- Product data (news titles, source names and business text) is not translated
  automatically; it remains user content.

## Current state

The locale registry, selector, direction handling, French locale and common
product labels are implemented in v3.18.0. Turkish, Arabic, Spanish, Italian,
German and French still require native review for terminology, pluralisation,
dates and RTL/LTR alignment before general-user promotion; English fallback is
explicitly used for any specialized product copy without a reviewed entry.
