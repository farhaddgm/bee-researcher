# Bee Researcher v3.20.0

## Complete locale-aware UX writing

- Added the remaining interface copy discovered in `admin_ui.py` to the
  `UX Writing` Google Sheet, preserving the existing rows and using the
  approved `GOOGLETRANSLATE` formulas as reviewable drafts for Turkish,
  Arabic, Italian, Spanish, German and French.
- The runtime now merges the sheet-derived additions into its catalog and
  applies the selected locale to dynamic dashboard labels, statuses, action
  cards, table headings and empty states without translating user content.
- Added reviewed dashboard translations for all eight supported locales and
  removed the Persian-digit fallback from Latin-script locales.

Verification: 278 automated tests passed in the rebuilt Docker image.
