# Bee Researcher — v3.29.27

## Product typography

- Standardized the Admin and User back-office shells on the IranSans font stack for every supported locale.
- Removed the Admin shell's Vazirmatn web-font import so a late stylesheet load cannot change typography after first paint.
- Kept typography inherited by buttons, form controls, tables, dialogs and dynamically rendered content.

## Verification

- `python3 -m compileall -q app/market_intelligence/app`
- `python -m unittest discover -s /app/tests -p 'test_*.py'` — 329 tests passed in the container.
- Browser smoke checks continue to cover all eight Admin locales.
