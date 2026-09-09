# Bee Researcher v3.21.9

## Support localization correction

- Ticket categories now render from the selected locale in every queue. A
  category ticket no longer falls back to the English stored subject; only a
  user-entered “Other” subject remains custom text.
- Retained the v3.21.8 queue, validation, retry, and owner-inbox fixes.

## Verification

- Python compilation and `git diff --check` pass.
- Full application test suite passes in the release container.
- Production health endpoint reports healthy PostgreSQL and Redis dependencies.
