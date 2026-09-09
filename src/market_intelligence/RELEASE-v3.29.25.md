# Bee Researcher v3.29.25

## Locale-consistent Assistants layout

- The Assistants page now uses one shared layout contract for English, Persian,
  Turkish, Arabic, Spanish, Italian, German and French.
- Page actions stay inline with text-sized controls; the English-only stacked
  action state caused by the legacy reference skin is removed.
- Assistant-card actions use a stable two-column layout with safe wrapping for
  long translations and a single primary-action order.
- Locale changes now affect copy and direction only; they no longer change the
  page geometry or persist stale measured widths.

## Verification

- Full unit suite: 329 tests passed.
- Browser style probe: Assistants page checked in all eight supported locales.
- English and Turkish screenshots now share the same action and card geometry.
- Service health: healthy after deploy.
