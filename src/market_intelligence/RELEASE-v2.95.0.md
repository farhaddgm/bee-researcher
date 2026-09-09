# Bee CFO / Bee Researcher v2.95.0

## Telegram report layout

- Removed Bee CFO's internal 1,200-character truncation from the main market
  analysis. The Telegram transport now uses a safe 3,900-character chunk size
  and preserves the complete report across messages when needed.
- Each media time horizon is delivered as its own standalone Telegram message.
- Horizon cards use the order `افزایشی`, `کاهشی`, `بدون تغییر`, and `دارای اختلاف`.
- Category rows contain only hyperlinked media names; article prose is not
  repeated in the media card.
- Internal contradictions are shown only under `دارای اختلاف` for that
  horizon, so a single outlet is not counted simultaneously as rising and
  falling in the display.

## Scope and verification

- Bee Researcher and Bee Consultant runtime behavior is untouched.
- Full test suite: 200 tests passed.
