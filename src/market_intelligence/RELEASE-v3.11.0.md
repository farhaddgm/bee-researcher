# Bee Researcher — v3.11.0

## Scope

This release implements the approved roadmap batch MI-181–MI-205.

## Included

- Project slug editing is validated server-side and remains globally unique.
- Assistant editing now exposes the slug in create and edit flows, with localized labels and confirmation copy.
- Dynamic overview, news-list, feedback-learning and business-knowledge content follows the selected language.
- Login fields have stable sizing and direction-aware alignment; progress bars that had no user meaning are hidden.
- The content-template editor is mounted on a dedicated Content page and enforces a maximum of one blank line between blocks.
- Business cards expose an explicit activate/deactivate action.
- Field helper text is available through accessible `i` tooltips, keeping forms compact.
- Collapsed-sidebar account menus are rendered outside the narrow sidebar clipping region.

## Verification

- Python source compilation: passed.
- `git diff --check`: passed.
- Full application test suite: run in the production image before promotion.

## Notes

The internationalization framework remains additive: Persian and English are complete for this release; Turkish, Arabic, Spanish, Italian and German require native copy review before they are promoted as production translations.
