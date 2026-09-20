# Bee Researcher v3.30.10

## Responsive admin action stability

- Fixed a self-triggering DOM-mutation loop in the admin action normalizer.
  The loop continuously reordered already-correct buttons after every render,
  causing unnecessary main-thread work and intermittent click handling on
  desktop layouts.
- Action groups are now reordered only when their actual DOM order differs.
  This keeps media and topic creation controls stable at full-page width and
  when the viewport changes.

## Regression coverage

- Added a server-side guard against reintroducing unconditional action
  reordering in the observed UI tree.
- Added a browser hit-test regression probe that physically clicks Add media
  and Add topic across common desktop and compact viewport widths.
