# Bee Researcher v3.29.14

## Support route visibility fix

- Fixed the final Support stylesheet overriding the shared `.view` visibility
  contract with an unconditional `display: block`.
- Support is now hidden by default and becomes visible only when the router
  adds the `active` class to `#view-support`; it no longer appears beneath
  other Admin pages.
- Added a regression test covering the active-only display rule.

Verification: full automated test suite passed.

