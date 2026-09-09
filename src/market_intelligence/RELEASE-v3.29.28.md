# Bee Researcher — v3.29.28

## IranSans coverage

- Applied the IranSans stack to the Admin and User back-office shells across every supported locale.
- Made all form controls inherit the shell font; the User search input no longer falls back to Arial.
- Removed the Admin Vazirmatn web-font import to prevent a late typography swap.

## Verification

- `python3 -m compileall -q app/market_intelligence/app`
- Browser font probe: Admin `en`, `tr`, `fa`, `ar`, `es`, `it`, `de`, `fr` plus User shell; body, buttons and inputs report the IranSans stack.
- Unit suite: 329 tests passed in the container.
