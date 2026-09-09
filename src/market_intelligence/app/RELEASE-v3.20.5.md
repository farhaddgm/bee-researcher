# Bee Researcher v3.20.5

## Reader portal hardening and usability

- Removed the `/user` portal's two-step verification challenge and its
  verification endpoint. Reader login now uses the portal's isolated,
  password-only session and never exposes back-office settings.
- Added reader-owned preferences for two-to-four card columns, text direction,
  Honey/Default/Dark/Red themes and browser notifications. Preferences are
  stored under the authenticated reader and cannot change workspace data.
- Added twelve-card pagination, safe HTML-to-text rendering, the requested
  `YYYY-Month-DD HH:MM` timestamp format and an IRANSans-first content font
  stack to the reader portal. The header logo now uses the larger back-office
  size.

## Quality and security gates

- Added a deterministic UX-writing catalog audit to CI for all eight locales;
  template expressions are excluded from the static-copy denominator.
- Added an opt-in `MARKET_INTELLIGENCE_CSP_STRICT=true` enforcement switch.
  Compatibility mode remains the default until browser smoke confirms that
  all legacy inline attributes have migrated; strict mode contains no
  `unsafe-inline` exception.

## Verification

- Python compilation and the catalog audit pass locally.
- The Docker unit/contract suite is the release gate before promotion.
