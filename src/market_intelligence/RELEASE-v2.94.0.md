# Bee CFO / Bee Researcher v2.94.0

## Telegram report layout

- Reworked the media outlook card into explicit bullet-point categories by
  time horizon and direction: rising, falling, unchanged, no explicit
  forecast, and internal media conflict.
- Each article-level opinion is rendered as its own linked bullet, preserving
  multiple statements from one outlet and making the original article easy to
  open.
- Added compact weighted-consensus metadata and a clear disclaimer without
  turning the report into a personalized recommendation.
- The media outlook card now has a dedicated 3,900-character Telegram-safe
  budget, while the main market brief keeps its existing 1,200-character limit.
- Bumped the Telegram renderer revision to `bee-cfo-telegram-11`.

## Scope and verification

- Only the isolated Bee CFO market-intelligence renderer and its tests were
  changed; Bee Researcher and Bee Consultant runtime behavior is untouched.
- The live sample report was sent after the full 200-test suite passed; its
  delivery used the new media renderer and the existing price/report order.
