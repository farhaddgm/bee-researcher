# Bee Researcher v3.21.5

## Owner-only collection and analysis settings

- Moved the collection and analysis schedule out of the Channels page; it now
  lives in Project Settings and is visible/editable only for the Owner.
- New projects use three collection windows per day (10:00, 14:00 and 18:00)
  across all seven days. Publication scheduling remains independent.
- Kept bounded defaults for collection capacity: 50 items per source, up to
  1,000 items per run, and up to 1,000 items per project day. The project
  timezone and freshness window continue to apply.
- Added localized field explanations to the `i` tooltips for all eight
  supported interface languages, including the enable switch and capacity
  fields.

## Verification

- Python compilation and `git diff --check` passed.
- Full unittest suite is run as part of the release deployment.
